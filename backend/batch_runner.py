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
import collections
import contextlib
import datetime
import inspect
import logging
import sqlite3
from typing import Any

from . import deps, store
from .assembler import build_analysis_payload, compute_yield_impact
from .config import DATA_EPOCH, compact, event_date_for, fab_db_path
from .graph import _CURRENT_GROUP, build_graph
from .graph_client import KGClient
from .mcp_client import MCPClient
# ⑦ 노드를 타지 않는 normal_reading(#69)도 같은 조치 템플릿을 쓴다(문구 단일 소스).
from .nodes.response import group_actions
from .schemas import NODE_TO_STEP_INDEX, normalize_pattern, pattern_slug

logger = logging.getLogger(__name__)

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


def _batch_date(batch_id: str) -> str:
    """analysis_id 채번용 날짜 — batch_id("batch_20260206_01")에 이미 박힌 값을 그대로 쓴다.

    서버 '오늘'이 커서를 따라 움직이므로(config.event_date_for) 모듈 상수를 쓰면 배치마다
    같은 날짜가 붙어 analysis_id가 충돌한다. 배치가 접수될 때 확정된 날짜를 재사용하는 것이
    안전하다 — 배치 실행 중 커서가 전진해도 그 배치의 결과 id는 흔들리지 않는다.
    """
    parts = batch_id.split("_")
    # 8자리 숫자(YYYYMMDD)일 때만 날짜로 인정한다 — 형식이 다른 batch_id(테스트 픽스처 등)에서
    # 엉뚱한 조각을 날짜로 집어 "grp_normal_normal_01" 같은 id가 나오지 않게.
    if len(parts) >= 3 and len(parts[1]) == 8 and parts[1].isdigit():
        return parts[1]
    return compact(event_date_for(store.get_cursor()))


def _cursor_range() -> tuple[str, str]:
    """(cursor_date exclusive, cursor_end inclusive) — §2.3 누적 스코프.

    첫 배치는 데이터축 처음(EPOCH)부터 전부 본다(직전 배치 없음 = 전체 누적,
    BACKEND_DECISIONS.md D2).

    cursor_end는 **서버 '오늘'의 전날**과 데이터축 최신일 중 이른 쪽이다 — 둘 다 데이터축
    값이라 벽시계는 여전히 안 쓴다(§1). 그 '오늘'은 커서에서 파생되므로(config.event_date_for)
    배치를 돌릴 때마다 대상이 하루씩 앞으로 간다: 커서 2/4 → 2/5 분석 → 커서 2/5 → 다음
    클릭은 2/6 분석. 버튼을 반복해서 눌러도 매번 다음 날 하루치만 처리된다.

    첫 배치(커서 없음)만 예외로 EPOCH부터 env EVENT_DATE의 전날까지를 한 번에 따라잡는다
    (BACKEND_DECISIONS.md D2 누적 스코프).
    """
    cursor = store.get_cursor()
    start = cursor
    if start is None:
        epoch = datetime.date.fromisoformat(DATA_EPOCH)
        start = (epoch - datetime.timedelta(days=1)).isoformat()

    con = sqlite3.connect(fab_db_path())
    try:
        row = con.execute("SELECT MAX(date(ts_out)) FROM lot_history").fetchone()
    finally:
        con.close()
    data_max = row[0] or DATA_EPOCH
    yesterday = (
        datetime.date.fromisoformat(event_date_for(cursor)) - datetime.timedelta(days=1)
    ).isoformat()
    return start, min(data_max, yesterday)   # ISO 날짜라 문자열 비교로 충분


def pending_range() -> tuple[str, str]:
    """다음 클릭이 처리할 구간 — GET /batches/today가 실행 전에 미리 보여주는 데 쓴다.

    배치를 돌리지 않고 계산만 하므로 부작용이 없다(커서도 건드리지 않는다).
    """
    return _cursor_range()


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
    finally:
        # run_batch는 create_task로 뜬 장수 백그라운드 코루틴이라 프로세스 종료 훅에 안 걸린다.
        # 배치가 끝날 때(성공/실패 무관) 잔여 트레이스를 강제 전송해 마지막 트레이스 유실을 막는다.
        # shutdown()이 아니라 flush() — 서버는 계속 살아 다음 배치도 트레이싱해야 하므로 안 닫는다.
        if deps.langfuse_handler() is not None:   # 트레이싱 off면 get_client() 초기화도 건드리지 않는다
            try:
                from langfuse import get_client
                # flush()는 동기 blocking(큐가 빌 때까지 호출 스레드를 막음)이다. run_batch는
                # 이벤트 루프 위 코루틴이라 직접 부르면 flush 동안 루프 전체가 멈춘다 —
                # export timeout을 60초로 올린 뒤(U9)엔 엔드포인트가 죽었을 때 최악 60초까지
                # 다른 요청(배치 상태 폴링·/health 등)을 얼린다. 워커 스레드로 옮겨 루프를 살린다.
                await asyncio.to_thread(get_client().flush)
            except Exception:   # noqa: BLE001 — flush 실패가 배치 결과를 삼키면 안 됨
                logger.warning("Langfuse flush 실패(무시)")


async def _run_batch_inner(batch_id: str, kg_client: KGClient, mcp: MCPClient) -> None:
    cursor_date, cursor_end = _cursor_range()

    logging_mcp = LoggingMCP(mcp, batch_id)
    # ⑦ description 영어→한국어 번역기 주입(RESPONSE_LLM=1일 때만 실체, 아니면 None=원문 운반).
    graph = build_graph(kg_client, logging_mcp, batch_id=batch_id, translate=deps.response_translator())

    # Langfuse 트레이싱(LANGFUSE_TRACING=1일 때만 실체, 아니면 None). 콜백은 LLM 노드를
    # 자동 캡처(모델명·토큰·비용·input/output)하고 비-LLM 노드도 span으로 잡는다.
    # config=None은 LangGraph에서 무해(no-op)라 트레이싱 꺼진 경로는 기존과 동일하다.
    handler = deps.langfuse_handler()
    run_config = {"callbacks": [handler]} if handler is not None else None

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
    #
    # 트레이스 속성(name·session·tags)은 config metadata의 langfuse_* 키로는 LangGraph
    # subgraphs 구조에서 트레이스 레벨에 안 붙었다(Step 7 실측 — 일반 metadata는 관측치에
    # 전파되나 langfuse_session_id/tags는 소비만 되고 트레이스에 미적용). 그래서 v4 권장대로
    # 루트 span + propagate_attributes로 감싼다:
    #   - start_as_current_observation(name="rca-batch"): 이 활성 span 컨텍스트에 astream이
    #     만드는 LangGraph 체인·generation·agent span이 attach돼 한 트레이스로 묶인다(Step 7
    #     실측 — 이 래퍼를 빼면 콜백 span들이 트레이스에서 유실됨). 래퍼 span 자체는 트레이스에
    #     관측치로 안 남지만 그룹핑 앵커 역할을 한다.
    #   - propagate_attributes: baggage로 트레이스 레벨에 trace_name(빈 이름 해소)·
    #     session=batch_id(배치 1회=세션 1개)·tags=["rca-batch"]를 실제 부착(Step 7 실측).
    # 트레이싱 off/실패해도 배치에 영향 없도록 try/except + ExitStack로 격리(원칙 #2).
    current_step = 0
    with contextlib.ExitStack() as stack:
        if handler is not None:
            try:
                from langfuse import get_client, propagate_attributes
                stack.enter_context(
                    get_client().start_as_current_observation(as_type="span", name="rca-batch")
                )
                stack.enter_context(
                    propagate_attributes(
                        trace_name="rca-batch",
                        session_id=batch_id,
                        tags=["rca-batch"],
                        metadata={"cursor_date": cursor_date, "cursor_end": cursor_end},
                    )
                )
            except Exception:  # noqa: BLE001 — 옵저버빌리티 실패가 배치를 죽이면 안 됨
                logger.warning("Langfuse 트레이스 속성 설정 실패(무시)")
        async for namespace, update in graph.astream(
            state, stream_mode="updates", subgraphs=True, config=run_config
        ):
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


def _defect_date(lot_ids: list[str]) -> str | None:
    """그룹 로트들의 결함 발생일(데이터축) — EDS 통과일 최댓값. §2.8 이벤트 오버레이의 x좌표.

    벽시계가 아니라 fab.db lot_history에서 읽는다(§1 시각 규약). fab.db가 없으면 None(곱게 무너짐).
    """
    if not lot_ids:
        return None
    try:
        con = sqlite3.connect(fab_db_path())
        try:
            placeholders = ",".join("?" * len(lot_ids))
            row = con.execute(
                f"SELECT MAX(date(ts_out)) FROM lot_history "
                f"WHERE step = 'EDS' AND lot_id IN ({placeholders})",
                lot_ids,
            ).fetchone()
        finally:
            con.close()
        return row[0]
    except Exception:  # noqa: BLE001 — fab.db 부재/오류 시 이벤트 날짜만 비운다
        return None


def _persist_results(batch_id: str, seq: int, state: dict) -> list[str]:
    """그룹별 final_response를 analysis payload로 조립·저장하고 result_ids를 돌려준다.

    같은 정규화 패턴으로 접히는 그룹이 여럿이면(예: 비매핑 결함 여러 종이 전부 Unknown)
    unmapped/novel끼리는 로트를 합쳐 1건으로 저장한다 — analysis_id가 패턴+배치 단위 유니크라
    (§3) 충돌을 피하기 위한 잠정 규칙(BACKEND_DECISIONS.md D4).

    v1.1: yield_impact(⓪ lot_yields 기반)·defect_date(EDS 최종일)·top 필드(장비/공정/등급)·
    confidence를 함께 저장한다 — §2.2 목록·§2.8/§2.9 차트의 원천.
    """
    # 같은 패턴이 여러 건 남을 수 있다: ② grouper의 시간 서브클러스터링으로 사건이 갈린 경우
    # (같은 Center라도 1월 사건 / 3월 사건). unmapped·novel만 종전대로 1건으로 접고(D4),
    # 그 외(reviewed·insufficient)는 각각 별도 분석으로 남긴다 — 접으면 사건 하나가 통째로
    # 사라진다(옛 코드는 조용히 덮어써 유실됐다).
    kept: list[tuple[str, dict]] = []
    folded: dict[str, dict] = {}
    for final in state.get("final_response", {}).values():
        pattern = normalize_pattern(final["pattern"])
        if final["status"] in ("unmapped", "novel"):
            if pattern in folded:
                merged = folded[pattern]
                merged["lot_ids"] = merged["lot_ids"] + final["lot_ids"]
                merged["lot_count"] = len(merged["lot_ids"])
                continue
            folded[pattern] = dict(final)
            kept.append((pattern, folded[pattern]))
        else:
            kept.append((pattern, dict(final)))

    lot_yields = state.get("lot_yields") or {}
    result_ids: list[str] = []
    # 같은 패턴이 여럿이면 analysis_id 뒤에 순번을 붙여 충돌을 막는다(§3 유니크 계약 유지).
    seen_pattern: collections.Counter = collections.Counter()
    for pattern, final in kept:
        seen_pattern[pattern] += 1
        nth = seen_pattern[pattern]
        dup = "" if nth == 1 else f"_{nth}"
        analysis_id = f"grp_{pattern_slug(pattern)}_{_batch_date(batch_id)}_{seq:02d}{dup}"
        # 수율영향은 병합(unmapped/novel) 확정 뒤의 최종 lot_ids로 계산해 payload에 주입한다.
        final["yield_impact"] = compute_yield_impact(final["lot_ids"], lot_yields)
        payload = build_analysis_payload(analysis_id, final)
        top_cause = (
            payload["hypotheses"][0]["cause"]
            if payload["status"] == "reviewed" and payload["hypotheses"]
            else None
        )
        # top 가설의 장비/공정/등급 — 차트(§2.8/§2.9) 집계용 비정규화 캐시.
        # equipment는 §2.5 카드에 없는 내부 필드라 노드 출력(final.hypotheses[0])에서 읽는다.
        top_node = (final.get("hypotheses") or [{}])[0] if top_cause else {}
        top_card = payload["hypotheses"][0] if top_cause else {}
        store.save_analysis(
            analysis_id=analysis_id,
            batch_id=batch_id,
            seq=seq,
            pattern=payload["pattern"],
            status=payload["status"],
            lot_count=payload["lot_count"],
            top_cause=top_cause,
            payload=payload,
            confidence=payload.get("confidence", "low"),
            yield_impact=payload.get("yield_impact"),
            defect_date=_defect_date(final["lot_ids"]),
            top_equipment=top_node.get("equipment"),
            top_stage=top_card.get("stage"),
            top_tier=top_card.get("tier"),
        )
        result_ids.append(analysis_id)

    result_ids.extend(_persist_normal_reading(batch_id, seq, state, lot_yields))
    return result_ids


def _persist_normal_reading(
    batch_id: str, seq: int, state: dict, lot_yields: dict[str, float]
) -> list[str]:
    """판독상 정상 로트(#69 (b)안)를 analysis 1건으로 합성·저장한다.

    ② grouper가 Normal 다수결 로트를 그룹으로 만들지 않으므로(기획 §6.1) 이 로트들은 그룹
    서브그래프(④~⑦)를 타지 않는다 — final_response가 없어 여기서 카드를 직접 만든다.
    "저수율인데 웨이퍼맵상 정상"은 맵에 안 보이는 수율손실(파라메트릭/EDS 계열) 의심이라
    조사 대상이다. 조용히 버리면 이 신호가 UI에서 사라지므로 전용 status로 노출한다
    (unmapped 재사용 금지 — v2.0에서 unmapped는 "기지 패턴 + 지식 공백"으로 재정의됨).
    """
    normal_lots = state.get("normal_lots") or []
    if not normal_lots:
        return []

    # ② grouper의 결함일 단위 분할을 여기에도 적용한다 — Normal은 그룹을 안 만들어
    # split_by_day를 안 거치므로, 캐치업 배치에서 2주치가 한 카드로 뭉치는 일이 있었다
    # (실측 2026-07-27: 1/19~2/2 4로트 1건). 정상 운영(하루 창)에서는 나올 수 없는 카드라
    # 결함일별로 나눠 "그날 눌렀다면 나왔을 결과"와 같게 만든다.
    result_ids: list[str] = []
    for nth, (day, lots) in enumerate(
        sorted(_group_lots_by_defect_day(state, normal_lots).items()), start=1
    ):
        dup = "" if nth == 1 else f"_{nth}"
        analysis_id = f"grp_normal_{_batch_date(batch_id)}_{seq:02d}{dup}"
        final = {
            "pattern": "Normal",
            "status": "normal_reading",
            "reason": (
                "저수율이지만 웨이퍼맵 판독상 결함 패턴이 없습니다 — 맵에 보이지 않는 "
                "수율손실(파라메트릭 등) 의심. 웨이퍼맵 RCA 범위 밖이므로 별도 조사가 필요합니다."
            ),
            "lot_ids": lots,
            "lot_count": len(lots),
            "hypotheses": [],
            # 채택 원인이 없으므로 확신은 항상 low(R1 규약).
            "confidence": "low",
            # 판독은 정상이어도 저수율 로트라 수율영향은 정상적으로 음수가 나온다.
            "yield_impact": compute_yield_impact(lots, lot_yields),
            "actions": group_actions("normal_reading", "Normal", len(lots), None),
        }
        payload = build_analysis_payload(analysis_id, final)
        store.save_analysis(
            analysis_id=analysis_id,
            batch_id=batch_id,
            seq=seq,
            pattern=payload["pattern"],
            status=payload["status"],
            lot_count=payload["lot_count"],
            top_cause=None,
            payload=payload,
            confidence=payload["confidence"],
            yield_impact=payload["yield_impact"],
            defect_date=day or _defect_date(lots),
        )
        result_ids.append(analysis_id)
    return result_ids


def _group_lots_by_defect_day(state: dict, lots: list[str]) -> dict[str, list[str]]:
    """로트를 결함 확정일별로 묶는다. 날짜 미상은 빈 키("")로 한 덩어리."""
    defect_ts = state.get("lot_defect_ts") or {}
    by_day: dict[str, list[str]] = {}
    for lot in lots:
        by_day.setdefault((defect_ts.get(lot) or "")[:10], []).append(lot)
    return by_day
