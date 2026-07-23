"""step 4 — 라우팅 함수 2종 + Normal 가드 + 공통 제약 테스트 (AC-11..13, AC-24..26).

route_on_candidates/route_on_verdicts/run_groups는 아직 backend.graph에 없다 — 이 심볼들이
없어서 나는 ImportError가 이 파일 테스트 대부분의 정당한 red다.

run_groups(state, group_graph)의 두 번째 인자 이름/타입은 스펙이 못박지 않았다 — 이 테스트는
"ainvoke(group_state) -> dict" 최소 인터페이스를 갖는 컴파일된 서브그래프 객체를 받는다고
가정한다(구현 시 이름이 다르면 이 테스트를 그 계약에 맞춰 고친다 — 오케스트레이터 보고 참고).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import typing


# covers: AC-11
def test_route_on_candidates_empty_goes_to_fallback():
    from backend.graph import route_on_candidates

    assert route_on_candidates({"candidates": []}) == "respond_without_llm"


# covers: AC-11
def test_route_on_candidates_ignores_pattern_and_goes_to_hypotheses_when_nonempty():
    from backend.graph import route_on_candidates

    for pattern in ("Center", "Unknown", "Edge-Ring"):
        state = {"pattern": pattern, "candidates": [{"cause": "x"}]}
        assert route_on_candidates(state) == "build_hypotheses"


# covers: AC-12
def test_route_on_verdicts_missing_or_empty_accepted_goes_to_fallback():
    from backend.graph import route_on_verdicts

    assert route_on_verdicts({"critic_result": None}) == "respond_without_llm"
    assert route_on_verdicts(
        {"critic_result": {"status": "insufficient_evidence", "accepted": [], "rejected": []}}
    ) == "respond_without_llm"


# covers: AC-12
def test_route_on_verdicts_has_accepted_goes_to_generate_response():
    from backend.graph import route_on_verdicts

    state = {"critic_result": {"status": "accepted", "accepted": [{"cause": "x"}], "rejected": []}}
    assert route_on_verdicts(state) == "generate_response"


class _FakeGroupGraph:
    """run_groups가 그룹마다 호출할 컴파일된 서브그래프의 최소 가짜 구현."""

    def __init__(self):
        self.invoked_patterns: list[str] = []

    async def ainvoke(self, group_state):
        self.invoked_patterns.append(group_state["pattern"])
        return {"final_response": {group_state["group_id"]: {"status": "unmapped"}}}


# covers: AC-13
def test_run_groups_skips_normal_pattern_and_logs(caplog):
    from backend.graph import run_groups

    state = {
        "groups": [
            {"group_id": "g-normal", "pattern": "Normal", "lot_ids": ["L1"], "status": "ok"},
            {"group_id": "g-center", "pattern": "Center", "lot_ids": ["L2"], "status": "ok"},
        ],
        "cursor_date": "2026-01-01",
        "cursor_end": "2026-01-02",
    }
    fake_graph = _FakeGroupGraph()

    with caplog.at_level(logging.INFO):
        result = asyncio.run(run_groups(state, fake_graph))

    assert fake_graph.invoked_patterns == ["Center"], "Normal 그룹은 서브그래프에 태워지면 안 된다"
    assert "g-normal" not in result.get("final_response", {})
    assert any("Normal" in rec.message for rec in caplog.records), "Normal 그룹 유입 로그가 1줄 남아야 한다"


# covers: AC-24
def test_run_groups_does_not_open_a_new_mcp_session():
    from backend.graph import run_groups

    src = inspect.getsource(run_groups)
    assert "MultiServerMCPClient" not in src
    assert "get_tools(" not in src


# covers: AC-25
def test_run_groups_is_sequential_for_loop_not_send_fanout():
    from backend.graph import run_groups

    src = inspect.getsource(run_groups)
    assert "Send(" not in src, "그룹 팬아웃은 아직 순차다 — Send 병렬화는 범위 밖(§7.1)"
    assert "for " in src, "run_groups는 for 루프로 그룹을 순회해야 한다"


# covers: AC-26
def test_api_contract_invariants_hold_with_new_routing_in_place():
    from backend.graph import route_on_candidates, route_on_verdicts  # noqa: F401 — step4 선행 조건

    from backend.schemas import NODE_TO_STEP_INDEX, STEPS
    from backend.state import FinalResponse

    assert len(STEPS) == 8
    assert min(NODE_TO_STEP_INDEX.values()) == 0

    hints = typing.get_type_hints(FinalResponse, include_extras=True)
    assert typing.get_args(hints["status"]) == ("reviewed", "insufficient", "unmapped")
