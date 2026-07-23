"""kg_rca(GraphRAG) 결과 조회 클라이언트.

kg_rca/6_ask_graphrag.py는 요청마다 도는 API가 아니라, 고정 3패턴(Center/Scratch/Edge-Ring)
전체를 미리 계산해 kg_rca/outputs/hypotheses.json에 저장해두는 배치 스크립트다
(personalspace/0711 work/qna_0711.md Q6). 그래프·패턴이 정적이므로, ③ GraphRAG 노드는
기본적으로 이 파일을 패턴으로 필터링하는 것만으로 충분하다 — 라이브 Neo4j 쿼리가
필요해지면 kg_rca.fetch_hypotheses(graph, pattern)를 그대로 재사용한다(같은 함수가 이미
재사용 가능한 형태로 분리돼 있음).
"""

from __future__ import annotations

import json
from pathlib import Path

from .morphology_rank import rerank_by_observation


class KGClient:
    def __init__(self, hypotheses_path: Path) -> None:
        self._hypotheses_path = hypotheses_path

    def get_candidates(self, pattern: str, observation: dict | None = None) -> dict:
        """패턴 이름 하나로 kg_rca가 이미 계산해 둔 가설 전체를 조회한다.

        반환 형태는 state.GraphRAGResult와 같다. Center/Edge-Ring/Scratch 3종 밖의
        패턴이 들어오면(UC-3, 미매핑 패턴) candidates=[]를 반환한다 — 이 경우 그래프의
        graphrag.py가 이 그룹의 ④~⑥을 건너뛴다.

        observation을 주면(관측 모폴로지 {density, continuity, angular_coverage, clock_positions})
        angular_coverage 판별자로 후보를 재정렬한다(morphology_rank.py). 상충 후보만
        아래로 내리는 감점 전용이라, 관측이 없으면(None) kg_rca 순위를 그대로 반환한다.

        필드 매핑(kg_rca 출력 -> state.GraphRAGCandidate)은 kg_rca/KG_output_명세.md(schema v2.4)가
        정본이다. 07-13 갱신으로 `route`/`score.confidence`가 출력에서 빠졌다 — 대신 `scenario_hint`,
        `score.evidence_docs`/`evidence_chunks`를 옮긴다.
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
