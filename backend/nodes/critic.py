"""⑥ Critic 노드. 결정적 함수(룰베이스), LLM 미사용 — 2026-07-09 노드화 결정.

번호 주의: 현행 파이프라인(⓪~⑦) 기준 이 노드는 ⑥이다. 07-23에 ③ VLM 관측 노드가
중간에 들어오며 한 칸 밀렸다 — 옛 주석·문서의 "⑤ Critic"은 같은 노드를 가리킨다.
정본: docs/node_langraph_spec/node_spec_06_critic.md

규칙을 순서대로 확인한다(semiconductor_proposal.md §7.2 Critic Workflow 정본). Critic은 결정론 —
fab 재조회 없이 ④가 채운 evidence만 읽는다(faithfulness firewall). 처음 걸리는 규칙이 판정을 정하고,
끝까지 안 걸리면 채택:
    ① 시간 정합    — 원인 시각 < 결함 시각 아니면 reject("선후 뒤집힘") (P2, 함정 PM 필터 — 미조사여도 먼저 사살)
    ② KG 메커니즘   — 근거없음 tier면 judge_unknown 보류 (P5)
    ③ 미조사       — investigated=False면 judge_unknown 보류 (S2-6 C3): 반자동 SEMI_AUTO_PENDING /
                    자동 폴백 NOT_INVESTIGATED. "안 봤다"는 기각이 아니라 판단 보류
    ④ faithfulness — 자동 tier & 조사됨(investigated)인데 drift 판정이 비었으면 reject (P4)
    ⑤ 반대근거     — get_normal_lot_ratio를 안 돌렸으면(normal_ratio is None) reject (P3)
    ⑥ 인과 서명    — 공통률 1.0 AND KG 예상 방향과 drift 일치가 아니면 reject (P6, S3-0726)

규칙 순서 근거(0724 수정 · 0726 ⑥ 추가): judge_unknown 조건(②③)을 채택 게이트(④⑤⑥)보다 먼저 확인한다. ⑤ pre-pass가
suspect 장비를 못 찾으면 normal_ratio가 None으로 남는데, 이때 근거없음·미조사 후보가 ⑤ 반대근거 규칙에서
hard reject되면 "안 봤다≠기각" 원칙(S2-6)이 깨진다. 시간정합(①)은 1번 유지 — 미조사여도 수집된
maintenance_ts로 함정을 먼저 사살해야 하므로(§5-2). 채택(investigated=True) 후보의 결과는 불변 —
그들은 여전히 ④⑤를 통과해야 채택된다.

채택 가능한 후보가 0개면 재시도 없이 즉시 insufficient_evidence를 반환한다(그룹 status).
재계획(replan) 루프는 없다(personalspace/0710 work/metadata.md §3.1).
"""

from __future__ import annotations

from ..mcp_client import MCPClient
from ..state import CriticResult, GroupState, Hypothesis

# 고정 사유 토큰(사유코드) — API가 verdict 3-state 승격을 이 토큰으로만 분기한다
# (API 명세 §2.7 "verdict 매핑 주의": 자연어 reject_reason 본문 매칭 금지).
# 내부 3버킷(adopt/reject/judge_unknown)을 프론트 verdict 3값에 매핑한다(hypo_critic_py.md §13-1 C1·C2):
#   P2/P3/P4/P6 = reject → verdict="rejected"
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
# S3(0726): 인과 서명 게이트 — 채택 직전 마지막 관문. 상관(모든 로트가 지나감)과 인과
# (그 파라미터가 KG 예상 방향으로 실제 이탈)를 가른다. 11개 시나리오 실측으로 도출:
# 단독 신호는 둘 다 기각됐고(공통률 단독 → UNMATCHED-02 우연 1.0에 뚫림 / 특이성 단독 →
# CENTER-03 정답이 -0.43으로 같이 죽음) 결합만이 정답 9/9 보존 + 환각 2/2 차단을 냈다.
TOKEN_NO_CAUSAL_SIGNATURE = "P6_NO_CAUSAL_SIGNATURE"
# 공통률 임계 — 부동소수 비교라 등호 대신 근사. "불량 로트 전부가 그 장비를 거쳤다"가
# 원인의 필요조건(원인 장비는 시나리오 구성상 반드시 1.0).
_COMMONALITY_MIN = 0.999


async def review_hypotheses(state: GroupState, mcp: MCPClient) -> dict:
    """이 그룹의 hypotheses를 규칙대로 채택/기각하고 critic_result를 채운다.

    순서(①시간정합 ②KG메커니즘 ③미조사 ④faithfulness ⑤반대근거) 그대로 적용한다 — judge_unknown
    조건(②③)이 채택 게이트(④⑤)보다 앞(0724, 위 docstring 근거).
    채택 후보가 0개면 status="insufficient_evidence", 아니면 "accepted".
    기각 항목에는 reject_reason(표시용 자연어)과 reject_token(고정 사유코드)을 같이 싣는다.
    """
    candidates = state["hypotheses"]

    accepted: list[Hypothesis] = []
    rejected: list[dict] = []
    for h in candidates:
        if not _check_time_consistency(h):
            # ① 시간정합(P2) — 미조사여도 수집된 maintenance_ts로 함정을 먼저 사살한다(§5-2).
            rejected.append({
                **h,
                "reject_token": TOKEN_TIME_ORDER,
                "reject_reason": "Time-order violation — cause occurs later than the defect",
            })
        elif not _check_kg_mechanism(h):
            # ② KG 메커니즘(P5) — 근거없음 tier는 judge_unknown 보류.
            rejected.append({
                **h,
                "reject_token": TOKEN_NO_KG_MECHANISM,
                "reject_reason": "No KG mechanism link (VERIFIED_BY)",
            })
        elif not h.get("investigated", False):
            # ③ 미조사(S2-6 C3) — 실제 조사 못 한 행(반자동 전부 + 자동 폴백)은 판단 보류.
            # 채택 게이트(④⑤)보다 앞이라, suspect 미탐으로 normal_ratio=None인 미조사 행이
            # ⑤ 반대근거로 오기각되지 않는다(0724). 시간정합(①)은 이미 통과 검사됨.
            token = TOKEN_SEMI_AUTO_PENDING if h["tier"] == "반자동" else TOKEN_NOT_INVESTIGATED
            rejected.append({
                **h,
                "reject_token": token,
                "reject_reason": "Fab evidence not investigated — judgment deferred (judge_unknown)",
            })
        elif not _check_faithfulness(h):
            # ④ faithfulness(P4) — 여기 도달 = investigated=True 확정. 자동 tier인데 drift 판정이 비면 reject.
            rejected.append({
                **h,
                "reject_token": TOKEN_FAITHFULNESS,
                "reject_reason": "Faithfulness violation — cited an unverified value as evidence",
            })
        elif not _check_negative_evidence(h):
            # ⑤ 반대근거(P3) — 채택 직전 게이트. 조사된 후보인데 normal_ratio 미수집이면 reject.
            rejected.append({
                **h,
                "reject_token": TOKEN_NO_COUNTER_EVIDENCE,
                "reject_reason": "Counter-evidence (normal_ratio) not collected",
            })
        elif not _check_causal_signature(h):
            # ⑥ 인과 서명(P6, S3-0726) — 채택 직전 마지막 게이트.
            # "모든 불량 로트가 이 장비를 거쳤다"(상관)만으로는 부족하고, "그 파라미터가
            # KG가 예측한 방향으로 실제 이탈했다"(기전)까지 있어야 채택한다.
            # 이 규칙이 ③(미조사)보다 뒤에 있어야 한다 — 앞에 두면 미조사 행이
            # judge_unknown이 아니라 P6 reject로 빠져 "안 봤다≠기각" 원칙(S2-6)이 깨진다.
            rejected.append({
                **h,
                "reject_token": TOKEN_NO_CAUSAL_SIGNATURE,
                "reject_reason": "No causal signature — correlation without a KG-predicted drift",
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


def _check_causal_signature(hypothesis: Hypothesis) -> bool:
    """상관이 아니라 인과인가 — 공통률 1.0 AND KG 예상 방향과 drift 방향 일치.

    두 조건이 서로의 구멍을 메운다(11개 시나리오 실측):
      - 공통률만 보면: LITHO-01처럼 모든 로트가 지나가는 무관 장비가 1.0으로 통과한다
        (CENTER-01/02/03에서 각 14건 채택). 그 장비의 파라미터는 미동도 안 했다.
      - 방향만 보면: 원인이 아닌 장비도 우연히 방향 맞는 이탈이 있을 수 있다
        (CENTER-01 CMP 지속 100%·특이성 0.72 — 공통률 0.62로 걸러짐).

    firewall 준수: evidence만 읽고 fab 재조회는 하지 않는다(⑤가 채운 값).

    ⚠ 반자동 tier에 조사 경로가 붙으면 이 규칙을 tier 조건부로 바꿔야 한다 — 정비/레시피
    근거는 telemetry 방향이 없어 direction_match가 구조적으로 성립하지 않는다. 지금은
    반자동이 ③에서 judge_unknown으로 먼저 빠지므로 여기 도달하지 않는다.
    """
    evidence = hypothesis["evidence"]
    ratio = evidence.get("commonality_ratio")
    if ratio is None or ratio < _COMMONALITY_MIN:
        return False
    return evidence.get("direction_match") is True