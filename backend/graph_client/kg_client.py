"""kg_rca 가설 조회 클라이언트 (파일 기반).

kg_rca/6_ask_graphrag.py는 요청마다 도는 API가 아니라, 고정 3패턴(Center/Scratch/Edge-Ring)을
미리 순회해 kg_rca/outputs/hypotheses.json에 저장하는 배치 스크립트다. 그래프·패턴이 정적이라
④ 조회 노드(nodes/graphrag.py)는 이 파일을 패턴으로 필터링하는 것만으로 충분하다.
요청마다 Neo4j를 직접 순회하려면 LiveKGClient를 쓴다(KG_LIVE=1).
"""

from __future__ import annotations

import json
from pathlib import Path

from .morphology_rank import rerank_by_observation


class KGClient:
    def __init__(self, hypotheses_path: Path) -> None:
        self._hypotheses_path = hypotheses_path

    def get_candidates(self, pattern: str, observation: dict | None = None) -> dict:
        """패턴 이름 하나로 kg_rca가 미리 계산해 둔 가설 전체를 조회한다.

        반환 형태는 state.GraphRAGResult와 같다. 3종(Center/Edge-Ring/Scratch) 밖의 패턴이
        들어오면 candidates=[]를 반환하고(미매핑 패턴), graphrag.py가 이 그룹의 ④~⑥을 건너뛴다.

        observation(관측 모폴로지 {density, continuity, angular_coverage, clock_positions})을 주면
        angular 판별자로 후보를 재정렬한다(morphology_rank.py): angular full↔partial 상충 후보는
        리스트에서 제외하고, 소프트 상충은 감점만 한다. 관측이 없으면(None) kg_rca 순위 그대로 반환.

        필드 매핑(kg_rca 출력 -> state.GraphRAGCandidate) 정본은 kg_rca/KG_output_명세.md.
        출력에 `route`/`score.confidence`는 없다 — `scenario_hint`, `score.evidence_docs`/`evidence_chunks`를 옮긴다.
        """
        data = self._load()
        for question in data.get("questions", []):
            if question.get("pattern") != pattern:
                continue
            candidates = [self._to_candidate(h) for h in question.get("hypotheses", [])]
            candidates = rerank_by_observation(candidates, observation)
            return {"pattern": pattern, "candidates": candidates}
        return {"pattern": pattern, "candidates": []}

    @staticmethod
    def _to_candidate(hypothesis: dict) -> dict:
        path = hypothesis["path"]
        verification = hypothesis["verification"]
        score = hypothesis["score"]
        return {
            "cause": path["cause"],
            # 평가 전용: kg cause → mapping_table(ground truth) 어휘 번역(kg_rca mapping 블록).
            # 정답이 아니라 어휘 대응표라 정답 누출 아님 — 표시·판정엔 안 쓰고 E2E 평가만 쓴다.
            "matched_cause": (hypothesis.get("mapping") or {}).get("matched_cause"),
            # 처방2-b: cause의 fab 공정 소속(mapping.process). step=None 후보의 폴백으로만
            # 런타임 사용(hypothesis._with_step_fallback) — KG path.step이 있으면 안 씀.
            "mapped_process": (hypothesis.get("mapping") or {}).get("process"),
            "failure_mode": path["failure_mode"],
            "step": path["step"],
            "signature": path.get("signature"),
            "morphology": path.get("morphology"),
            "scenario_hint": hypothesis.get("scenario_hint"),
            "tier": hypothesis["tier"],
            "evidence_label": path["evidence_label"],
            "evidence": path["evidence"],
            "fab_table": verification["fab_table"],
            "direction": verification["direction"],
            "occurrence_prior": score["occurrence_prior"],
            "rank": hypothesis.get("rank"),
            "evidence_docs": score.get("evidence_docs"),
            "evidence_chunks": score.get("evidence_chunks"),
            "unverifiable_signals": verification.get("unverifiable_signals"),
            "sentence": hypothesis["sentence"],
            "citations": KGClient._to_citations(hypothesis.get("provenance")),
        }

    @staticmethod
    def _to_citations(provenance: dict | None) -> list[dict]:
        """provenance.chunk_ids의 문서명("문서명#c00")을 {id, text} 인용 목록으로 유도한다.

        같은 문서의 청크 여러 개는 문서 1건으로 접는다(등장 순서 유지, id는 후보 내 1부터).
        API 명세 §2.5/§2.7 citations[] — 인용 없으면 [](null 금지).
        """
        if not provenance:
            return []
        seen: list[str] = []
        for chunk_id in provenance.get("chunk_ids", []):
            doc = chunk_id.rsplit("#", 1)[0]
            if doc not in seen:
                seen.append(doc)
        return [{"id": i + 1, "text": doc} for i, doc in enumerate(seen)]

    def _load(self) -> dict:
        return json.loads(self._hypotheses_path.read_text(encoding="utf-8"))
