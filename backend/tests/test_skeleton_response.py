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
