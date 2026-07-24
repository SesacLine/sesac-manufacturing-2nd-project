"""step 4 — 응답생성 분리(⑦ generate_response / ⑦' respond_without_llm) 테스트 (AC-14..18).

respond_without_llm은 아직 backend.nodes.response에 없다 — 그 import가 정당한 red다.
golden 값은 현재 backend/nodes/response.py(:42 unmapped 분기, :69 insufficient 분기,
:57~66 정렬·h{n}·verdict 규칙)를 그대로 옮겨 적은 것이다 — §10 step4 완료기준의 "동일
payload"를 not-data 레벨 순수함수 비교로 대체 검증한다(스펙 §"검증 방법" 1차 게이트).
"""

from __future__ import annotations

import inspect

from backend.nodes.critic import TOKEN_SEMI_AUTO_PENDING, TOKEN_TIME_ORDER

GROUP_ID = "grp-Center-2026-07-23"
PATTERN = "Center"
LOT_IDS = ["LOT1", "LOT2"]


def _state_with_no_candidates() -> dict:
    # #33 평탄화: 배치 RCAState가 아니라 그룹 1건짜리 GroupState를 받는다.
    return {
        "group_id": GROUP_ID,
        "pattern": PATTERN,
        "lot_ids": LOT_IDS,
        "candidates": [],           # 후보 0건 → unmapped
        "critic_result": None,
    }


_REJECTED = [
    {
        "cause": "cause-A",
        "tier": "자동",
        "stage": "CMP",
        "equipment": "EQ-1",
        "evidence": {},
        "sentence": "s1",
        "reject_token": TOKEN_TIME_ORDER,
        "reject_reason": "시간 정합 실패 — 원인이 결함 발생보다 늦음",
    },
    {
        "cause": "cause-B",
        "tier": "반자동",
        "stage": None,
        "equipment": None,
        "evidence": {},
        "sentence": "s2",
        "reject_token": TOKEN_SEMI_AUTO_PENDING,
        "reject_reason": "반자동 등급 — fab 증거 미조사로 판단 보류(judge_unknown)",
    },
]


def _state_with_candidates_but_zero_accepted() -> dict:
    return {
        "group_id": GROUP_ID,
        "pattern": PATTERN,
        "lot_ids": LOT_IDS,
        "candidates": [{"cause": "cause-A"}, {"cause": "cause-B"}],
        "critic_result": {"status": "insufficient_evidence", "accepted": [], "rejected": _REJECTED},
    }


EXPECTED_UNMAPPED = {
    "final_response": {
        "group_id": GROUP_ID,
        "pattern": PATTERN,
        "status": "unmapped",
        "reason": "이 결함 패턴은 원인 매핑 데이터가 없어 판독까지만 지원됩니다.",
        "lot_ids": LOT_IDS,
        "lot_count": len(LOT_IDS),
        "hypotheses": [],
        "summary": f"{PATTERN} 패턴은 원인 분석 데이터가 없습니다(KG 매핑 대상 3종 밖).",
        # 테스트 state에 observation이 없어 영어 서술 소스가 없음 → 한국어 description도 None
        "description": None,
        "confidence": "low",  # R1: 채택 원인 없음(unmapped) → 불확실
    }
}

EXPECTED_INSUFFICIENT_HYPOTHESES = [
    {**_REJECTED[0], "verdict": "rejected", "verdict_reason": _REJECTED[0]["reject_reason"], "hypothesis_id": "h0"},
    {**_REJECTED[1], "verdict": "judge_unknown", "verdict_reason": _REJECTED[1]["reject_reason"], "hypothesis_id": "h1"},
]

EXPECTED_INSUFFICIENT = {
    "final_response": {
        "group_id": GROUP_ID,
        "pattern": PATTERN,
        "status": "insufficient",
        "reason": (
            "매핑된 원인 후보는 있으나 시간 정합·정상 로트 대조에서 "
            "채택 가능한 후보가 없어 판단 불가(근거부족)."
        ),
        "lot_ids": LOT_IDS,
        "lot_count": len(LOT_IDS),
        "hypotheses": EXPECTED_INSUFFICIENT_HYPOTHESES,
        "summary": f"{PATTERN} 패턴은 판단 불가 — 채택 가능한 근거 있는 가설이 없습니다.",
        # 테스트 state에 observation이 없어 영어 서술 소스가 없음 → 한국어 description도 None
        "description": None,
        "confidence": "low",  # R1: 채택 0건(insufficient) → 불확실
    }
}


# --- reviewed(⑦ generate_response) 골든/픽스처: 채택 ≥1 경로 (기존엔 unmapped/insufficient만 있었다) ---
_ACCEPTED = [
    {"cause": "cause-X", "tier": "자동", "stage": "CMP", "equipment": "EQ-9",
     "evidence": {}, "sentence": "sx"},
    {"cause": "cause-Y", "tier": "반자동", "stage": "ETCH", "equipment": "EQ-3",
     "evidence": {}, "sentence": "sy"},
]


def _state_reviewed() -> dict:
    # 채택 ≥1 → generate_response(reviewed). candidates는 존재 표시용(내용 무관).
    return {
        "group_id": GROUP_ID,
        "pattern": PATTERN,
        "lot_ids": LOT_IDS,
        "candidates": [{"cause": "cause-X"}, {"cause": "cause-Y"}],
        "critic_result": {"status": "accepted", "accepted": list(_ACCEPTED), "rejected": []},
    }


EXPECTED_REVIEWED_HYPOTHESES = [
    {**_ACCEPTED[0], "verdict": "accepted", "verdict_reason": None, "hypothesis_id": "h0"},
    {**_ACCEPTED[1], "verdict": "accepted", "verdict_reason": None, "hypothesis_id": "h1"},
]

EXPECTED_REVIEWED = {
    "final_response": {
        "group_id": GROUP_ID,
        "pattern": PATTERN,
        "status": "reviewed",
        "reason": None,                       # reviewed는 reason 없음(§2.5 필드 존재 계약)
        "lot_ids": LOT_IDS,
        "lot_count": len(LOT_IDS),
        "hypotheses": EXPECTED_REVIEWED_HYPOTHESES,
        "summary": (
            # R1: 비단정형 — 두 채택 모두 evidence={} → 적극 지지 없음 → 확신 "불확실"
            f"{PATTERN} 패턴 — 가능성 있는 원인 후보 2건 (확정 아님 · 확신: 불확실):\n"
            "- cause-X (등급: 자동, 의심 장비: EQ-9)\n"
            "- cause-Y (등급: 반자동, 의심 장비: EQ-3)"
        ),
        "description": None,                  # observation 없음 → None
        "confidence": "low",                  # R1: evidence 없음 → 불확실
    }
}


# covers: AC-14, AC-17
def test_respond_without_llm_unmapped_matches_golden_from_current_response_py():
    from backend.nodes.response import respond_without_llm

    result = respond_without_llm(_state_with_no_candidates())
    assert result == EXPECTED_UNMAPPED


# covers: AC-14, AC-16, AC-17
def test_respond_without_llm_insufficient_matches_golden_from_current_response_py():
    from backend.nodes.response import respond_without_llm

    result = respond_without_llm(_state_with_candidates_but_zero_accepted())
    assert result == EXPECTED_INSUFFICIENT


# covers: AC-18
def test_respond_without_llm_insufficient_hypotheses_start_at_h0_for_evidence_modal():
    from backend.nodes.response import respond_without_llm

    result = respond_without_llm(_state_with_candidates_but_zero_accepted())
    hyps = result["final_response"]["hypotheses"]
    assert len(hyps) >= 1
    assert hyps[0]["hypothesis_id"] == "h0", "근거 모달 드릴다운이 h0부터 열려야 한다(§2.7)"


# description(§2.5): VLM이 **실제로 생성한 경우에만**(vlm_track 존재) total_description을 운반한다.
def test_description_carried_only_when_vlm_really_generated():
    from backend.nodes.response import respond_without_llm

    state = _state_with_candidates_but_zero_accepted()
    # VLM 실생성 = 관측 메타 vlm_track이 붙음 → total_description 그대로 운반
    state["observation"] = {
        "total_description": "A high-density blob at the wafer center.",
        "vlm_track": "open",
    }
    desc = respond_without_llm(state)["final_response"]["description"]
    assert desc == "A high-density blob at the wafer center."


def test_description_null_for_skeleton_fallback_even_with_text():
    # 스켈레톤/폴백은 total_description이 있어도 vlm_track이 없음 → 지어낸 문구 노출 금지(None)
    from backend.nodes.response import respond_without_llm

    state = _state_with_candidates_but_zero_accepted()
    state["observation"] = {"total_description": "웨이퍼 중심부에 …(스켈레톤 폴백)"}  # vlm_track 없음
    desc = respond_without_llm(state)["final_response"]["description"]
    assert desc is None, "스켈레톤 폴백 문구는 노출 금지 → None"


def test_description_none_when_no_observation():
    # observation 자체가 없으면(Unknown 등) None → 프론트 summary_line fallback
    from backend.nodes.response import respond_without_llm

    result = respond_without_llm(_state_with_no_candidates())
    assert result["final_response"]["description"] is None


def test_description_translated_when_translator_injected():
    # translate 주입(RESPONSE_LLM 경로) → VLM 영어 서술을 한국어로 변환해 싣는다
    from backend.nodes.response import respond_without_llm

    state = _state_with_candidates_but_zero_accepted()
    state["observation"] = {"total_description": "A blob at the center.", "vlm_track": "pty"}
    result = respond_without_llm(state, translate=lambda en: f"[KO]{en}")
    assert result["final_response"]["description"] == "[KO]A blob at the center."


def test_description_falls_back_to_english_when_translation_raises():
    # 번역 콜 실패 시 원문(영어) 보존 — 곱게 무너짐(내용 유지)
    from backend.nodes.response import respond_without_llm

    def boom(_en):
        raise RuntimeError("LLM down")

    state = _state_with_candidates_but_zero_accepted()
    state["observation"] = {"total_description": "A blob at the center.", "vlm_track": "pty"}
    result = respond_without_llm(state, translate=boom)
    assert result["final_response"]["description"] == "A blob at the center."


# covers: AC-15
def test_generate_response_no_longer_handles_unmapped_or_insufficient_branches():
    from backend.nodes.response import generate_response

    src = inspect.getsource(generate_response)
    assert "unmapped" not in src, "unmapped 분기(구 :42)가 generate_response에서 제거돼야 한다"
    assert "insufficient" not in src, "insufficient 분기(구 :69)가 generate_response에서 제거돼야 한다"


# covers: AC-16
def test_generate_response_and_respond_without_llm_share_ordering_helper():
    from backend.nodes import response as response_module

    helper_name = "_ordered_hypotheses"
    assert hasattr(response_module, helper_name), (
        "generate_response와 respond_without_llm이 정렬·h{n}·verdict 규칙을 공유할 헬퍼"
        f"({helper_name})가 response.py에 없다 — 이 이름은 스펙에 못박히지 않아 테스트 작성자가 "
        "가정한 것이므로 구현 시 이름이 다르면 이 테스트를 그 이름에 맞춰 고친다"
    )
    gen_src = inspect.getsource(response_module.generate_response)
    rwl_src = inspect.getsource(response_module.respond_without_llm)
    assert helper_name in gen_src
    assert helper_name in rwl_src


# ── 갭1: ⑦ reviewed 전체 골든 (기존엔 reviewed payload 완전일치 검증이 없었다) ──────────
def test_generate_response_reviewed_matches_golden():
    from backend.nodes.response import generate_response

    assert generate_response(_state_reviewed()) == EXPECTED_REVIEWED


# ── 갭2: 정렬 불변식 — accepted+rejected+judge_unknown 혼합에서 채택이 앞·대표=h0 ──────────
def test_ordered_hypotheses_accepted_first_then_rejected_with_hids_and_verdicts():
    from backend.nodes.response import _ordered_hypotheses

    accepted = [
        {"cause": "A0", "tier": "자동", "equipment": "E0"},
        {"cause": "A1", "tier": "자동", "equipment": "E1"},
    ]
    rejected = [
        {"cause": "R_time", "reject_token": TOKEN_TIME_ORDER, "reject_reason": "시간역전"},
        {"cause": "R_semi", "reject_token": TOKEN_SEMI_AUTO_PENDING, "reject_reason": "보류"},
    ]
    ordered = _ordered_hypotheses({"accepted": accepted, "rejected": rejected})

    # 채택이 전부 앞, 비채택이 전부 뒤 (대표=index 0 = 첫 accepted)
    assert [h["cause"] for h in ordered] == ["A0", "A1", "R_time", "R_semi"]
    assert [h["hypothesis_id"] for h in ordered] == ["h0", "h1", "h2", "h3"]
    assert [h["verdict"] for h in ordered] == ["accepted", "accepted", "rejected", "judge_unknown"]
    # accepted는 verdict_reason 없음, 비채택은 reject_reason을 싣는다
    assert ordered[0]["verdict_reason"] is None and ordered[1]["verdict_reason"] is None
    assert ordered[2]["verdict_reason"] == "시간역전"
    assert ordered[3]["verdict_reason"] == "보류"


# ── 갭3: critic_result None 방어경로 → 빈 배열 ──────────────────────────────────────────
def test_ordered_hypotheses_none_critic_returns_empty():
    from backend.nodes.response import _ordered_hypotheses

    assert _ordered_hypotheses(None) == []


# ── 갭4: reviewed 경로에서도 translate가 description에 적용된다 (기존엔 ⑦'만 검증) ──────────
def test_generate_response_reviewed_translates_description():
    from backend.nodes.response import generate_response

    state = _state_reviewed()
    state["observation"] = {"total_description": "A blob at the center.", "vlm_track": "pty"}
    out = generate_response(state, translate=lambda en: f"[KO]{en}")
    assert out["final_response"]["description"] == "[KO]A blob at the center."


# ── 갭6: vlm_track은 있으나 total_description이 없으면 None (엣지) ──────────────────────────
def test_description_none_when_vlm_track_but_no_text():
    from backend.nodes.response import respond_without_llm

    state = _state_with_candidates_but_zero_accepted()
    state["observation"] = {"vlm_track": "pty"}  # total_description 키 없음
    assert respond_without_llm(state)["final_response"]["description"] is None


# ── R1: 확신 수준(불확실 표시, eval_scenario_kg_proposal.md R1) ────────────────────────────
def test_confidence_medium_when_few_accepted_with_strong_support():
    # 소수 채택(≤3) + 방향일치 drift 있는 가설 → "medium"(잠정 지지). 확정("high")은 없음.
    from backend.nodes.response import generate_response

    accepted = [
        {"cause": "cX", "tier": "자동", "equipment": "EQ-9",
         "evidence": {"drift_detected": True, "direction_match": True}, "sentence": "s"},
    ]
    state = {
        "group_id": GROUP_ID, "pattern": PATTERN, "lot_ids": LOT_IDS,
        "candidates": [{"cause": "cX"}],
        "critic_result": {"status": "accepted", "accepted": accepted, "rejected": []},
    }
    fr = generate_response(state)["final_response"]
    assert fr["confidence"] == "medium"
    assert "확정 아님" in fr["summary"] and "잠정 지지" in fr["summary"]


def test_confidence_low_when_many_accepted_even_with_support():
    # 채택 다수(>3)면 지지 증거가 있어도 "좁히지 못함" → "low"(불확실).
    from backend.nodes.response import generate_response

    accepted = [
        {"cause": f"c{i}", "tier": "자동", "equipment": "EQ",
         "evidence": {"drift_detected": True, "direction_match": True}, "sentence": "s"}
        for i in range(4)
    ]
    state = {
        "group_id": GROUP_ID, "pattern": PATTERN, "lot_ids": LOT_IDS,
        "candidates": [{"cause": "c0"}],
        "critic_result": {"status": "accepted", "accepted": accepted, "rejected": []},
    }
    fr = generate_response(state)["final_response"]
    assert fr["confidence"] == "low"
    assert "불확실" in fr["summary"]


def test_confidence_never_high():
    # R1 불변식: confidence는 절대 "high"(확정)가 아니다 — RCA 스코프는 가설까지.
    from backend.nodes.response import _confidence

    strong = [{"evidence": {"normal_ratio": 0.1}}]
    assert _confidence(strong) in ("medium", "low")
    assert _confidence([]) == "low"
