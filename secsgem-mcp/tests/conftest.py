"""M3 서버 테스트 공용 fixture — in-process FastMCP 클라이언트.

data 마커 테스트 전용: fab.db가 있어야 함 (python -m simulator.generate 선행).
"""
import asyncio
import json

import pytest


class _SyncClient:
    """async fastmcp Client를 pytest에서 동기로 쓰기 위한 래퍼."""

    def call(self, tool: str, **kwargs) -> dict:
        from fastmcp import Client
        from server.main import mcp

        async def _go():
            async with Client(mcp) as c:
                r = await c.call_tool(tool, kwargs)
                return json.loads(r.content[0].text)
        return asyncio.run(_go())


@pytest.fixture(scope="session")
def client():
    return _SyncClient()


@pytest.fixture(scope="session")
def sample_wafer():
    """이미지가 저장된(시나리오) lot 하나 — 존재가 보장된 조회 키."""
    from server.db import query
    r = query("SELECT lot_id, wafer_id FROM wafer "
              "WHERE die_map IS NOT NULL LIMIT 1")
    assert r, "fab.db에 시나리오 웨이퍼 없음 — simulator.generate 먼저 실행"
    return dict(r[0])


@pytest.fixture(scope="session")
def all_tool_responses(client, sample_wafer):
    """9종 툴을 대표 인자로 1회씩 호출한 응답 목록 (P5 검사용)."""
    lot, wid = sample_wafer["lot_id"], sample_wafer["wafer_id"]
    tr = ("2026-01-01", "2026-04-01")
    from server.db import query
    eq = query("SELECT equipment_id FROM lot_history WHERE lot_id=? LIMIT 1",
               (lot,))[0]["equipment_id"]
    calls = [
        ("get_wafer_map", dict(lot_id=lot, wafer_id=wid)),
        ("get_lot_history", dict(lot_id=lot)),
        ("run_commonality_analysis", dict(lot_ids=[lot])),
        ("get_normal_lot_ratio", dict(equipment_id=eq, time_range=tr)),
        ("query_telemetry", dict(equipment_id=eq, time_range=tr)),
        ("get_alarm_history", dict(equipment_id=eq, time_range=tr)),
        ("get_maintenance_history", dict(equipment_id=eq, time_range=tr)),
        ("detect_change_points", dict(metric="yield", scope=eq, time_range=tr)),
        ("get_lot_timeline", dict(lot_id=lot)),
    ]
    return [client.call(name, **kw) for name, kw in calls]
