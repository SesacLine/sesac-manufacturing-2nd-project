"""LangGraph StateGraph 조립 — 배치 그래프(⓪~③ + run_groups) + 그룹 서브그래프(④~⑦).

그룹 처리 구간(④~⑦)을 그룹 하나짜리 좁은 상태(GroupState)를 쓰는 **그룹 서브그래프**로 떼어내고,
바깥 그래프는 groups를 순차로 돌며 그 서브그래프를 호출하는 run_groups 노드 하나로 팬아웃한다.
Send 병렬화는 범위 밖(§7.1) — MCP 싱글턴 세션 재사용(mcp_client/client.py) 때문에 순차로 시작한다.

step 2(행위 보존): ④⑤⑥⑦ 노드 함수는 **아직 옛 시그니처**((state, group_id, mcp) 등)를 그대로 두고,
서브그래프 노드는 그 함수를 GroupState로 브리지하는 **어댑터**다. 시그니처 평탄화는 step 3(#33).
라우팅(후보 0건/채택 0건 컷)과 Normal 가드는 step 4에서 조건부 엣지로 꺼낸다 — 지금 서브그래프는
선형(④→⑤→⑥→⑦)이라 옛 코드의 "노드 내부 분기"와 동작이 같다.
"""

from __future__ import annotations

import contextvars
import logging

from langgraph.graph import END, StateGraph

from .graph_client import KGClient
from .mcp_client import MCPClient
from .nodes import cnn, critic, graphrag, grouper, hypothesis, lowyield, response, vlm_describe
from .state import GroupState, RCAState

logger = logging.getLogger(__name__)

# 진행 로그 그룹 태그(§8.3). 비동기 작업마다 각자 값을 갖는 ContextVar라 순차·Send 병렬 양쪽에서
# 안 섞인다. run_groups가 그룹마다 set하고, batch_runner._tag_message가 읽어 로그 앞에 [Center]처럼 붙인다.
_CURRENT_GROUP: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_group", default=None
)


def _to_group_state(group: dict, state: RCAState) -> dict:
    """② Group + 배치 스코프에서 서브그래프 입력 GroupState를 만든다."""
    return {
        "group_id": group["group_id"],
        "pattern": group["pattern"],
        "lot_ids": group["lot_ids"],
        "cursor_date": state["cursor_date"],
        "cursor_end": state["cursor_end"],
        "observation": group.get("observation"),
    }


def route_on_candidates(state: GroupState) -> str:
    """④ 뒤 라우팅 — 후보가 0건이면 ⑤⑥을 건너뛰고 ⑦'로. 패턴명은 보지 않는다(§6.1).

    3종이든 Unknown이든 "KG가 후보를 줬나" 하나로 갈린다. 후보가 있으면 build_hypotheses로.
    """
    if not state.get("candidates"):
        return "respond_without_llm"
    return "build_hypotheses"


def route_on_verdicts(state: GroupState) -> str:
    """⑥ 뒤 라우팅 — 채택 0건이면 LLM(⑦)을 아예 호출하지 않는다(환각 억제 장치, §6.2).

    재료(채택 가설) 없이 문장을 쓰게 하지 않는 것이 이 컷의 이유다. 채택 ≥1이면 generate_response로.
    """
    result = state.get("critic_result")
    if not result or not result.get("accepted"):
        return "respond_without_llm"
    return "generate_response"


def _group_for_node(gstate: GroupState) -> dict:
    """옛 노드 함수가 state["groups"]에서 group_id로 찾아 쓰는 그룹 dict를 GroupState에서 되만든다."""
    return {
        "group_id": gstate["group_id"],
        "pattern": gstate["pattern"],
        "lot_ids": gstate["lot_ids"],
        "status": "",
        "observation": gstate.get("observation"),
    }


def _build_group_subgraph(kg_client: KGClient, mcp: MCPClient):
    """④~⑦ 그룹 서브그래프(state=GroupState). 노드는 옛 시그니처 함수를 감싼 어댑터다.

    각 어댑터는 "그 그룹 하나짜리 fake RCAState"를 만들어 옛 함수를 부르고, 반환 dict에서
    자기 그룹의 슬라이스를 꺼내 GroupState 키로 돌려준다(dict[group_id] 중첩이 한 겹 벗겨진다).
    함수 내부 알고리즘·MCP 호출 순서·캐싱은 한 줄도 안 바뀐다.
    """

    async def fetch_kg(gstate: GroupState) -> dict:
        gid = gstate["group_id"]
        fake = {"groups": [_group_for_node(gstate)]}
        out = graphrag.fetch_graphrag_candidates(fake, kg_client)
        result = out["graphrag_candidates"][gid]
        return {"candidates": result["candidates"]}

    async def build(gstate: GroupState) -> dict:
        gid = gstate["group_id"]
        fake = {
            "groups": [_group_for_node(gstate)],
            "graphrag_candidates": {
                gid: {"pattern": gstate["pattern"], "candidates": gstate["candidates"]}
            },
        }
        out = await hypothesis.build_hypotheses(fake, gid, mcp)
        return {"hypotheses": out["hypotheses"][gid]}

    async def review(gstate: GroupState) -> dict:
        gid = gstate["group_id"]
        fake = {
            "groups": [_group_for_node(gstate)],
            "hypotheses": {gid: gstate["hypotheses"]},
        }
        out = await critic.review_hypotheses(fake, gid, mcp)
        return {"critic_result": out["critic_result"][gid]}

    async def generate(gstate: GroupState) -> dict:
        gid = gstate["group_id"]
        fake = {
            "groups": [_group_for_node(gstate)],
            "graphrag_candidates": {
                gid: {"pattern": gstate["pattern"], "candidates": gstate["candidates"]}
            },
            "critic_result": {gid: gstate.get("critic_result")},
        }
        out = response.generate_response(fake, gid)
        return {"final_response": out["final_response"][gid]}

    async def respond(gstate: GroupState) -> dict:
        gid = gstate["group_id"]
        fake = {
            "groups": [_group_for_node(gstate)],
            "graphrag_candidates": {
                gid: {"pattern": gstate["pattern"], "candidates": gstate.get("candidates", [])}
            },
            "critic_result": {gid: gstate.get("critic_result")},
        }
        out = response.respond_without_llm(fake, gid)
        return {"final_response": out["final_response"][gid]}

    sub = StateGraph(GroupState)
    # 노드명은 옛 바깥 노드명을 그대로 물려받는다(NODE_TO_STEP_INDEX 4·5·6·7과 대응, §8.2c).
    sub.add_node("fetch_graphrag_candidates", fetch_kg)
    sub.add_node("build_hypotheses", build)
    sub.add_node("review_hypotheses", review)
    sub.add_node("generate_response", generate)
    sub.add_node("respond_without_llm", respond)
    sub.set_entry_point("fetch_graphrag_candidates")
    # ④ 뒤: 후보 0건이면 ⑤⑥ 건너뛰고 ⑦'로(§6.1).
    sub.add_conditional_edges(
        "fetch_graphrag_candidates",
        route_on_candidates,
        {"build_hypotheses": "build_hypotheses", "respond_without_llm": "respond_without_llm"},
    )
    sub.add_edge("build_hypotheses", "review_hypotheses")
    # ⑥ 뒤: 채택 0건이면 LLM(⑦) 안 부르고 ⑦'로(§6.2).
    sub.add_conditional_edges(
        "review_hypotheses",
        route_on_verdicts,
        {"generate_response": "generate_response", "respond_without_llm": "respond_without_llm"},
    )
    sub.add_edge("generate_response", END)
    sub.add_edge("respond_without_llm", END)
    return sub.compile()


async def run_groups(state: RCAState, group_graph) -> dict:
    """groups를 순차로 돌며 그룹 서브그래프를 호출하고 결과를 {group_id: 값}으로 모은다.

    순차 for 루프다 — Send 병렬화는 범위 밖(§7.1). MCP 세션을 새로 열지 않는다(group_graph의
    노드가 이미 주입된 mcp 싱글턴을 재사용한다).

    Normal 방어 가드(§6.3): ②가 Normal 그룹을 안 만드는 게 원칙이지만(정상 웨이퍼=그룹 미생성),
    표기 차이 등으로 새어 들어오면 서브그래프에 태우지 않고 로그만 남긴다 — 그래프 갈래가 아니라
    "여기 오면 안 되는데 왔다"를 기록하는 것이라 라우팅이 아닌 가드로 둔다.
    """
    merged: dict = {
        "graphrag_candidates": {},
        "hypotheses": {},
        "critic_result": {},
        "final_response": {},
    }
    for group in state["groups"]:
        gid = group["group_id"]
        if group["pattern"] == "Normal":
            logger.info("Normal 그룹 유입 — 건너뜀 (②에서 걸러졌어야 함): %s", gid)
            continue
        # 이 그룹 처리 동안의 MCP 로그에 [pattern] 태그가 붙도록 contextvar를 건다(§8.3).
        token = _CURRENT_GROUP.set(group["pattern"])
        try:
            out = await group_graph.ainvoke(_to_group_state(group, state))
        finally:
            _CURRENT_GROUP.reset(token)
        merged["graphrag_candidates"][gid] = {
            "pattern": group["pattern"],
            "candidates": out.get("candidates", []),
        }
        merged["hypotheses"][gid] = out.get("hypotheses", [])
        if out.get("critic_result") is not None:
            merged["critic_result"][gid] = out["critic_result"]
        if out.get("final_response") is not None:
            merged["final_response"][gid] = out["final_response"]
    return merged


def build_graph(kg_client: KGClient, mcp: MCPClient):
    """RCAState를 상태로 갖는 바깥 StateGraph를 조립해 반환한다.

    ⓪~③은 배치당 1회(바깥 노드), ④~⑦은 그룹마다 반복(서브그래프). 이 경계가 서브그래프 경계다.
    ③ observe_groups는 #25가 배치 노드로 머지한 그대로 바깥에 둔다(A안).
    """
    group_graph = _build_group_subgraph(kg_client, mcp)

    async def _run_groups(state: RCAState) -> dict:
        return await run_groups(state, group_graph)

    workflow = StateGraph(RCAState)
    workflow.add_node("select_low_yield_lots", lowyield.select_low_yield_lots)
    workflow.add_node("read_wafer_maps", cnn.read_wafer_maps)
    workflow.add_node("group_by_pattern", grouper.group_by_pattern)
    # ③ 관측 생산(v1.5: VLM은 Grouper 뒤, 스택맵에 1회, #25 배치 노드).
    workflow.add_node("observe_groups", vlm_describe.observe_groups)
    workflow.add_node("run_groups", _run_groups)

    workflow.set_entry_point("select_low_yield_lots")
    workflow.add_edge("select_low_yield_lots", "read_wafer_maps")
    workflow.add_edge("read_wafer_maps", "group_by_pattern")
    workflow.add_edge("group_by_pattern", "observe_groups")
    workflow.add_edge("observe_groups", "run_groups")
    workflow.add_edge("run_groups", END)

    return workflow.compile()
