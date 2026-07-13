"""④ Hypothesis 노드. 결정적 함수(룰베이스), LLM 미사용 — 2026-07-09 노드화 결정.

kg_rca가 이미 순회해 둔 candidate마다, candidate.tier가 어떤 MCP 도구를 부를지 결정한다.
candidate.cause/failure_mode 문자열은 fab.db와 join key가 아니다 — 실제 join은
candidate.evidence(Parameter/Maintenance/Recipe id)로만 이루어진다
(personalspace/0711 work/qna_0711.md Q5).

호출 규칙(모두 personalspace/0708 work/산출물_데이터모델설계.md §3.0/3.1 정본):
    - 모든 candidate 공통: run_commonality_analysis, get_normal_lot_ratio
    - tier == "자동"    (evidence_label == "Parameter") : + query_telemetry, 즉시 채택/기각까지
    - tier == "반자동"  (evidence_label == "Maintenance"): + get_maintenance_history, 사람 판정 필요
    - tier == "반자동"  (evidence_label == "Recipe")     : + get_lot_history(recipe_id 비교), 사람 판정 필요
    - tier == "근거없음"                                  : MCP 호출 없음

주의: mapping_table.yaml(fab.db 시나리오 근거)과 kg_rca cause 어휘가 대부분 안 겹친다.
"자동" candidate라도 fab.db에 실제로 주입된 신호가 없으면 "증거 없음"이 정상 결과다 —
personalspace/0711 work/kg_mapping_vocabulary.md 참고.
"""

from __future__ import annotations

from ..mcp_client import MCPClient
from ..state import EvidenceEntry, GraphRAGCandidate, Hypothesis, RCAState


async def build_hypotheses(
    state: RCAState, group_id: str, mcp: MCPClient
) -> dict:
    """group_id의 graphrag_candidates 각각에 증거를 모아 hypotheses[group_id]를 채운다.

    TODO:
      1. comm = await mcp.run_commonality_analysis(lot_ids)               # 공통, tier 무관
      2. suspect = top_equipment_for(comm, cand.step)
      3. neg = await mcp.get_normal_lot_ratio(suspect, time_range=...)    # 공통, tier 무관
      4. cand.tier로 분기해 _verify_candidate 호출
      5. Hypothesis 리스트로 조립해 반환
    """
    raise NotImplementedError


async def _verify_candidate(
    candidate: GraphRAGCandidate, suspect_equipment: str, mcp: MCPClient
) -> EvidenceEntry:
    """candidate.tier에 따라 정해진 MCP 도구만 호출해 EvidenceEntry를 채운다.

    TODO: tier == "자동"    -> query_telemetry(suspect, candidate.evidence, ...) 후
                                candidate.direction과 비교해 drift_detected 결정
          tier == "반자동"  -> evidence_label == "Maintenance"면 get_maintenance_history,
                                "Recipe"면 get_lot_history로 recipe_id 비교
          tier == "근거없음" -> MCP 호출 없이 빈 EvidenceEntry 반환
    """
    raise NotImplementedError
