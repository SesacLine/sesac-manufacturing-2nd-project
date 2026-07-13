import math

from server.schemas import respond
from server.db import query
from simulator.fab_model import normal_range   # fab_model.yaml 로더

MAX_POINTS = 500   # 컨텍스트 폭주 방지 (§5.2-4)

def downsample(rows: list, max_points: int) -> list:
    """균일 간격 다운샘플 — 반환 개수 ≤ max_points 보장."""
    return rows[::math.ceil(len(rows) / max_points) or 1]

def register(mcp):
    @mcp.tool()
    def query_telemetry(equipment_id: str, time_range: tuple[str, str],
                        params: list[str] | None = None,
                        max_points: int = MAX_POINTS) -> dict:
        """S6F11 시계열 + 정상 범위. 다운샘플링으로 포인트 상한."""
        sql = ("SELECT ts, param, value FROM telemetry "
               "WHERE equipment_id=? AND ts BETWEEN ? AND ?" +
               (f" AND param IN ({','.join('?'*len(params))})" if params else "") +
               " ORDER BY ts")
        args = (equipment_id, *time_range, *(params or []))
        rows = [dict(r) for r in query(sql, args)]
        downsampled = downsample(rows, max_points)
        return respond({
            "equipment_id": equipment_id,
            "series": downsampled,
            "normal_ranges": {p: normal_range(equipment_id, p) for p in (params or [])},
            "downsampled": len(rows) > max_points,
            "n_raw": len(rows), "n_returned": len(downsampled),
        }, queried=str(time_range),
           missing=[] if rows else [f"{equipment_id} 텔레메트리 없음: {time_range}"])