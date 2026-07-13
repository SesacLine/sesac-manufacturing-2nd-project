"""LangGraph StateGraph 조립. ⓪~⑥ 노드를 순서대로 연결한다.

그룹 팬아웃은 LangGraph Send API가 아니라 순차 loop로 시작한다 — 지금 규모(하루 그룹 수 적음)면
충분하다는 것이 현재 판단이고, 병렬 처리가 필요해지면 이 파일만 바꾸면 된다
(personalspace/0708 work/산출물_데이터모델설계.md §3 "그룹 팬아웃" 참고).

미매핑 패턴(GraphRAG candidates가 빈 그룹)은 ④~⑥을 건너뛰고 바로 "원인 분석 데이터 없음"
응답으로 간다 — 이 분기는 nodes/graphrag.py와 nodes/response.py 안에서 처리한다(TODO).
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from .graph_client import KGClient
from .mcp_client import MCPClient
from .nodes import critic, graphrag, grouper, hypothesis, lowyield, response, vlm
from .state import RCAState


def build_graph(kg_client: KGClient, mcp: MCPClient):
    """RCAState를 상태로 갖는 StateGraph를 조립해 반환한다.

    TODO: 각 async 노드 함수를 StateGraph가 기대하는 (state) -> dict 시그니처로 감싸고
          (group_id 순회는 node wrapper 내부에서 처리), 조건부 엣지(미매핑 패턴 스킵,
          insufficient_evidence 처리)를 추가한다.
    """
    workflow = StateGraph(RCAState)

    workflow.add_node("select_low_yield_lots", lowyield.select_low_yield_lots)
    workflow.add_node("read_wafer_maps", vlm.read_wafer_maps)
    workflow.add_node("group_by_pattern", grouper.group_by_pattern)
    workflow.add_node(
        "fetch_graphrag_candidates",
        lambda state: graphrag.fetch_graphrag_candidates(state, kg_client),
    )
    workflow.add_node(
        "build_hypotheses", lambda state: _run_per_group(state, hypothesis.build_hypotheses, mcp)
    )
    workflow.add_node(
        "review_hypotheses", lambda state: _run_per_group(state, critic.review_hypotheses, mcp)
    )
    workflow.add_node(
        "generate_response", lambda state: _run_per_group(state, response.generate_response)
    )

    workflow.set_entry_point("select_low_yield_lots")
    workflow.add_edge("select_low_yield_lots", "read_wafer_maps")
    workflow.add_edge("read_wafer_maps", "group_by_pattern")
    workflow.add_edge("group_by_pattern", "fetch_graphrag_candidates")
    workflow.add_edge("fetch_graphrag_candidates", "build_hypotheses")
    workflow.add_edge("build_hypotheses", "review_hypotheses")
    workflow.add_edge("review_hypotheses", "generate_response")
    workflow.add_edge("generate_response", END)

    return workflow.compile()


def _run_per_group(state: RCAState, node_fn, *extra_args) -> dict:
    """group_id 단위 노드 함수를 groups 전체에 순차 적용하고 결과를 병합한다.

    TODO: 실제 구현. node_fn(state, group_id, *extra_args)를 각 group에 대해 호출하고
          반환된 partial state(dict)들을 병합해 반환한다.
    """
    raise NotImplementedError
