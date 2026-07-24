"""LangGraph StateGraph 조립 — 배치 그래프(⓪~③ + run_groups) + 그룹 서브그래프(④~⑦).

그룹 처리 구간(④~⑦)을 그룹 하나짜리 좁은 상태(GroupState)를 쓰는 **그룹 서브그래프**로 떼어내고,
바깥 그래프는 groups를 순차로 돌며 그 서브그래프를 호출하는 run_groups 노드 하나로 팬아웃한다.
Send 병렬화는 범위 밖(§7.1) — MCP 싱글턴 세션 재사용(mcp_client/client.py) 때문에 순차로 시작한다.

step 3(#33, 행위 보존): ④⑤⑥⑦ 노드 함수가 **GroupState를 직접 받는다**. #38이 임시로 두었던
브리지 클로저와 그룹 dict 재구성 헬퍼는 제거됐고, 반환도 `{group_id: 값}` 중첩 없이 납작하다.
그룹 키 dict로 다시 모으는 일은 바깥의 run_groups 한 곳에서만 한다.
라우팅(후보 0건/채택 0건 컷)은 조건부 엣지로 그래프 위상에 박혀 있다(step 4).
"""

from __future__ import annotations

import contextvars
import datetime
import logging
from functools import partial

from langgraph.graph import END, StateGraph

from . import store
from .graph_client import KGClient
from .mcp_client import MCPClient
from .nodes import cnn, critic, graphrag, grouper, hypothesis, lowyield, response, vlm_describe
from .state import GroupState, RCAState

logger = logging.getLogger(__name__)


def _now_hms() -> str:
    """logs[].time — §2.4 예외 형식(HH:MM:SS). batch_runner._now_hms와 동형(순환 import 회피용 로컬)."""
    return datetime.datetime.now().strftime("%H:%M:%S")


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


def _build_group_subgraph(kg_client: KGClient, mcp: MCPClient, translate=None):
    """④~⑦ 그룹 서브그래프(state=GroupState). 노드 함수를 직접 등록한다(step 3, #33).

    노드 함수가 GroupState를 그대로 받으므로 #38의 브리지 클로저(그룹 하나짜리 RCAState를
    되만들어 옛 시그니처로 넘기던 것)는 사라졌다. kg_client·mcp·translate 같은 의존성은 LangGraph가
    노드를 fn(state)로 부르기 때문에 partial로 조립 시점에 묶어 둔다.
    함수 내부 알고리즘·MCP 호출 순서·캐싱은 한 줄도 안 바뀐다.

    translate: ⑦ description의 영어→한국어 번역기(deps.response_translator, RESPONSE_LLM=1일 때만
    실체). None이면 응답노드가 원문(영어)을 그대로 운반한다(기본/테스트 — 결정적).
    """
    sub = StateGraph(GroupState)
    # 노드명은 옛 바깥 노드명을 그대로 물려받는다(NODE_TO_STEP_INDEX 4·5·6·7과 대응, §8.2c).
    sub.add_node(
        "fetch_graphrag_candidates",
        partial(graphrag.fetch_graphrag_candidates, kg_client=kg_client),
    )
    sub.add_node("build_hypotheses", partial(hypothesis.build_hypotheses, mcp=mcp))
    sub.add_node("review_hypotheses", partial(critic.review_hypotheses, mcp=mcp))
    sub.add_node("generate_response", partial(response.generate_response, translate=translate))
    sub.add_node("respond_without_llm", partial(response.respond_without_llm, translate=translate))
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


async def run_groups(state: RCAState, group_graph, batch_id: str | None = None) -> dict:
    """groups를 순차로 돌며 그룹 서브그래프를 호출하고 결과를 {group_id: 값}으로 모은다.

    순차 for 루프다 — Send 병렬화는 범위 밖(§7.1). MCP 세션을 새로 열지 않는다(group_graph의
    노드가 이미 주입된 mcp 싱글턴을 재사용한다).

    Normal 방어 가드(§6.3): ②가 Normal 그룹을 안 만드는 게 원칙이지만(정상 웨이퍼=그룹 미생성),
    표기 차이 등으로 새어 들어오면 서브그래프에 태우지 않고 로그만 남긴다 — 그래프 갈래가 아니라
    "여기 오면 안 되는데 왔다"를 기록하는 것이라 라우팅이 아닌 가드로 둔다.

    고장 격리(노드 실패 계약): 한 그룹의 서브그래프가 예상 못 한 예외(MCP 프록시 재던짐·LLM
    API 에러·Neo4j 끊김·KeyError 등, 노드 내부 좁은 폴백이 못 잡는 것)를 던지면 그 예외를 그
    그룹 안에 가둔다 — 배치 로그에 status="error"로 남기고(§2.4, batch_id 있을 때) 결과 없이
    다음 그룹으로 넘어간다. 재시도는 없다(곱게 무너짐, 기획안 §5.2·§7.1). 이렇게 해야 이미
    성공한 다른 그룹 결과가 run_batch 최상단 except에서 배치째 유실되지 않는다. 조건부 엣지
    2종(후보 0건·채택 0건)은 "정상 종단"이라 예외가 아니며 여기 걸리지 않는다.
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
        except Exception as exc:  # 이 그룹만 격리 — 배치는 나머지 그룹으로 계속(재시도 없음)
            logger.exception("그룹 처리 실패 — 이 그룹만 건너뜀: %s", gid)
            if batch_id is not None:
                # 로깅은 best-effort — 로그 write 자체가 던져도(sqlite 잠금·디스크 오류) 격리가
                # 뚫려선 안 된다. 여기서 새면 run_batch 최상단 except가 배치째 죽여 이미 성공한
                # 그룹까지 유실된다(격리 계약의 최후 보루).
                try:
                    store.append_batch_log(
                        batch_id,
                        {
                            "time": _now_hms(),
                            "tool": "pipeline",
                            "message": f"[{group['pattern']}] 그룹 처리 실패 — {exc}",
                            "status": "error",
                        },
                    )
                except Exception:
                    logger.warning("실패 그룹 로그 기록 실패(무시하고 계속): %s", gid)
            continue
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


def build_graph(kg_client: KGClient, mcp: MCPClient, batch_id: str | None = None, translate=None):
    """RCAState를 상태로 갖는 바깥 StateGraph를 조립해 반환한다.

    ⓪~③은 배치당 1회(바깥 노드), ④~⑦은 그룹마다 반복(서브그래프). 이 경계가 서브그래프 경계다.
    ③ observe_groups는 #25가 배치 노드로 머지한 그대로 바깥에 둔다(A안).

    batch_id는 run_groups의 고장 격리 로그를 어느 배치에 남길지 알려주는 용도다(기본 None이면
    조립·테스트 경로 — 로그는 남기지 않고 격리만 한다). translate는 ⑦ description 번역기(기본
    None = 원문 운반). LangGraph는 노드를 fn(state)로 부르므로 _run_groups 클로저에 묶어 넘긴다.
    """
    group_graph = _build_group_subgraph(kg_client, mcp, translate)

    async def _run_groups(state: RCAState) -> dict:
        return await run_groups(state, group_graph, batch_id=batch_id)

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
