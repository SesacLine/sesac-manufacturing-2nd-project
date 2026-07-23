"""step 5 — batch_runner.py 진행 방출 재설계 테스트 (AC-19..23).

process_stream_item / _CURRENT_GROUP / _tag_message는 이 스펙이 이름을 못박지 않아 테스트
작성자(나)가 가정한 심볼이다 — 구현자가 다른 이름을 쓰면 이 테스트들을 그 이름에 맞춰
고쳐야 한다(오케스트레이터 보고 참고).

가정한 계약: astream(subgraphs=True)이 뱉는 (namespace, update) 한 쌍을 순수 함수
`process_stream_item(namespace, update, current_step) -> (new_current_step, state_delta_or_None)`
로 처리한다.
    - 안쪽 신호(namespace 비어있지 않음): state_delta = None (진행 표시 전용, 부모 state를
      GroupState 부분상태로 덮어쓰지 않는다 — AC-20)
    - 바깥 신호(namespace 빔): state_delta = update (결과 누적용)
    - current_step은 두 경우 다 다음 규칙으로 갱신한다: 완료된 노드명을
      NODE_TO_STEP_INDEX(바깥 이름) 또는 서브그래프 내부 이름(④~⑦, 각 4·5·6·7)으로 직접
      조회해 max(현재, 조회값)을 취한다(단조 증가 — AC-21·23).
"""

from __future__ import annotations

import contextvars
import inspect

import pytest


# covers: AC-19
def test_run_batch_inner_uses_subgraphs_true_and_unpacks_namespace_update_pair():
    from backend import batch_runner

    src = inspect.getsource(batch_runner._run_batch_inner)
    assert "subgraphs=True" in src, "astream 호출에 subgraphs=True가 없다(§8.2a)"
    assert "namespace" in src, "namespace 언패킹이 안 보인다 — 여전히 update.items()만 순회 중일 수 있다"


# covers: AC-19, AC-20
def test_process_stream_item_outer_signal_returns_state_delta():
    from backend.batch_runner import process_stream_item

    new_step, delta = process_stream_item(
        namespace=(),
        update={"select_low_yield_lots": {"target_lot_ids": ["L1"]}},
        current_step=0,
    )
    assert delta == {"target_lot_ids": ["L1"]}, "바깥 신호(namespace 빔)는 결과 누적용 delta를 내야 한다"
    assert new_step >= 0


# covers: AC-20
def test_process_stream_item_inner_signal_returns_no_state_delta():
    from backend.batch_runner import process_stream_item

    new_step, delta = process_stream_item(
        namespace=("run_groups:abc123", "fetch_graphrag_candidates:xyz"),
        update={"fetch_graphrag_candidates": {"candidates": []}},
        current_step=2,
    )
    assert delta is None, (
        "안쪽 신호(namespace 비어있지 않음)는 GroupState 부분상태로 부모 state를 "
        "덮어쓰면 안 된다 — 진행 표시 전용이어야 한다"
    )


# covers: AC-21
def test_process_stream_item_current_step_is_monotonic_non_decreasing():
    from backend.batch_runner import process_stream_item

    step_after_first, _ = process_stream_item(
        namespace=("g1",), update={"generate_response": {}}, current_step=3,
    )
    assert step_after_first == 7

    step_after_second, _ = process_stream_item(
        namespace=("g2",), update={"fetch_graphrag_candidates": {}}, current_step=step_after_first,
    )
    assert step_after_second == 7, "그룹이 반복돼도 current_step이 뒤로 가면 안 된다(§8.1)"


# covers: AC-23
@pytest.mark.parametrize(
    "node_name,expected_index",
    [
        ("fetch_graphrag_candidates", 4),
        ("build_hypotheses", 5),
        ("review_hypotheses", 6),
        ("generate_response", 7),
    ],
)
def test_subgraph_inner_node_names_map_to_expected_step_index(node_name, expected_index):
    from backend.batch_runner import process_stream_item

    new_step, _ = process_stream_item(namespace=("g1",), update={node_name: {}}, current_step=0)
    assert new_step == expected_index


# covers: AC-22
def test_group_tag_contextvar_prefixes_log_message():
    from backend import batch_runner

    assert hasattr(batch_runner, "_CURRENT_GROUP"), "그룹 태그용 contextvars.ContextVar가 없다"
    assert isinstance(batch_runner._CURRENT_GROUP, contextvars.ContextVar)

    token = batch_runner._CURRENT_GROUP.set("Center")
    try:
        assert batch_runner._tag_message("run_commonality_analysis — 12건") == (
            "[Center] run_commonality_analysis — 12건"
        )
    finally:
        batch_runner._CURRENT_GROUP.reset(token)


# covers: AC-22
def test_group_tag_absent_leaves_message_unprefixed():
    from backend import batch_runner

    assert batch_runner._tag_message("아무 메시지") == "아무 메시지"
