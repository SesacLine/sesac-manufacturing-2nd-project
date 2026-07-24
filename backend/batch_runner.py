"""배치 파이프라인 백그라운드 실행기 (§2.3 접수 → §2.4 진행 방출 → 결과 저장).

main.py의 POST /batches가 배치 row를 만들고 asyncio.create_task로 run_batch를 띄운다.
run_batch는:
    1. 누적 커서 계산(직전 배치 커서 이후 ~ 데이터축 최신일, §2.3)
    2. LoggingMCP(MCP 호출 트레이스 → batch.logs)로 그래프를 새로 조립
    3. graph.astream(updates)으로 노드 완료마다 current_step 갱신(§2.4 8키, AGENT_GUIDE §5 매핑)
    4. 완료 시 그룹별 analysis payload 조립·저장, 웨이퍼 판독 저장, result_ids 기록, 커서 전진
    5. 실패 시 status="failed" + error 기록 (§2.4 — HTTP가 아니라 body status로 표현)

주의: MCPClient 싱글턴 세션 재사용 패턴(CLAUDE.md)을 깨지 않는다 — LoggingMCP는 그
싱글턴을 감싸는 위임 프록시일 뿐, 세션을 새로 만들지 않는다.
"""

from __future__ import annotations

import asyncio
import datetime
import inspect
import sqlite3
from typing import Any

from . import store
from .assembler import build_analysis_payload
from .config import DATA_EPOCH, EVENT_DATE_COMPACT, fab_db_path
from .graph import _CURRENT_GROUP, build_graph
from .graph_client import KGClient
from .mcp_client import MCPClient
from .schemas import NODE_TO_STEP_INDEX, normalize_pattern, pattern_slug

# create_task로 띄운 배치 태스크가 GC로 사라지지 않게 참조를 붙잡아 둔다.
_running_tasks: set[asyncio.Task] = set()

# LoggingMCP가 트레이스를 남길 MCP 도구 메서드 이름(secsgem-mcp 9종 도구와 동일).
_MCP_TOOL_METHODS = {
    "get_wafer_map",
    "get_lot_history",
    "run_commonality_analysis",
    "get_normal_lot_ratio",
    "query_telemetry",
    "get_alarm_history",
    "get_maintenance_history",
    "detect_change_points",
    "get_lot_timeline",
}


def _now_hms() -> str:
    """logs[].time — §2.4 예외 형식(HH:MM:SS). 날짜는 batch_id에서 파생되므로 시각만."""
    return datetime.datetime.now().strftime("%H:%M:%S")


def _tag_message(message: str) -> str:
    """진행 로그 메시지 앞에 현재 그룹 태그를 붙인다(§8.1·§8.3).

    run_groups가 그룹마다 _CURRENT_GROUP(contextvars)에 pattern을 걸어두므로, 여기서 읽어
    "[Center] run_commonality_analysis — 12건"처럼 앞에 붙인다. 그룹 밖(⓪~③ 배치 구간)이면
    태그 없이 그대로 둔다. contextvars라 Send 병렬화 후에도 그룹 로그가 안 섞인다.
    """
    group = _CURRENT_GROUP.get()
    return f"[{group}] {message}" if group else message


def process_stream_item(
    namespace: tuple, update: dict, current_step: int
) -> tuple[int, dict | None]:
    """astream(subgraphs=True)의 (namespace, update) 한 쌍을 처리한다(§8.2).

    - **안쪽 신호**(namespace 비어있지 않음): 서브그래프 내부 노드 완료 → **진행 표시 전용**.
      state_delta=None 을 돌려 부모 state를 GroupState 부분상태로 덮어쓰지 않는다(§8.2b).
    - **바깥 신호**(namespace 빔): 배치 노드 완료 → state_delta=부분상태(결과 누적용).
    - **current_step**: 완료 노드명을 NODE_TO_STEP_INDEX로 조회해 max(현재, 조회값)(단조 증가, §8.1).
      바깥 이름과 서브그래프 내부 이름(④~⑦)이 같은 표를 공유한다(내부명=옛 바깥명, §8.2c).
      표에 없는 노드(run_groups)는 current_step을 그대로 둔다.
    """
    is_inner = bool(namespace)
    new_step = current_step
    delta: dict | None = None
    for node_name, partial in update.items():
        if node_name in NODE_TO_STEP_INDEX:
            new_step = max(new_step, NODE_TO_STEP_INDEX[node_name])
        if not is_inner and isinstance(partial, dict):
            delta = {**(delta or {}), **partial}
    return new_step, delta


class LoggingMCP:
    """MCPClient 위임 프록시 — 도구 호출 1건마다 batch.logs에 트레이스를 남긴다(§2.4 logs)."""

    def __init__(self, inner: MCPClient, batch_id: str) -> None:
        self._inner = inner
        self._batch_id = batch_id

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if name not in _MCP_TOOL_METHODS or not inspect.iscoroutinefunction(attr):
            return attr

        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            message = _describe_call(args, kwargs)
            try:
                result = await attr(*args, **kwargs)
            except Exception as exc:
                store.append_batch_log(
                    self._batch_id,
                    {"time": _now_hms(), "tool": name, "message": _tag_message(f"{message} — {exc}"), "status": "error"},
                )
                raise
            store.append_batch_log(
                self._batch_id,
                {"time": _now_hms(), "tool": name, "message": _tag_message(message), "status": "done"},
            )
            return result

        return wrapped


def _describe_call(args: tuple, kwargs: dict) -> str:
    """도구 호출 인자를 짧은 표시 문자열로 요약한다(로그 콘솔용)."""
    parts: list[str] = []
    for a in args:
        if isinstance(a, list):
            parts.append(f"{len(a)}건")
        elif isinstance(a, (str, int)):
            parts.append(str(a))
    for k, v in kwargs.items():
        if v is None:
            continue
        if isinstance(v, list):
            parts.append(f"{k}={len(v)}건" if len(v) > 3 else f"{k}={v}")
        else:
            parts.append(f"{k}={v}")
    return ", ".join(parts) if parts else "(인자 없음)"


def _cursor_range() -> tuple[str, str]:
    """(cursor_date exclusive, cursor_end inclusive) — §2.3 누적 스코프.

    첫 배치는 데이터축 처음(EPOCH)부터 전부 본다(직전 배치 없음 = 전체 누적,
    BACKEND_DECISIONS.md D2). cursor_end는 데이터축 최신일(max ts) — 벽시계 아님(§1).
    """
    cursor = store.get_cursor()
    if cursor is None:
        epoch = datetime.date.fromisoformat(DATA_EPOCH)
        cursor = (epoch - datetime.timedelta(days=1)).isoformat()

    con = sqlite3.connect(fab_db_path())
    try:
        row = con.execute("SELECT MAX(date(ts_out)) FROM lot_history").fetchone()
    finally:
        con.close()
    cursor_end = row[0] or DATA_EPOCH
    return cursor, cursor_end


def launch_batch(batch_id: str, kg_client: KGClient, mcp: MCPClient) -> None:
    """배치 백그라운드 태스크를 띄운다(POST /batches에서 호출, 202 즉시 반환용)."""
    task = asyncio.create_task(run_batch(batch_id, kg_client, mcp))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)


async def run_batch(batch_id: str, kg_client: KGClient, mcp: MCPClient) -> None:
    try:
        await _run_batch_inner(batch_id, kg_client, mcp)
    except Exception as exc:  # §2.4: 실행 실패는 200 + status:"failed"로 표현
        store.append_batch_log(
            batch_id,
            {"time": _now_hms(), "tool": "pipeline", "message": str(exc), "status": "error"},
        )
        store.fail_batch(batch_id, f"배치 실행 실패 — {exc}")


async def _run_batch_inner(batch_id: str, kg_client: KGClient, mcp: MCPClient) -> None:
    cursor_date, cursor_end = _cursor_range()

    logging_mcp = LoggingMCP(mcp, batch_id)
    graph = build_graph(kg_client, logging_mcp, batch_id=batch_id)

    state: dict = {
        "cursor_date": cursor_date,
        "cursor_end": cursor_end,
        "target_lot_ids": [],
        "cnn_results": [],
        "groups": [],
        "graphrag_candidates": {},
        "hypotheses": {},
        "critic_result": {},
        "final_response": {},
    }

    # astream(subgraphs=True): 바깥 노드뿐 아니라 그룹 서브그래프(④~⑦) 안쪽 노드 완료도
    # (namespace, update)로 받는다(§8.2). 안쪽 신호는 진행 표시 전용(process_stream_item이
    # delta=None), 바깥 신호만 결과 누적. current_step은 완료 노드의 인덱스로 단조 증가한다.
    # (observe_groups=인덱스3 매핑은 #33/step7 몫 — 지금은 그 자리가 비어 3을 건너뛴다.)
    current_step = 0
    async for namespace, update in graph.astream(state, stream_mode="updates", subgraphs=True):
        new_step, delta = process_stream_item(namespace, update, current_step)
        if delta:
            state.update(delta)
        if new_step > current_step:
            current_step = new_step
            store.update_batch_step(batch_id, current_step)

    seq = int(batch_id.rsplit("_", 1)[1])
    result_ids = _persist_results(batch_id, seq, state)

    # 웨이퍼 판독 저장(§2.6 원천) — defect_pattern은 API 5종으로 정규화해 저장.
    readings = [
        (r["lot_id"], str(r["wafer_id"]), normalize_pattern(r["pattern"]))
        for r in state.get("cnn_results", [])
    ]
    if readings:
        store.save_wafer_readings(readings)

    store.set_cursor(cursor_end)
    store.finish_batch(batch_id, result_ids)


def _persist_results(batch_id: str, seq: int, state: dict) -> list[str]:
    """그룹별 final_response를 analysis payload로 조립·저장하고 result_ids를 돌려준다.

    같은 정규화 패턴으로 접히는 그룹이 여럿이면(예: 비매핑 결함 여러 종이 전부 Unknown)
    unmapped끼리는 로트를 합쳐 1건으로 저장한다 — analysis_id가 패턴+배치 단위 유니크라
    (§3) 충돌을 피하기 위한 잠정 규칙(BACKEND_DECISIONS.md D4).
    """
    by_pattern: dict[str, dict] = {}
    for final in state.get("final_response", {}).values():
        pattern = normalize_pattern(final["pattern"])
        if pattern in by_pattern and final["status"] == "unmapped":
            merged = by_pattern[pattern]
            merged["lot_ids"] = merged["lot_ids"] + final["lot_ids"]
            merged["lot_count"] = len(merged["lot_ids"])
            continue
        if pattern not in by_pattern:
            by_pattern[pattern] = dict(final)

    result_ids: list[str] = []
    for pattern, final in by_pattern.items():
        analysis_id = f"grp_{pattern_slug(pattern)}_{EVENT_DATE_COMPACT}_{seq:02d}"
        payload = build_analysis_payload(analysis_id, final)
        top_cause = (
            payload["hypotheses"][0]["cause"]
            if payload["status"] == "reviewed" and payload["hypotheses"]
            else None
        )
        store.save_analysis(
            analysis_id=analysis_id,
            batch_id=batch_id,
            seq=seq,
            pattern=payload["pattern"],
            status=payload["status"],
            lot_count=payload["lot_count"],
            top_cause=top_cause,
            payload=payload,
        )
        result_ids.append(analysis_id)
    return result_ids
