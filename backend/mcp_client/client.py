"""secsgem-mcp 서버(9종 도구)에 대한 얇은 클라이언트.

도구 계약(인자/반환 스키마)은 secsgem-mcp/README.md와 server/schemas.py가 정본이다.
연결은 langchain_mcp_adapters.MultiServerMCPClient로 stdio 서버를 붙이는 방식을
README가 이미 예시로 제공한다.

stdio 서버라 미리 띄워둘 필요 없다(README §5) — 첫 도구 호출 시점에 지연 연결한다.
연결 정보는 MCP_SERVER_CWD/MCP_SERVER_PYTHONPATH/FAB_DB 환경변수로 받는다(.env_example 참고).

실측(2026-07-13): `MultiServerMCPClient.get_tools()`는 라이브러리 자체 docstring에
"A new session will be created for each tool call"이라고 명시돼 있다 — 편의 API라
호출마다 stdio 서브프로세스를 새로 띄운다. 가설 하나 검증하는 데도 MCP를 여러 번
부르는 우리 사용 패턴(hypothesis.py)에서는 이게 곧 호출마다 프로세스 재기동이라
치명적으로 느리다(실제로 Center 244건 처리가 타임아웃 남). 그래서 `session()`으로
연결을 한 번만 열고 `load_mcp_tools(session, ...)`로 그 세션에 물린 도구를 재사용한다.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools


def _server_config() -> dict:
    """MultiServerMCPClient에 넘길 stdio 서버 설정을 환경변수로부터 조립한다.

    secsgem-mcp는 SesacLine_SemiRCA 밑의 평범한 하위 폴더다. 그래도 어느 디렉터리에서
    uvicorn을 띄우든 subprocess가 올바른 위치에서 `-m server.main`을 실행하도록 cwd를
    항상 절대경로로 고정한다(상대경로를 그대로 넘기면 호출한 쪽의 cwd에 따라 깨진다).

    command는 PATH 위의 "python"이 아니라 지금 실행 중인 인터프리터(`sys.executable`)를
    그대로 쓴다 — PATH에 다른 파이썬(가상환경이 아닌 시스템 파이썬 등)이 먼저 잡히면
    subprocess가 fastmcp 등 이 프로젝트 의존성이 없는 인터프리터로 뜬다.
    env도 통째로 갈아끼우지 않고 부모 프로세스 환경을 이어받은 채로 PYTHONPATH/FAB_DB만
    덧붙인다 — env를 완전히 새로 주면 Windows에서는 SystemRoot 등 기본 환경변수가
    빠져 subprocess 실행 자체가 불안정해질 수 있다.
    """
    cwd = Path(os.environ["MCP_SERVER_CWD"]).resolve()
    pythonpath = Path(os.environ.get("MCP_SERVER_PYTHONPATH", str(cwd))).resolve()
    fab_db = Path(os.environ["FAB_DB"]).resolve()
    return {
        "secsgem": {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-m", "server.main"],
            "cwd": str(cwd),
            "env": {**os.environ, "PYTHONPATH": str(pythonpath), "FAB_DB": str(fab_db)},
        }
    }


def _as_dict(result: Any) -> dict:
    """MCP 툴 반환값을 dict로 정규화한다.

    실측(2026-07-13): 우리 서버(FastMCP)는 구조화 출력(structuredContent)을 안 쓰고
    있어서, langchain_mcp_adapters가 MCP 표준 콘텐츠 블록 리스트를 그대로 돌려준다 —
    `[{"type": "text", "text": "<json 문자열>"}]`. 텍스트 블록의 JSON을 파싱한 게
    schemas.py의 ToolResponse(`{"data": ..., "meta": {...}}`)다. dict/문자열로 오는
    경우(구조화 출력을 켜거나 어댑터 버전이 바뀔 때 대비)도 방어적으로 받는다.
    """
    if isinstance(result, list):
        texts = [
            item["text"] for item in result
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        if not texts:
            raise TypeError(f"MCP 콘텐츠 블록에서 텍스트를 찾지 못함: {result!r}")
        return json.loads(texts[0])
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        return json.loads(result)
    raise TypeError(f"예상치 못한 MCP 반환 타입: {type(result)!r}")


class MCPClient:
    """9종 도구를 메서드로 노출하는 래퍼. 연결은 지연 생성하되, 한 번 열면 재사용한다."""

    def __init__(self) -> None:
        self._client = MultiServerMCPClient(_server_config())
        self._exit_stack: AsyncExitStack | None = None
        self._tools: dict[str, Any] | None = None

    async def _tool(self, name: str) -> Any:
        if self._tools is None:
            self._exit_stack = AsyncExitStack()
            session = await self._exit_stack.enter_async_context(self._client.session("secsgem"))
            tools = await load_mcp_tools(session)
            self._tools = {t.name: t for t in tools}
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(
                f"MCP 서버가 '{name}' 도구를 노출하지 않는다. "
                f"연결된 도구: {sorted(self._tools)}"
            ) from None

    async def _call(self, name: str, **kwargs: Any) -> dict:
        tool = await self._tool(name)
        result = await tool.ainvoke(kwargs)
        return _as_dict(result)

    async def aclose(self) -> None:
        """열린 세션(서브프로세스)을 정리한다. 배치 1회 실행이 끝나면 호출할 것."""
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
            self._exit_stack = None
            self._tools = None

    async def get_wafer_map(self, lot_id: str, wafer_id: str) -> dict:
        return await self._call("get_wafer_map", lot_id=lot_id, wafer_id=wafer_id)

    async def get_lot_history(self, lot_id: str) -> dict:
        return await self._call("get_lot_history", lot_id=lot_id)

    async def run_commonality_analysis(
        self, lot_ids: list[str], step: str | None = None
    ) -> dict:
        """모든 candidate에 공통으로 호출 — tier 무관."""
        return await self._call("run_commonality_analysis", lot_ids=lot_ids, step=step)

    async def get_normal_lot_ratio(
        self,
        equipment_id: str | None = None,
        chamber_id: str | None = None,
        time_range: tuple[str, str] | None = None,
    ) -> dict:
        """모든 candidate에 공통으로 호출 — tier 무관. 반대 증거."""
        return await self._call(
            "get_normal_lot_ratio",
            equipment_id=equipment_id,
            chamber_id=chamber_id,
            time_range=time_range,
        )

    async def query_telemetry(
        self,
        equipment_id: str,
        time_range: tuple[str, str],
        params: list[str] | None = None,
        max_points: int = 500,
    ) -> dict:
        """candidate.tier == '자동'(evidence_label == 'Parameter')일 때만 호출."""
        return await self._call(
            "query_telemetry",
            equipment_id=equipment_id,
            time_range=time_range,
            params=params,
            max_points=max_points,
        )

    async def get_alarm_history(
        self,
        equipment_id: str | None = None,
        lot_id: str | None = None,
        time_range: tuple[str, str] | None = None,
    ) -> dict:
        return await self._call(
            "get_alarm_history", equipment_id=equipment_id, lot_id=lot_id, time_range=time_range
        )

    async def get_maintenance_history(
        self, equipment_id: str, time_range: tuple[str, str]
    ) -> dict:
        """candidate.evidence_label == 'Maintenance'일 때만 호출."""
        return await self._call(
            "get_maintenance_history", equipment_id=equipment_id, time_range=time_range
        )

    async def detect_change_points(
        self, metric: str, scope: str, time_range: tuple[str, str]
    ) -> dict:
        return await self._call(
            "detect_change_points", metric=metric, scope=scope, time_range=time_range
        )

    async def get_lot_timeline(self, lot_id: str) -> dict:
        """Critic 노드의 시간 정합성 검사에 사용."""
        return await self._call("get_lot_timeline", lot_id=lot_id)
