"""라이브 KG 조회 클라이언트 (Mode B, (가) 전면 라이브).

파일(hypotheses.json)을 읽는 KGClient와 달리, 요청마다 Neo4j를 **직접 순회**한다.
- pattern이 3종(Center/Scratch/Edge-Ring)이면 패턴 진입(fetch_hypotheses).
- pattern이 Unknown이고 관측 signature(shape@zone)가 있으면 **형상 진입**
  (fetch_hypotheses_by_signature) — dedup에 안 먹혀 모든 FORMS_IN 엣지의 morphology가 보존된다.
그 뒤 angular 판별자(morphology_rank)로 재랭킹한다.

순회 로직은 kg_rca/6_ask_graphrag.py의 함수를 재사용한다(빌드 스크립트와 단일 진실).
숫자로 시작하는 모듈명이라 importlib로 지연 로드한다 — 이 로더 한 곳이 나중에 옵션 2
(의미 진입)로 갈 때 교체 지점이다. get_candidates 인터페이스는 KGClient와 동일해서
graph.py/batch_runner에 그대로 drop-in 된다.
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
        # 옵션 2: 주입되면 미지 패턴에서 자연어 서술을 의미 매칭해 진입 시그니처를 고른다.
        self._semantic = semantic_index
        self._semantic_k = semantic_k

    def get_candidates(self, pattern: str, observation: dict | None = None) -> dict:
        q = _query_layer()
        obs = observation or {}
        signature = obs.get("signature")
        description = obs.get("description")

        entry_signatures: list[str] = []
        if pattern in _KNOWN_PATTERNS:
            rows = q.fetch_hypotheses(self._graph, pattern)
        elif signature:
            # 미지 패턴, enum 진입: 형상(shape@zone) 정확일치
            rows = q.fetch_hypotheses_by_signature(self._graph, signature)
            entry_signatures = [signature]
        elif description and self._semantic is not None:
            # 미지 패턴, 의미 진입(옵션 2): 자연어 서술 -> top-k 시그니처 -> 각자 순회 후 합침
            matches = self._semantic.match(description, k=self._semantic_k)
            rows = []
            for sig, score in matches:
                for row in q.fetch_hypotheses_by_signature(self._graph, sig):
                    row["entry_signature"] = sig
                    row["entry_score"] = score
                    rows.append(row)
            entry_signatures = [sig for sig, _ in matches]
        else:
            return {"pattern": pattern, "candidates": []}

        candidates = [self._row_to_candidate(row, pattern, q) for row in rows]
        candidates = rerank_by_observation(candidates, observation)
        for i, candidate in enumerate(candidates, start=1):
            candidate["rank"] = i
        result = {"pattern": pattern, "candidates": candidates}
        if entry_signatures:
            result["entry_signatures"] = entry_signatures
        return result

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
            # 의미 진입(옵션 2)일 때만: 어느 시그니처로 어떤 유사도로 들어왔는지
            "entry_signature": row.get("entry_signature"),
            "entry_score": row.get("entry_score"),
        }
