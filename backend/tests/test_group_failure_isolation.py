"""그룹 서브그래프 고장 격리 — 한 그룹의 예외를 그 그룹 안에 가둔다.

계약(스펙 langgraph_골격_설계공유 §3 실패·경계 케이스에 추가): 그룹 2개 중 1개의
서브그래프가 예상 못 한 예외(MCP 프록시 재던짐·LLM API 에러·Neo4j 끊김·KeyError 등,
노드 내부 좁은 폴백이 못 잡는 것)를 던져도

  (a) run_groups가 예외를 위로 전파하지 않아 배치가 status="failed"로 죽지 않고,
  (b) 정상 그룹의 결과는 merged에 그대로 남으며,
  (c) 실패는 배치 로그에 status="error"로 남는다(§2.4 logs 형식, LoggingMCP와 동형).

재시도는 없다(곱게 무너짐, 기획안 §5.2·§7.1) — 실패 그룹은 결과 없이 스킵한다.
run_batch 최상단 배치-레벨 except와 조건부 엣지 2종은 이 변경과 무관하게 그대로다.

fab.db 없이 도는 테스트(`not data`) — 그룹 그래프를 예외 주입 스텁으로 대역한다.
"""

from __future__ import annotations

import asyncio

from backend import graph as graph_module

_HYP = {
    "cause": "슬러리 유량 불안정",
    "tier": "자동",
    "stage": "CMP",
    "equipment": "CMP-01",
    "citations": [],
    "sentence": "...",
    "evidence": {},
}


class _PartlyFailingGroupGraph:
    """지정 패턴 그룹에서만 예외를 던지고 나머지는 정상 결과를 주는 서브그래프 대역.

    run_groups가 부르는 컴파일 서브그래프의 ainvoke 인터페이스만 흉내낸다
    (test_skeleton_flatten의 _StubGroupGraph와 같은 계열, 예외 주입만 추가).
    """

    def __init__(self, fail_pattern: str) -> None:
        self.fail_pattern = fail_pattern
        self.seen: list[dict] = []

    async def ainvoke(self, gstate: dict) -> dict:
        self.seen.append(gstate)
        if gstate["pattern"] == self.fail_pattern:
            raise RuntimeError("MCP 프록시 재던짐(테스트 주입) — 노드 폴백이 못 잡는 예외")
        return {
            "candidates": [{"cause": "c1"}],
            "hypotheses": [dict(_HYP)],
            "critic_result": {"status": "accepted", "accepted": [dict(_HYP)], "rejected": []},
            "final_response": {"group_id": gstate["group_id"], "status": "reviewed"},
        }


def _state_two_groups() -> dict:
    """Center·Scratch 두 그룹짜리 배치 상태(Normal 아님 — 둘 다 서브그래프에 태워진다)."""
    return {
        "cursor_date": "2026-01-01",
        "cursor_end": "2026-01-31",
        "groups": [
            {"group_id": "Center-x", "pattern": "Center", "lot_ids": ["L1"],
             "status": "", "observation": None},
            {"group_id": "Scratch-x", "pattern": "Scratch", "lot_ids": ["L2"],
             "status": "", "observation": None},
        ],
    }


def test_group_failure_does_not_kill_batch_and_keeps_healthy_results():
    """(a)+(b): 첫 그룹이 터져도 run_groups는 정상 반환하고 둘째 그룹 결과는 남는다."""
    stub = _PartlyFailingGroupGraph(fail_pattern="Center")

    # 예외가 전파되면 asyncio.run이 여기서 raise → 테스트 실패 = (a) 위반을 잡는다.
    merged = asyncio.run(graph_module.run_groups(_state_two_groups(), stub))

    # (b) 정상 그룹만 결과에 남는다.
    assert list(merged["final_response"]) == ["Scratch-x"]
    assert merged["final_response"]["Scratch-x"]["status"] == "reviewed"
    assert merged["hypotheses"]["Scratch-x"] == [dict(_HYP)]
    assert merged["critic_result"]["Scratch-x"]["status"] == "accepted"
    assert merged["graphrag_candidates"]["Scratch-x"]["pattern"] == "Scratch"

    # 실패 그룹은 어떤 결과 필드에도 없다(곱게 무너짐 — 부분 카드 조립 안 함).
    for field in ("final_response", "hypotheses", "critic_result", "graphrag_candidates"):
        assert "Center-x" not in merged[field], f"{field}에 실패 그룹이 새어 들어왔다"

    # 두 그룹 모두 실제로 시도는 됐다(실패 그룹도 태워는 봤다 — 순회 자체는 계속됨).
    assert [g["pattern"] for g in stub.seen] == ["Center", "Scratch"]


def test_group_failure_is_recorded_in_batch_log_as_error(monkeypatch):
    """(c): 실패 그룹이 배치 로그에 status='error'로 남는다(§2.4 형식, 패턴 태그 포함)."""
    logs: list[tuple] = []
    monkeypatch.setattr(
        graph_module.store, "append_batch_log",
        lambda batch_id, entry: logs.append((batch_id, entry)),
    )
    stub = _PartlyFailingGroupGraph(fail_pattern="Center")

    asyncio.run(graph_module.run_groups(_state_two_groups(), stub, batch_id="batch_x"))

    assert len(logs) == 1, "실패 그룹 1건당 로그 1건이어야 한다"
    batch_id, entry = logs[0]
    assert batch_id == "batch_x"
    assert entry["status"] == "error"
    assert entry["tool"] == "pipeline"
    assert "[Center]" in entry["message"], "로그 메시지에 그룹 패턴 태그가 붙어야 한다(§8.3)"
    assert set(entry) == {"time", "tool", "message", "status"}, "§2.4 로그 엔트리 4키 형식"


def test_group_failure_without_batch_id_isolates_without_logging(monkeypatch):
    """batch_id 미지정(조립·테스트 경로)에서도 격리는 되고 로그 시도는 하지 않는다."""
    called: list = []
    monkeypatch.setattr(
        graph_module.store, "append_batch_log", lambda *a, **k: called.append((a, k))
    )
    stub = _PartlyFailingGroupGraph(fail_pattern="Center")

    merged = asyncio.run(graph_module.run_groups(_state_two_groups(), stub))  # batch_id 기본 None

    assert list(merged["final_response"]) == ["Scratch-x"]
    assert called == [], "batch_id가 없으면 append_batch_log를 부르지 않는다"


def test_logging_failure_does_not_defeat_isolation(monkeypatch):
    """격리의 최후 보루: 로그 write 자체가 던져도 배치가 죽지 않고 정상 그룹은 보존된다.

    append_batch_log가 sqlite 잠금·디스크 오류로 던지는 상황을 모사한다. 로깅은 best-effort라야
    하며, 로깅 실패가 run_groups 밖으로 새면 run_batch 최상단 except가 배치째 failed로 만들어
    이미 성공한 그룹 결과가 통째로 유실된다(계약 (a)의 잔여 구멍, 코드리뷰 Medium 지적).
    """
    def _boom(batch_id, entry):
        raise RuntimeError("sqlite database is locked(테스트 주입)")

    monkeypatch.setattr(graph_module.store, "append_batch_log", _boom)
    stub = _PartlyFailingGroupGraph(fail_pattern="Center")

    # 로그가 던져도 여기서 예외가 새어나오면 안 된다(현재는 새어나옴 → RED).
    merged = asyncio.run(graph_module.run_groups(_state_two_groups(), stub, batch_id="batch_x"))

    assert list(merged["final_response"]) == ["Scratch-x"], "로깅 실패가 정상 그룹 결과를 날리면 안 된다"
    assert "Center-x" not in merged["final_response"]


class _FailingKG:
    """지정 패턴의 KG 조회에서 예외를 던지는 fake KGClient(Neo4j 끊김 모사).

    ④ fetch_graphrag_candidates 노드가 실제로 예외를 던지게 만들어, 위 스텁이 아닌
    **진짜 컴파일 서브그래프**가 노드 안에서 터지는 프로덕션 형상을 재현한다.
    """

    def get_candidates(self, pattern, observation=None):
        if pattern == "Center":
            raise RuntimeError("Neo4j 연결 끊김(테스트 주입)")
        return {"pattern": pattern, "candidates": []}  # Scratch는 후보 0건 → unmapped 정상 종단


def test_astream_production_path_isolates_real_subgraph_exception():
    """프로덕션 경로 회귀 고정: 실제 build된 서브그래프가 노드에서 던져도
    바깥 graph.astream(subgraphs=True)이 배치를 죽이지 않고 정상 그룹을 남긴다.

    운영은 run_groups 직접 호출이 아니라 astream(subgraphs=True)으로 돈다(batch_runner). 이
    테스트는 실제 _build_group_subgraph로 컴파일한 서브그래프(노드가 진짜 예외를 던짐)를 최소
    바깥 그래프에 물려 astream으로 돌린다 — ⓪~③(fab.db 필요)은 격리 검증과 무관해 뺀다.
    안쪽 서브그래프 예외가 ainvoke await 이외 채널로 새어 astream을 깨뜨리지 않음을 실증한다.
    """
    from langgraph.graph import END, StateGraph

    from backend.graph import _build_group_subgraph, run_groups
    from backend.state import RCAState

    group_graph = _build_group_subgraph(_FailingKG(), object())

    async def _run_groups(state):
        return await run_groups(state, group_graph)  # batch_id None — 격리만, 로그 없음

    outer = StateGraph(RCAState)
    outer.add_node("run_groups", _run_groups)
    outer.set_entry_point("run_groups")
    outer.add_edge("run_groups", END)
    app = outer.compile()

    state = {
        "cursor_date": "2026-01-01",
        "cursor_end": "2026-01-31",
        "target_lot_ids": [],
        "vlm_results": [],
        "groups": _state_two_groups()["groups"],
        "graphrag_candidates": {},
        "hypotheses": {},
        "critic_result": {},
        "final_response": {},
    }

    async def _drive():
        # batch_runner와 동형: subgraphs=True, 바깥 신호(namespace 빔)만 누적.
        merged: dict = {}
        async for namespace, update in app.astream(
            state, stream_mode="updates", subgraphs=True
        ):
            if namespace:
                continue
            for _node, part in update.items():
                if isinstance(part, dict):
                    merged.update(part)
        return merged

    # astream이 예외로 깨지면 asyncio.run이 여기서 raise → 테스트 실패(프로덕션 비전파 위반 포착).
    merged = asyncio.run(_drive())

    # Center는 예외로 스킵, Scratch는 후보 0건 unmapped로 정상 종단.
    assert "Center-x" not in merged["final_response"], "예외 그룹이 결과에 새어들면 안 된다"
    assert merged["final_response"]["Scratch-x"]["status"] == "unmapped"
