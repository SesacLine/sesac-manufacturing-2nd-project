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

# 고정 사유 토큰(사유코드) — API가 verdict 3-state 승격을 이 토큰으로만 분기한다
# (API 명세 §2.7 "verdict 매핑 주의": 자연어 reject_reason 본문 매칭 금지).
# P2/P3/P4는 verdict="rejected", P5는 verdict="insufficient"로 승격된다.
TOKEN_TIME_ORDER = "P2_TIME_ORDER"
TOKEN_NO_COUNTER_EVIDENCE = "P3_NO_COUNTER_EVIDENCE"
TOKEN_FAITHFULNESS = "P4_FAITHFULNESS"
TOKEN_NO_KG_MECHANISM = "P5_NO_KG_MECHANISM"
# semi_auto 잠정 자동 기각(명세 §2.5 tier 🔲 · §4-2 미결정 대기 — 사람 판정 경로가 생기면 제거)
TOKEN_SEMI_AUTO_PENDING = "SEMI_AUTO_AUTO_REJECT"


async def review_hypotheses(state: RCAState, group_id: str, mcp: MCPClient) -> dict:
    """hypotheses[group_id]를 규칙대로 채택/기각하고 critic_result[group_id]를 채운다.

    문서 순서(①시간정합 ②반대근거 ③faithfulness ④KG메커니즘) 그대로 적용한다.
    채택 후보가 0개면 status="insufficient_evidence", 아니면 "accepted".
    기각 항목에는 reject_reason(표시용 자연어)과 reject_token(고정 사유코드)을 같이 싣는다.
    """
    candidates = state["hypotheses"].get(group_id, [])

    accepted: list[Hypothesis] = []
    rejected: list[dict] = []
    for h in candidates:
        if not _check_time_consistency(h):
            rejected.append({
                **h,
                "reject_token": TOKEN_TIME_ORDER,
                "reject_reason": "시간 정합 실패 — 원인이 결함 발생보다 늦음",
            })
        elif not _check_negative_evidence(h):
            rejected.append({
                **h,
                "reject_token": TOKEN_NO_COUNTER_EVIDENCE,
                "reject_reason": "반대증거(normal_ratio) 미수행",
            })
        elif not _check_faithfulness(h):
            rejected.append({
                **h,
                "reject_token": TOKEN_FAITHFULNESS,
                "reject_reason": "faithfulness 위반 — 확인 안 된 값을 근거로 사용",
            })
        elif not _check_kg_mechanism(h):
            rejected.append({
                **h,
                "reject_token": TOKEN_NO_KG_MECHANISM,
                "reject_reason": "KG 메커니즘 연결(VERIFIED_BY) 없음",
            })
        elif h["tier"] == "반자동":
            # 잠정(명세 §2.5 🔲·§4-2): 사람 판정 경로가 정립되지 않아 반자동 등급은
            # 규칙을 통과해도 자동 기각으로 처리한다. 경로가 생기면 이 분기를 걷어낸다.
            rejected.append({
                **h,
                "reject_token": TOKEN_SEMI_AUTO_PENDING,
                "reject_reason": "반자동 등급 — 사람 판정 경로 미정립으로 잠정 자동 기각",
            })
        else:
            accepted.append(h)

    status: str = "accepted" if accepted else "insufficient_evidence"
    result: CriticResult = {"status": status, "accepted": accepted, "rejected": rejected}
    return {"critic_result": {group_id: result}}


def _check_time_consistency(hypothesis: Hypothesis) -> bool:
    """evidence의 maintenance_ts < defect_ts 확인 (firewall: 재조회 없음)
    """
    maintenance_ts = hypothesis["evidence"].get("maintenance_ts")
    if maintenance_ts is None:
        return True

    defect_ts = hypothesis["evidence"].get("defect_ts")  
    if defect_ts is None:                                 
        return True
    
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
