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


async def review_hypotheses(state: RCAState, group_id: str, mcp: MCPClient) -> dict:
    """hypotheses[group_id]를 규칙대로 채택/기각하고 critic_result[group_id]를 채운다.

    문서 순서(①시간정합 ②반대근거 ③faithfulness ④KG메커니즘) 그대로 적용한다.
    채택 후보가 0개면 status="insufficient_evidence", 아니면 "accepted".
    """
    group = next((g for g in state["groups"] if g["group_id"] == group_id), None)
    lot_id = group["lot_ids"][0] if group and group["lot_ids"] else None
    candidates = state["hypotheses"].get(group_id, [])

    accepted: list[Hypothesis] = []
    rejected: list[dict] = []
    for h in candidates:
        if lot_id is not None and not await _check_time_consistency(h, mcp, lot_id):
            rejected.append({**h, "reject_reason": "시간 정합 실패 — 원인이 결함 발생보다 늦음"})
        elif not _check_negative_evidence(h):
            rejected.append({**h, "reject_reason": "반대증거(normal_ratio) 미수행"})
        elif not _check_faithfulness(h):
            rejected.append({**h, "reject_reason": "faithfulness 위반 — 확인 안 된 값을 근거로 사용"})
        elif not _check_kg_mechanism(h):
            rejected.append({**h, "reject_reason": "KG 메커니즘 연결 없음(근거없음 등급)"})
        else:
            accepted.append(h)

    status: str = "accepted" if accepted else "insufficient_evidence"
    result: CriticResult = {"status": status, "accepted": accepted, "rejected": rejected}
    return {"critic_result": {group_id: result}}


async def _check_time_consistency(hypothesis: Hypothesis, mcp: MCPClient, lot_id: str) -> bool:
    """get_lot_timeline으로 원인 이벤트 ts < 결함 발생(EDS) ts 확인. 실패 시 False(reject).

    비교할 원인 이벤트가 없는 hypothesis(정비 이력이 안 잡힌 경우)는 시간 정합 검사 대상이
    아니므로 통과시킨다 — 이 규칙은 "함정 정비"(결함 이후에 이뤄진 정비) 배제가 목적이다.
    """
    maintenance_ts = hypothesis["evidence"].get("maintenance_ts")
    if maintenance_ts is None:
        return True

    timeline = await mcp.get_lot_timeline(lot_id)
    eds_events = [e for e in timeline["data"] if e["detail"] == "EDS"]
    if not eds_events:
        return True
    defect_ts = max(e["ts"] for e in eds_events)
    return maintenance_ts < defect_ts


def _check_negative_evidence(hypothesis: Hypothesis) -> bool:
    """evidence.normal_ratio가 None이면 반대증거 미수행 -> False(reject)."""
    return hypothesis["evidence"].get("normal_ratio") is not None


def _check_faithfulness(hypothesis: Hypothesis) -> bool:
    """조회 실패/미확인 값을 사실처럼 인용했는지 확인. 위반 시 False(reject).

    0713 단순화: `[자동]` 후보인데 query_telemetry는 불렀지만 정상범위 자체가 없어
    drift_detected를 못 정한 경우만 위반으로 본다. 실제 문장 단위 사실 대조는
    스텝7(response.py, LLM)이 붙은 뒤 다시 설계해야 한다.
    """
    if hypothesis["tier"] == "자동":
        return hypothesis["evidence"].get("drift_detected") is not None
    return True


def _check_kg_mechanism(hypothesis: Hypothesis) -> bool:
    """VERIFIED_BY 경로(evidence_label != None)가 있는지 확인. 없으면 False(insufficient_evidence)."""
    return hypothesis["tier"] != "근거없음"
