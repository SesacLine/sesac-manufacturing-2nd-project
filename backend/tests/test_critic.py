import asyncio

from backend.nodes.critic import (
    review_hypotheses,
    TOKEN_TIME_ORDER, TOKEN_NO_COUNTER_EVIDENCE, TOKEN_FAITHFULNESS,
    TOKEN_NO_KG_MECHANISM, TOKEN_SEMI_AUTO_PENDING, TOKEN_NOT_INVESTIGATED,
)

GID = "g1"


def _run(hyps):
    """review_hypotheses를 최소 GroupState로 돌려 critic_result를 반환(#33 평탄화)."""
    state = {
        "group_id": GID, "pattern": "Center", "lot_ids": ["L1"],
        "hypotheses": hyps,
    }
    out = asyncio.run(review_hypotheses(state, mcp=None))   # firewall — mcp 미사용
    return out["critic_result"]


def _hyp(**ev):
    """evidence 기본값(정상 통과 세트) 위에 덮어써 한 행을 만든다."""
    base = {
        "cause": "c", "tier": "자동", "stage": "CMP", "equipment": "CMP-01",
        "citations": [], "sentence": "...", "investigated": True,
        "evidence": {
            "maintenance_ts": None, "defect_ts": None,
            "normal_ratio": 0.1, "drift_detected": True,
        },
    }
    base["evidence"].update(ev.pop("evidence", {}))
    base.update(ev)
    return base


def _tokens(result):
    return {r["cause"]: r["reject_token"] for r in result["rejected"]}


# --- 행 유형별 판정 (terms §7-2 표를 그대로 고정) ---

def test_auto_investigated_with_drift_accepted():
    result = _run([_hyp(cause="ok")])
    assert [h["cause"] for h in result["accepted"]] == ["ok"]
    assert result["status"] == "accepted"


def test_auto_investigated_but_drift_none_is_faithfulness_reject():
    # 조사까지 해놓고(investigated=True) 판정이 빈 자동 행 → 진짜 P4
    result = _run([_hyp(cause="empty", evidence={"drift_detected": None})])
    assert _tokens(result)["empty"] == TOKEN_FAITHFULNESS


def test_auto_not_investigated_is_judge_unknown_not_faithfulness():
    # S2-6 핵심: 미조사 자동 행은 P4 가짜 기각이 아니라 NOT_INVESTIGATED(보류)
    result = _run([_hyp(cause="fallback", investigated=False,
                        evidence={"drift_detected": None})])
    assert _tokens(result)["fallback"] == TOKEN_NOT_INVESTIGATED


def test_semi_auto_pending_keeps_its_token():
    # 반자동은 항상 미조사지만 토큰은 기존 SEMI_AUTO_PENDING 유지 (API 계약)
    result = _run([_hyp(cause="semi", tier="반자동", investigated=False,
                        evidence={"drift_detected": None})])
    assert _tokens(result)["semi"] == TOKEN_SEMI_AUTO_PENDING


def test_time_order_trap_still_rejects_before_investigated():
    # 함정: 반자동(미조사)이라도 시간역전은 ①에서 먼저 사살 — 미조사 분기보다 우선
    result = _run([_hyp(cause="trap", tier="반자동", investigated=False,
                        evidence={"maintenance_ts": "2026-03-10 00:00:00",
                                "defect_ts": "2026-03-05 00:00:00",
                                "drift_detected": None})])
    assert _tokens(result)["trap"] == TOKEN_TIME_ORDER


def test_no_counter_evidence_rejects():
    result = _run([_hyp(cause="noneg", evidence={"normal_ratio": None})])
    assert _tokens(result)["noneg"] == TOKEN_NO_COUNTER_EVIDENCE


def test_no_kg_mechanism_is_judge_unknown():
    result = _run([_hyp(cause="nokg", tier="근거없음", investigated=False,
                        evidence={"drift_detected": None})])
    assert _tokens(result)["nokg"] == TOKEN_NO_KG_MECHANISM


def test_status_insufficient_when_none_accepted():
    result = _run([_hyp(cause="x", investigated=False, evidence={"drift_detected": None})])
    assert result["accepted"] == []
    assert result["status"] == "insufficient_evidence"


# --- 0724 규칙 순서 재배치: judge_unknown 조건(②KG메커니즘 ③미조사)이 채택 게이트(⑤반대근거)보다 앞.
#     suspect 미탐으로 normal_ratio=None인 근거없음/미조사 행이 P3로 오기각되지 않아야 한다. ---

def test_no_kg_mechanism_wins_over_null_normal_ratio():
    # 버그 재현: 근거없음인데 suspect 미탐(normal_ratio=None) → 옛 순서면 P3 오기각.
    #           새 순서는 ②KG메커니즘이 먼저라 judge_unknown(P5) 유지.
    result = _run([_hyp(cause="nokg_nonull", tier="근거없음", investigated=False,
                        evidence={"normal_ratio": None, "drift_detected": None})])
    assert _tokens(result)["nokg_nonull"] == TOKEN_NO_KG_MECHANISM


def test_not_investigated_wins_over_null_normal_ratio():
    # 버그 재현: 자동 폴백(미조사)인데 suspect 미탐(normal_ratio=None) → 옛 순서면 P3 오기각.
    #           새 순서는 ③미조사가 먼저라 NOT_INVESTIGATED(judge_unknown) 유지.
    result = _run([_hyp(cause="fallback_nonull", investigated=False,
                        evidence={"normal_ratio": None, "drift_detected": None})])
    assert _tokens(result)["fallback_nonull"] == TOKEN_NOT_INVESTIGATED


def test_semi_auto_pending_wins_over_null_normal_ratio():
    result = _run([_hyp(cause="semi_nonull", tier="반자동", investigated=False,
                        evidence={"normal_ratio": None, "drift_detected": None})])
    assert _tokens(result)["semi_nonull"] == TOKEN_SEMI_AUTO_PENDING


def test_investigated_auto_with_null_normal_ratio_still_p3():
    # 채택 게이트 불변 회귀: 조사됐고(investigated=True, drift 있음) KG 메커니즘 있는 자동 행이
    # normal_ratio만 None이면 여전히 ⑤반대근거(P3)로 기각 — 재배치가 채택 게이트를 안 흔든다.
    result = _run([_hyp(cause="inv_nonull", evidence={"normal_ratio": None})])
    assert _tokens(result)["inv_nonull"] == TOKEN_NO_COUNTER_EVIDENCE


def test_trap_still_p2_even_with_null_normal_ratio():
    # 함정 회귀: 시간역전(①)은 normal_ratio·미조사와 무관하게 여전히 최우선 사살.
    result = _run([_hyp(cause="trap_nonull", tier="반자동", investigated=False,
                        evidence={"maintenance_ts": "2026-03-10 00:00:00",
                                  "defect_ts": "2026-03-05 00:00:00",
                                  "normal_ratio": None, "drift_detected": None})])
    assert _tokens(result)["trap_nonull"] == TOKEN_TIME_ORDER