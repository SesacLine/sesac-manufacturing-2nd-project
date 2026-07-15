"""T5: query_telemetry (S6F11 장비 파라미터 시계열 + 정상 범위)"""
import math
from datetime import datetime

from server.schemas import respond
from server.db import query
from simulator.fab_model import normal_range   # fab_model.yaml 로더

MAX_POINTS = 500   # 컨텍스트 폭주 방지


def downsample(rows, max_points):
    """균일 간격 다운샘플 — step을 올림으로 잡아 반환 개수가 max_points를 절대 넘지 않는다.
    (내림 나눗셈은 501~999 구간에서 step=1이 되어 상한을 깨뜨린다.)"""
    if len(rows) <= max_points:
        return rows
    return rows[::math.ceil(len(rows) / max_points)]


def _gaps(rows, equipment_id):
    """관측 결측 창 감지 — 타임스탬프 간격이 중앙값의 2.5배를 넘는 구간을 missing으로.
    P4: 결측 구간에 대해 '이상 없음'을 주장하지 않도록 coverage로 명시한다."""
    stamps = sorted({r["ts"] for r in rows})
    times = [datetime.strptime(s, "%Y-%m-%d %H:%M:%S") for s in stamps]
    deltas = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
    if not deltas:
        return []
    med = sorted(deltas)[len(deltas) // 2]
    return [f"{equipment_id} 텔레메트리 결측: {a} ~ {b}"
            for a, b, d in zip(stamps, stamps[1:], deltas) if d > 2.5 * med]

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
        downsampled = downsample(rows, max_points)  # 균일 다운샘플링 (상한 보장)
        return respond({
            "equipment_id": equipment_id,
            "series": downsampled,
            "normal_ranges": {p: normal_range(equipment_id, p) for p in (params or [])},
            "downsampled": len(rows) > max_points,
            "n_raw": len(rows), "n_returned": len(downsampled),
        }, queried=str(time_range),
           missing=_gaps(rows, equipment_id) if rows
                   else [f"{equipment_id} 텔레메트리 없음: {time_range}"])