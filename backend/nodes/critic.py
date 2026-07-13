"""⑤ Critic 노드. 결정적 함수(룰베이스), LLM 미사용 — 2026-07-09 노드화 결정.

4개 규칙을 순서대로 확인한다(semiconductor_proposal.md §7.2 Critic Workflow 정본):
    ① 시간 정합    — 원인 시각 < 결함 시각 아니면 reject("선후 뒤집힘") (함정 PM 필터링)
    ② 반대근거     — get_normal_lot_ratio를 안 돌렸으면(against is None) reject
    ③ faithfulness — 조회 안 된 값을 사실처럼 인용했으면 reject
    ④ KG 메커니즘 연결 — VERIFIED_BY 경로가 없으면 insufficient_evidence

채택 가능한 후보가 0개면 재시도 없이 즉시 insufficient_evidence를 반환한다.
재계획(replan) 루프는 없다(personalspace/0710 work/metadata.md §3.1).
"""

from __future__ import annotations

from ..mcp_client import MCPClient
from ..state import CriticResult, Hypothesis, RCAState


async def review_hypotheses(
    state: RCAState, group_id: str, mcp: MCPClient
) -> dict:
    """hypotheses[group_id]를 규칙대로 채택/기각하고 critic_result[group_id]를 채운다.

    TODO: 각 hypothesis에 _check_time_consistency -> _check_negative_evidence ->
          _check_faithfulness -> _check_kg_mechanism 순서로 적용.
          채택 후보가 0개면 status="insufficient_evidence", 아니면 "accepted".
    """
    raise NotImplementedError


async def _check_time_consistency(hypothesis: Hypothesis, mcp: MCPClient) -> bool:
    """get_lot_timeline으로 원인 이벤트 ts < 결함 발생 ts 확인. 실패 시 False(reject)."""
    raise NotImplementedError


def _check_negative_evidence(hypothesis: Hypothesis) -> bool:
    """evidence.normal_ratio가 None이면 반대증거 미수행 -> False(reject)."""
    raise NotImplementedError


def _check_faithfulness(hypothesis: Hypothesis) -> bool:
    """조회 실패/미확인 값을 사실처럼 인용했는지 확인. 위반 시 False(reject)."""
    raise NotImplementedError


def _check_kg_mechanism(hypothesis: Hypothesis) -> bool:
    """VERIFIED_BY 경로(evidence_label != None)가 있는지 확인. 없으면 False(insufficient_evidence)."""
    raise NotImplementedError
