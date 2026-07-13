"""FastAPI 진입점.

배치형 트리거 1개가 전부다 — 자유 질의/실시간 스트리밍 없음(산출물_mvp설계서.md §1).
엔지니어가 "오늘 판독 배치 확인" 버튼을 누르면 커서를 전진시키고 ⓪~⑥ 전체를 실행한다.
"""

from __future__ import annotations

import os
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


@app.post("/batch/run")
async def run_daily_batch():
    """오늘 날짜 커서를 전진시키고 ⓪~⑥ 파이프라인을 1회 실행한다.

    TODO: app_state.db의 cursor_state를 읽어 다음 날짜로 전진 -> RCAState 초기값 구성 ->
          _graph.ainvoke(initial_state) -> 결과를 app_state.db의 batch_group_result에 저장 ->
          그대로 응답.
    """
    raise NotImplementedError


@app.get("/batch/results")
async def get_batch_results():
    """대시보드 큐 조회용 — app_state.db의 batch_group_result를 그대로 반환.

    TODO: 구현.
    """
    raise NotImplementedError


@app.get("/health")
async def health():
    return {"status": "ok"}
