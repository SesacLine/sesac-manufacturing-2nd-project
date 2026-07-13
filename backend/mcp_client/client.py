"""secsgem-mcp 서버(9종 도구)에 대한 얇은 클라이언트.

도구 계약(인자/반환 스키마)은 secsgem-mcp/README.md와 server/schemas.py가 정본이다.
연결은 langchain_mcp_adapters.MultiServerMCPClient로 stdio 서버를 붙이는 방식을
README가 이미 예시로 제공한다.

stdio 서버라 미리 띄워둘 필요 없다(README §5) — 첫 도구 호출 시점에 지연 연결한다.
연결 정보는 MCP_SERVER_CWD/MCP_SERVER_PYTHONPATH/FAB_DB 환경변수로 받는다(.env_example 참고).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient


def _server_config() -> dict:
    """MultiServerMCPClient에 넘길 stdio 서버 설정을 환경변수로부터 조립한다.

    secsgem-mcp는 SesacLine_SemiRCA 밑의 하위 폴더(자체 .git은 유지되는 nested repo)다.
    그래도 어느 디렉터리에서 uvicorn을 띄우든 subprocess가 올바른 위치에서
    `python -m server.main`을 실행하도록 cwd를 항상 절대경로로 고정한다
    (상대경로를 그대로 넘기면 호출한 쪽의 cwd에 따라 깨진다).
    """
    cwd = Path(os.environ["MCP_SERVER_CWD"]).resolve()
    pythonpath = Path(os.environ.get("MCP_SERVER_PYTHONPATH", str(cwd))).resolve()
    fab_db = Path(os.environ["FAB_DB"]).resolve()
    return {
        "secsgem": {
            "transport": "stdio",
            "command": "python",
            "args": ["-m", "server.main"],
            "cwd": str(cwd),
            "env": {"PYTHONPATH": str(pythonpath), "FAB_DB": str(fab_db)},
        }
    }


def _as_dict(result: Any) -> dict:
    """MCP 툴 반환값을 dict로 정규화한다.

    어댑터가 구조화 출력을 지원하면 dict를, 아니면 텍스트 content를 문자열(JSON)로
    돌려준다 — 둘 다 받아들인다. 툴 자체의 반환 스키마는 schemas.py의 ToolResponse
    (`{"data": ..., "meta": {...}}`)이므로, 여기서는 그 바깥 dict만 정규화하고
    data/meta 분리는 호출부(hypothesis.py/critic.py)의 몫으로 남긴다.
    """
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        return json.loads(result)
    raise TypeError(f"예상치 못한 MCP 반환 타입: {type(result)!r}")


class MCPClient:
    """9종 도구를 메서드로 노출하는 래퍼."""

    def __init__(self) -> None:
        self._client = MultiServerMCPClient(_server_config())
        self._tools: dict[str, Any] | None = None

    async def _tool(self, name: str) -> Any:
        if self._tools is None:
            tools = await self._client.get_tools()
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
