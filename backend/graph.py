"""LangGraph StateGraph 조립. ⓪~⑥ 노드를 순서대로 연결한다.

그룹 팬아웃은 LangGraph Send API가 아니라 순차 loop로 시작한다 — 지금 규모(하루 그룹 수 적음)면
충분하다는 것이 현재 판단이고, 병렬 처리가 필요해지면 이 파일만 바꾸면 된다
(personalspace/0708 work/산출물_데이터모델설계.md §3 "그룹 팬아웃" 참고).

미매핑 패턴(GraphRAG candidates가 빈 그룹)은 ④~⑥을 건너뛰고 바로 "원인 분석 데이터 없음"
응답으로 간다 — 이 분기는 nodes/graphrag.py와 nodes/response.py 안에서 처리한다(TODO).
"""

from __future__ import annotations

import inspect

from langgraph.graph import END, StateGraph

from .graph_client import KGClient
from .mcp_client import MCPClient
from .nodes import cnn, critic, graphrag, grouper, hypothesis, lowyield, response, vlm_describe
from .state import RCAState


def build_graph(kg_client: KGClient, mcp: MCPClient):
    """RCAState를 상태로 갖는 StateGraph를 조립해 반환한다.

    fetch_graphrag_candidates/build_hypotheses/review_hypotheses/generate_response는
    kg_client·mcp를 추가로 필요로 해서, 람다가 아니라 실제 async 함수로 감싼다 —
    build_hypotheses/review_hypotheses는 내부에서 await가 필요한데 lambda는 await를
    못 담으므로 일반 def로는 코루틴 객체만 반환하고 실행이 안 된다.
    """
    workflow = StateGraph(RCAState)

    async def _fetch_graphrag_candidates(state: RCAState) -> dict:
        return graphrag.fetch_graphrag_candidates(state, kg_client)

    async def _build_hypotheses(state: RCAState) -> dict:
        return await _run_per_group(state, hypothesis.build_hypotheses, mcp)

    async def _review_hypotheses(state: RCAState) -> dict:
        return await _run_per_group(state, critic.review_hypotheses, mcp)

    async def _generate_response(state: RCAState) -> dict:
        return await _run_per_group(state, response.generate_response)

    workflow.add_node("select_low_yield_lots", lowyield.select_low_yield_lots)
    workflow.add_node("read_wafer_maps", cnn.read_wafer_maps)
    workflow.add_node("group_by_pattern", grouper.group_by_pattern)
    # ③ 관측 생산(v1.5: VLM은 Grouper 뒤, 스택맵에 1회) — 스켈레톤은 패턴별 결정적 템플릿.
    workflow.add_node("observe_groups", vlm_describe.observe_groups)
    workflow.add_node("fetch_graphrag_candidates", _fetch_graphrag_candidates)
    workflow.add_node("build_hypotheses", _build_hypotheses)
    workflow.add_node("review_hypotheses", _review_hypotheses)
    workflow.add_node("generate_response", _generate_response)

    workflow.set_entry_point("select_low_yield_lots")
    workflow.add_edge("select_low_yield_lots", "read_wafer_maps")
    workflow.add_edge("read_wafer_maps", "group_by_pattern")
    workflow.add_edge("group_by_pattern", "observe_groups")
    workflow.add_edge("observe_groups", "fetch_graphrag_candidates")
    workflow.add_edge("fetch_graphrag_candidates", "build_hypotheses")
    workflow.add_edge("build_hypotheses", "review_hypotheses")
    workflow.add_edge("review_hypotheses", "generate_response")
    workflow.add_edge("generate_response", END)

    return workflow.compile()


async def _run_per_group(state: RCAState, node_fn, *extra_args) -> dict:
    """group_id 단위 노드 함수를 groups 전체에 순차 적용하고 결과를 병합한다.

    node_fn은 async(build_hypotheses/review_hypotheses)일 수도, sync(generate_response)일
    수도 있어서 둘 다 받는다. 순차 loop다 — 병렬(Send API)은 규모가 커지면 재검토
    (산출물_데이터모델설계.md §3 "그룹 팬아웃").
    """
    merged: dict = {}
    for group in state["groups"]:
        result = node_fn(state, group["group_id"], *extra_args)
        if inspect.isawaitable(result):
            result = await result
        for key, partial in result.items():
            merged.setdefault(key, {}).update(partial)
    return merged
