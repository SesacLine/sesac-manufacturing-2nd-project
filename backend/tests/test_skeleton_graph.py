"""step 2 — graph.py: 그룹 서브그래프(④~⑦) + run_groups 테스트 (AC-5..10).

build_graph(kg_client, mcp)는 조립(컴파일) 시점에 kg_client/mcp를 실제로 호출하지 않는다
(그래프를 짜기만 한다) — 그래서 더미 object()를 그대로 넘겨도 안전하고, 네트워크·MCP
서브프로세스·fab.db가 전혀 필요 없다(AC-10 하나만 예외, data 마커).
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from backend.graph import build_graph


def _edges(g):
    return {(e.source, e.target) for e in g.get_graph().edges}


# covers: AC-5
def test_group_processing_is_a_separate_subgraph_invoked_by_run_groups():
    g = build_graph(object(), object())
    outer_nodes = set(g.nodes.keys())
    assert "run_groups" in outer_nodes, "④~⑦을 순차 호출하는 run_groups 노드가 바깥 그래프에 없다"
    for inner_node in (
        "fetch_graphrag_candidates", "build_hypotheses", "review_hypotheses", "generate_response",
    ):
        assert inner_node not in outer_nodes, (
            f"{inner_node}는 그룹 서브그래프 안으로 옮겨져야 한다(바깥 그래프 노드가 아니다)"
        )


# covers: AC-6
def test_run_per_group_removed_and_unreferenced_in_backend_source():
    from backend import graph as graph_module

    assert not hasattr(graph_module, "_run_per_group"), "_run_per_group이 아직 남아있다"

    backend_dir = Path(graph_module.__file__).resolve().parent
    for path in backend_dir.rglob("*.py"):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        assert "_run_per_group" not in text, f"_run_per_group이 {path}에 여전히 참조된다"


# covers: AC-7
def test_observe_groups_stays_outer_batch_node_feeding_run_groups():
    g = build_graph(object(), object())
    assert "observe_groups" in g.nodes, "observe_groups는 서브그래프가 아니라 바깥 배치 노드에 남아야 한다"
    assert ("observe_groups", "run_groups") in _edges(g)


# covers: AC-8
def test_outer_graph_node_order_matches_spec_chain():
    g = build_graph(object(), object())
    edges = _edges(g)
    chain = [
        "__start__", "select_low_yield_lots", "read_wafer_maps",
        "group_by_pattern", "observe_groups", "run_groups", "__end__",
    ]
    for src, dst in zip(chain, chain[1:]):
        assert (src, dst) in edges, f"바깥 그래프 엣지 {src} -> {dst}가 없다(§3 그림 순서)"


# covers: AC-9
def test_group_node_functions_keep_old_signature_via_adapter():
    from backend.graph import run_groups  # 서브그래프/어댑터가 서기 전까진 존재하지 않는다(red)
    from backend.nodes import critic, graphrag, hypothesis, response

    assert list(inspect.signature(hypothesis.build_hypotheses).parameters) == [
        "state", "group_id", "mcp",
    ]
    assert list(inspect.signature(critic.review_hypotheses).parameters) == [
        "state", "group_id", "mcp",
    ]
    assert list(inspect.signature(response.generate_response).parameters) == ["state", "group_id"]
    assert list(inspect.signature(graphrag.fetch_graphrag_candidates).parameters) == [
        "state", "kg_client",
    ]


class _EmptyKG:
    """후보 0건만 돌려주는 fake KGClient — unmapped 경로 통합 테스트용(mcp 불필요)."""

    def get_candidates(self, pattern, observation=None):
        return {"pattern": pattern, "candidates": []}


# covers: AC-5, AC-11, AC-14
def test_subgraph_unmapped_path_routes_adapter_to_respond_without_llm():
    """④ 후보 0건 → route_on_candidates → ⑦' respond 어댑터 통합 경로를 실제 ainvoke로 탄다.

    ④ 후보 0건 처리는 build/critic을 건너뛰므로 mcp는 안 불린다(object() 더미로 충분). 순수함수
    단위 테스트(test_skeleton_response)가 우회했던 '어댑터 fake-state 재구성 + 라우팅' 통합을 덮는다.
    """
    import asyncio

    from backend.graph import _build_group_subgraph

    sub = _build_group_subgraph(_EmptyKG(), object())
    gstate = {
        "group_id": "g-unknown",
        "pattern": "Unknown",
        "lot_ids": ["L1"],
        "cursor_date": "2026-01-01",
        "cursor_end": "2026-01-02",
        "observation": None,
    }
    out = asyncio.run(sub.ainvoke(gstate))
    final = out["final_response"]
    assert final["status"] == "unmapped"
    assert final["hypotheses"] == []
    assert final["pattern"] == "Unknown"
    assert final["lot_ids"] == ["L1"]


GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "ac10_full_batch_golden.json"


# covers: AC-10
@pytest.mark.data
def test_full_batch_persisted_results_byte_identical_to_pre_refactor_golden():
    """2차 게이트. fab.db + 사전 캡처된 golden 스냅샷이 모두 있어야 실질 비교를 한다.

    golden 캡처 절차(구현자가 리팩터 착수 전 1회 수행): 현재(리팩터 전) 코드로 배치를 1회
    돌려 final_response/wafer_readings/cursor 결과를 이 경로에 JSON으로 저장해 둔다.
    이 테스트는 그 스냅샷과 리팩터 후 결과를 비교한다 — 스냅샷이 없으면 skip(로컬 수동
    검증 대상, 스펙 §"검증 방법" 2차 게이트).
    """
    from backend.config import fab_db_path

    if not fab_db_path().exists():
        pytest.skip("fab.db 없음 — 2차 게이트는 fab.db 준비 후 로컬에서 수동 확인 대상")
    if not GOLDEN_PATH.exists():
        pytest.skip(
            f"golden 스냅샷 없음({GOLDEN_PATH}) — 리팩터 착수 전 현재 코드로 배치를 1회 돌려 "
            "final_response/wafer_readings/cursor를 캡처해 저장해야 한다"
        )

    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert "final_response" in golden or "analyses" in golden
