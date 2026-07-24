"""⑤ Critic 노드. 결정적 함수(룰베이스), LLM 미사용 — 2026-07-09 노드화 결정.

규칙을 순서대로 확인한다(semiconductor_proposal.md §7.2 Critic Workflow 정본). Critic은 결정론 —
fab 재조회 없이 ④가 채운 evidence만 읽는다(faithfulness firewall). 처음 걸리는 규칙이 판정을 정하고,
끝까지 안 걸리면 채택:
    ① 시간 정합    — 원인 시각 < 결함 시각 아니면 reject("선후 뒤집힘") (함정 PM 필터링)
    ② 반대근거     — get_normal_lot_ratio를 안 돌렸으면(normal_ratio is None) reject
    ③ faithfulness — 자동 tier & 조사됨(investigated)인데 drift 판정이 비었으면 reject (미조사는 제외 — S2-6)
    ④ KG 메커니즘 연결 — 근거없음 tier면 judge_unknown 보류(P5)
    ⑤ 미조사      — investigated=False면 judge_unknown 보류 (S2-6 C3): 반자동 SEMI_AUTO_PENDING /
                    자동 폴백 NOT_INVESTIGATED. "안 봤다"는 기각이 아니라 판단 보류

채택 가능한 후보가 0개면 재시도 없이 즉시 insufficient_evidence를 반환한다(그룹 status).
재계획(replan) 루프는 없다(personalspace/0710 work/metadata.md §3.1).
"""

from __future__ import annotations

from ..mcp_client import MCPClient
from ..state import CriticResult, GroupState, Hypothesis

# 고정 사유 토큰(사유코드) — API가 verdict 3-state 승격을 이 토큰으로만 분기한다
# (API 명세 §2.7 "verdict 매핑 주의": 자연어 reject_reason 본문 매칭 금지).
# 내부 3버킷(adopt/reject/judge_unknown)을 프론트 verdict 3값에 매핑한다(hypo_critic_py.md §13-1 C1·C2):
#   P2/P3/P4 = reject → verdict="rejected"
#   P5(근거없음)·SEMI_AUTO_PENDING(반자동 미조사)·NOT_INVESTIGATED(자동 폴백) → verdict="judge_unknown"
# (그룹 status "insufficient"와는 다른 층 — verdict는 가설 1건, status는 그룹 전체.)
TOKEN_TIME_ORDER = "P2_TIME_ORDER"
TOKEN_NO_COUNTER_EVIDENCE = "P3_NO_COUNTER_EVIDENCE"
TOKEN_FAITHFULNESS = "P4_FAITHFULNESS"
TOKEN_NO_KG_MECHANISM = "P5_NO_KG_MECHANISM"
# 미조사 분기는 tier가 아니라 investigated 마커 기반이다(S2-6 C3). 반자동은 아직 조사
# 경로가 없어 항상 미조사 → SEMI_AUTO_PENDING. 반자동 조사가 붙으면 이 토큰만 걷어낸다.
TOKEN_SEMI_AUTO_PENDING = "SEMI_AUTO_PENDING"
# S2-6(C3): 미조사 일반 토큰 — 반자동이 아닌데 investigated=False인 행(자동 tier의
# suspect-None/에이전트 폭주 폴백). "안 봤다"는 기각이 아니라 판단 보류(judge_unknown).
TOKEN_NOT_INVESTIGATED = "NOT_INVESTIGATED"


async def review_hypotheses(state: GroupState, mcp: MCPClient) -> dict:
    """이 그룹의 hypotheses를 규칙대로 채택/기각하고 critic_result를 채운다.

    문서 순서(①시간정합 ②반대근거 ③faithfulness ④KG메커니즘) 그대로 적용한다.
    채택 후보가 0개면 status="insufficient_evidence", 아니면 "accepted".
    기각 항목에는 reject_reason(표시용 자연어)과 reject_token(고정 사유코드)을 같이 싣는다.
    """
    candidates = state["hypotheses"]

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
        elif not h.get("investigated", False):
            # S2-6(C3): ④가 실제로 조사 못 한 행(반자동 전부 + 자동 폴백)은 판단 보류.
            # 여기 도달 전에 ①시간정합은 이미 통과 검사됨 — 미조사여도 수집된 사실
            # (maintenance_ts)에 의한 반박은 유효하다(함정 사살 유지, §1-3).
            token = TOKEN_SEMI_AUTO_PENDING if h["tier"] == "반자동" else TOKEN_NOT_INVESTIGATED
            rejected.append({
                **h,
                "reject_token": token,
                "reject_reason": "fab 증거 미조사로 판단 보류(judge_unknown)",
            })
        else:
            accepted.append(h)

    status: str = "accepted" if accepted else "insufficient_evidence"
    result: CriticResult = {"status": status, "accepted": accepted, "rejected": rejected}
    return {"critic_result": result}


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

    0713 단순화: `[자동]` 후보를 실제로 조사했는데(investigated=True) 정상범위 부재로
    drift_detected를 못 정한 경우만 위반으로 본다. 미조사 행은 위반이 아니라 "판단
    보류" 대상이라 여기서 걸지 않는다(S2-6 C3 — 가짜 reject 오염 방지). 실제 문장
    단위 사실 대조는 스텝7(response.py, LLM)이 붙은 뒤 다시 설계해야 한다.
    """
    if hypothesis["tier"] == "자동" and hypothesis.get("investigated"):
        return hypothesis["evidence"].get("drift_detected") is not None
    return True


def _check_kg_mechanism(hypothesis: Hypothesis) -> bool:
    """VERIFIED_BY 경로(evidence_label != None)가 있는지 확인. 없으면 False(insufficient_evidence)."""
    return hypothesis["tier"] != "근거없음"
