"""라이브 KG 조회 클라이언트 — 파일(hypotheses.json)을 읽는 KGClient와 달리 Neo4j를 요청마다 직접 순회한다.

진입 방식(관측 내용에 따라 자동 선택):
- pattern이 3종(Center/Scratch/Edge-Ring)이면 패턴 진입(fetch_hypotheses).
- 관측에 자연어 서술이 있으면 **의미 진입**: 자연어를 임베딩해 시그니처와 유사도 매칭.
  기지 패턴은 HAS_SIGNATURE로 범위를 좁혀 그 안에서, Unknown은 전체에서 고른다.
- 관측이 shape@zone enum을 직접 주면 **형상 정확 진입**(fetch_hypotheses_by_signature)
  — 패턴을 거치지 않아 미지 패턴도 조회 가능하고, 패턴 진입의 dedup(공정 경로 우선)에
  먹히지 않아 모든 FORMS_IN 엣지의 morphology가 후보에 보존된다.
그 뒤 angular_coverage 판별자(morphology_rank)로 재랭킹한다.

순회 로직은 kg_rca/6_ask_graphrag.py의 함수를 재사용한다(빌드 스크립트와 단일 진실).
숫자로 시작하는 모듈명이라 importlib로 지연 로드한다. get_candidates 인터페이스는
KGClient와 동일해서 graph.py/batch_runner에 그대로 drop-in 된다.
"""

from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path

from .kg_client import KGClient
from .morphology_rank import rerank_by_observation

_KNOWN_PATTERNS = {"Center", "Scratch", "Edge-Ring"}


@lru_cache(maxsize=1)
def _query_layer():
    """kg_rca/6_ask_graphrag.py의 순회 함수를 지연 로드(1회 캐시). import 부작용 회피용."""
    path = Path(__file__).resolve().parents[2] / "kg_rca" / "6_ask_graphrag.py"
    spec = importlib.util.spec_from_file_location("_kg_query_layer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LiveKGClient:
    """Neo4j 라이브 순회. KGClient와 동일한 get_candidates(pattern, observation) 인터페이스."""

    def __init__(self, graph, semantic_index=None, semantic_k: int = 3) -> None:
        self._graph = graph
        # 의미 진입 인덱스: 주입되면 관측의 자연어(location+morphology_text)를 임베딩 유사도로
        # 매칭해 진입 시그니처를 고른다. 기지 패턴이면 그 패턴의 HAS_SIGNATURE 시그니처로
        # 검색 범위를 좁히고, Unknown이면 전체에서 찾는다.
        self._semantic = semantic_index
        self._semantic_k = semantic_k

    # CNN 패턴이 좁혀주는 시그니처 검색 범위 — "문헌상 이 패턴이 나타나는 형상들"
    _PATTERN_SIGNATURES_QUERY = (
        "MATCH (:DefectPattern {id: $pattern})-[:HAS_SIGNATURE]->(g:SpatialSignature) "
        "RETURN g.id AS sig"
    )

    def get_candidates(self, pattern: str, observation: dict | None = None) -> dict:
        """VLM 자연어(location_text+morphology_text)가 진입 쿼리를 이끈다.
        CNN 패턴은 검색 "범위"를 좁히고, 자연어가 그 범위 안에서 진입 시그니처를 고른다.

        - pattern_candidate(CNN)가 3종이면 그 패턴의 HAS_SIGNATURE 시그니처로 **범위를 좁히고**,
          자연어 임베딩이 그 안에서 진입 시그니처를 고른다. 패턴 레벨 원인(공정 경유·문헌 직결)도 유지.
        - Unknown이면 자연어가 전체 시그니처에서 진입을 고른다(범위 제한 없음).
        - 관측이 shape@zone(enum)을 직접 주면 그대로 정확 진입. 자연어/의미 인덱스가 없으면
          기지 패턴은 패턴 진입으로 폴백.
        그 뒤 morphology 판별자로 재랭킹한다.
        """
        q = _query_layer()
        obs = observation or {}
        exact_sig = obs.get("signature")
        query_text = self._query_text(obs)
        known = pattern in _KNOWN_PATTERNS

        entry_signatures: list[str] = []
        rows: list[dict] = []

        if exact_sig:
            # enum 정확 진입 (관측이 shape@zone을 직접 준 경우)
            rows = q.fetch_hypotheses_by_signature(self._graph, exact_sig)
            entry_signatures = [exact_sig]
        elif query_text and self._semantic is not None:
            # 자연어 진입: known이면 패턴의 시그니처로 범위 제한, 아니면 전체
            scope = self._pattern_signatures(pattern) if known else None
            matches = self._semantic.match(query_text, k=self._semantic_k, allowed=scope)
            for sig, score in matches:
                for row in q.fetch_hypotheses_by_signature(self._graph, sig):
                    row["entry_signature"] = sig
                    row["entry_score"] = score
                    rows.append(row)
            entry_signatures = [sig for sig, _ in matches]
            if known:
                # 형상 경로는 위 NL-선정 시그니처로 대체했으니, 패턴 레벨 원인만 더한다
                rows += q.fetch_hypotheses_step_direct(self._graph, pattern)
        elif known:
            # 자연어/의미 인덱스 없을 때 폴백: 패턴 진입(기존)
            rows = q.fetch_hypotheses(self._graph, pattern)
        else:
            return {"pattern": pattern, "candidates": []}

        candidates = [self._row_to_candidate(row, pattern, q) for row in rows]
        candidates = self._dedup(candidates)
        candidates = rerank_by_observation(candidates, observation)
        for i, candidate in enumerate(candidates, start=1):
            candidate["rank"] = i
        result = {"pattern": pattern, "candidates": candidates}
        if entry_signatures:
            result["entry_signatures"] = entry_signatures
        return result

    @staticmethod
    def _query_text(obs: dict) -> str | None:
        """VLM 자연어를 하나의 검색 질의로 합친다: location_text + morphology_text (없으면 description)."""
        parts = [obs.get("location_text"), obs.get("morphology_text")]
        parts = [p for p in parts if p]
        if not parts and obs.get("description"):
            parts = [obs["description"]]
        return "\n".join(parts) if parts else None

    def _pattern_signatures(self, pattern: str) -> set:
        rows = self._graph.query(self._PATTERN_SIGNATURES_QUERY, params={"pattern": pattern})
        return {row["sig"] for row in rows}

    @staticmethod
    def _dedup(candidates: list[dict]) -> list[dict]:
        """같은 (step, failure_mode, cause, evidence) 꼬리는 하나만.

        형상 경로(morphology 있음)와 패턴 레벨 경로(morphology None)가 같은 꼬리에 닿으면,
        morphology 있는 쪽을 남긴다 — 판별자가 쓸 신호를 보존하기 위함.
        """
        best: dict[tuple, dict] = {}
        for candidate in candidates:
            key = (candidate.get("step"), candidate.get("failure_mode"),
                   candidate["cause"], candidate.get("evidence"))
            existing = best.get(key)
            if existing is None or (
                candidate.get("morphology") is not None and existing.get("morphology") is None
            ):
                best[key] = candidate
        return list(best.values())

    @staticmethod
    def _row_to_candidate(row: dict, pattern: str, q) -> dict:
        """_rank_and_sort가 낸 평탄한 행을 state.GraphRAGCandidate 형태로 옮긴다.

        KGClient._to_candidate가 hypotheses.json(중첩)에서 옮기는 것과 같은 결과를,
        여기서는 라이브 행(평탄)에서 만든다. 문장은 LLM 없이 결정적 fallback으로 채운다.
        """
        signature = row.get("signature")
        morphology = None
        if signature is not None:
            morphology = {
                "density": row.get("density"),
                "continuity": row.get("continuity"),
                "angular_coverage": row.get("angular_coverage"),
                "clock_positions": row.get("clock_positions") or [],
            }
        tier = row["tier"]
        fab_table = row.get("fab_table")
        return {
            "cause": row["cause"],
            "failure_mode": row.get("failure_mode"),
            "step": row.get("step"),
            "signature": signature,
            "morphology": morphology,
            "scenario_hint": q.scenario_hint(row),
            "tier": q.TIER_TAG[tier],
            "evidence_label": row["evidence_label"],
            "evidence": None if tier == q.TIER_NONE else row["evidence"],
            "fab_table": None if fab_table == "-" else fab_table,
            "direction": row.get("direction"),
            "occurrence_prior": row.get("occurrence_prior"),
            "evidence_docs": row.get("evidence_docs"),
            "evidence_chunks": row.get("evidence_chunks"),
            "unverifiable_signals": row.get("unverifiable_signals") or None,
            "sentence": q._fallback_sentence(pattern or "관측 형상", row),
            "citations": KGClient._to_citations({"chunk_ids": row.get("chunk_ids") or []}),
            # 자연어 의미 진입일 때만: 어느 시그니처로 어떤 유사도로 들어왔는지
            "entry_signature": row.get("entry_signature"),
            "entry_score": row.get("entry_score"),
        }
