"""step 1 — state.py: GroupState + reducer 4종 테스트 (AC-1..4).

GroupState/merge_by_group는 아직 backend.state에 없다 — 그 import가 그 자체로 정당한 red다
(langgraph-skeleton-2026-07-23.md §10 step1).
"""

from __future__ import annotations

import typing


# covers: AC-1
def test_group_state_defines_expected_fields():
    from backend.state import GroupState  # 아직 없음(step1 신설 대상) — ImportError로 red

    hints = typing.get_type_hints(GroupState, include_extras=True)
    expected_fields = {
        "group_id", "pattern", "lot_ids", "cursor_date", "cursor_end",
        "observation", "description", "candidates", "hypotheses",
        "critic_result", "final_response",
    }
    assert expected_fields <= set(hints.keys())


# covers: AC-2
def test_rca_state_group_key_fields_are_annotated_with_reducer():
    from backend.state import RCAState

    hints = typing.get_type_hints(RCAState, include_extras=True)
    for field in ("graphrag_candidates", "hypotheses", "critic_result", "final_response"):
        hint = hints[field]
        assert hasattr(hint, "__metadata__"), (
            f"{field} 필드에 Annotated[..., reducer] 표기가 없다 — 아직 reducer 미부착(§4.3)"
        )
        reducer = hint.__metadata__[0]
        assert callable(reducer)
        # 키-병합 시맨틱까지 이 reducer가 실제로 구현하는지 함께 확인한다.
        assert reducer({"a": 1}, {"a": 2, "b": 3}) == {"a": 2, "b": 3}


# covers: AC-3
def test_merge_by_group_key_merge_semantics():
    from backend.state import merge_by_group

    old = {"g1": "old-value", "g2": "keep-me"}
    new = {"g1": "new-wins", "g3": "added"}
    merged = merge_by_group(old, new)
    assert merged == {"g1": "new-wins", "g2": "keep-me", "g3": "added"}


# covers: AC-3
def test_merge_by_group_handles_empty_dicts_safely():
    from backend.state import merge_by_group

    assert merge_by_group({}, {}) == {}
    assert merge_by_group({}, {"a": 1}) == {"a": 1}
    assert merge_by_group({"a": 1}, {}) == {"a": 1}


# covers: AC-4
def test_existing_fields_unchanged_after_group_state_added():
    from backend.state import GroupState  # noqa: F401 — step1 선행 조건(§10 step1)
    from backend.state import CNNResult, Group, RCAState

    hints = typing.get_type_hints(RCAState, include_extras=True)
    assert hints["target_lot_ids"] == list[str]
    assert hints["cnn_results"] == list[CNNResult]
    assert hints["groups"] == list[Group]
    # 4종 그룹-키 필드만 reducer 대상이고, 그 외 필드는 여전히 기본(덮어쓰기) 그대로다.
    assert not hasattr(hints["groups"], "__metadata__")
    assert not hasattr(hints["target_lot_ids"], "__metadata__")
    assert not hasattr(hints["cnn_results"], "__metadata__")
