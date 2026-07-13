"""FastAPI 진입점.

배치형 트리거 1개가 전부다 — 자유 질의/실시간 스트리밍 없음(산출물_mvp설계서.md §1).
엔지니어가 "오늘 판독 배치 확인" 버튼을 누르면 커서를 전진시키고 ⓪~⑥ 전체를 실행한다.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

from .graph import build_graph
from .graph_client import KGClient
from .mcp_client import MCPClient

load_dotenv()

app = FastAPI(title="SesacLine SemiRCA")

_kg_client = KGClient(hypotheses_path=Path(os.environ["KG_HYPOTHESES_PATH"]))
_mcp_client = MCPClient()
_graph = build_graph(_kg_client, _mcp_client)

# TODO(팀 결정 필요): fab.db 시뮬레이터 데이터 범위(90일, 시드 20260101) 중 첫 배치일을
# 임의로 하드코딩했다 — 실제 커서 시작일 정책은 아직 안 정해짐.
_FIRST_CURSOR_DATE = "2026-03-04"


def _app_state_db() -> sqlite3.Connection:
    con = sqlite3.connect(os.environ.get("APP_STATE_DB", "./app_state.db"))
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE IF NOT EXISTS cursor_state (id INTEGER PRIMARY KEY CHECK (id = 1), cursor_date TEXT NOT NULL)"
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS batch_group_result (
            group_id TEXT PRIMARY KEY, cursor_date TEXT NOT NULL,
            pattern TEXT NOT NULL, result_json TEXT NOT NULL
        )"""
    )
    con.commit()
    return con


def _advance_cursor(con: sqlite3.Connection) -> str:
    row = con.execute("SELECT cursor_date FROM cursor_state WHERE id = 1").fetchone()
    if row is None:
        cursor_date = _FIRST_CURSOR_DATE
        con.execute("INSERT INTO cursor_state (id, cursor_date) VALUES (1, ?)", (cursor_date,))
    else:
        cursor_date = (date.fromisoformat(row["cursor_date"]) + timedelta(days=1)).isoformat()
        con.execute("UPDATE cursor_state SET cursor_date = ? WHERE id = 1", (cursor_date,))
    con.commit()
    return cursor_date


@app.post("/batch/run")
async def run_daily_batch():
    """오늘 날짜 커서를 전진시키고 ⓪~⑥ 파이프라인을 1회 실행한다."""
    con = _app_state_db()
    cursor_date = _advance_cursor(con)

    initial_state = {
        "cursor_date": cursor_date,
        "target_lot_ids": [],
        "vlm_results": [],
        "groups": [],
        "graphrag_candidates": {},
        "hypotheses": {},
        "critic_result": {},
        "final_response": {},
    }
    result = await _graph.ainvoke(initial_state)

    for group_id, group_response in result["final_response"].items():
        con.execute(
            """INSERT OR REPLACE INTO batch_group_result (group_id, cursor_date, pattern, result_json)
               VALUES (?, ?, ?, ?)""",
            (group_id, cursor_date, group_response["pattern"], json.dumps(group_response, ensure_ascii=False)),
        )
    con.commit()
    con.close()

    return {"cursor_date": cursor_date, "groups": list(result["final_response"].keys())}


@app.get("/batch/results")
async def get_batch_results():
    """대시보드 큐 조회용 — app_state.db의 batch_group_result를 그대로 반환."""
    con = _app_state_db()
    rows = con.execute(
        "SELECT group_id, cursor_date, pattern, result_json FROM batch_group_result ORDER BY cursor_date DESC"
    ).fetchall()
    con.close()
    return [
        {
            "group_id": row["group_id"],
            "cursor_date": row["cursor_date"],
            "pattern": row["pattern"],
            **json.loads(row["result_json"]),
        }
        for row in rows
    ]


@app.get("/health")
async def health():
    return {"status": "ok"}
