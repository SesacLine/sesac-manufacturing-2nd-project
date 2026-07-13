"""변화점 시각 목록 + 인접 이벤트(PM/recipe 변경/알람) 정렬"""
import numpy as np, ruptures as rpt
from server.schemas import respond
from server.db import query

def register(mcp):
    @mcp.tool()
    def detect_change_points(metric: str, scope: str,
                             time_range: tuple[str, str]) -> dict:
        """수율/파라미터 변화점 + 인접 이벤트 정렬. 원인은 추론하지 않는다."""
        rows = query("SELECT ts, value FROM metric_series "
                     "WHERE metric=? AND scope=? AND ts BETWEEN ? AND ? ORDER BY ts",
                     (metric, scope, *time_range))
        ts = [r["ts"] for r in rows]
        vals = np.array([r["value"] for r in rows], dtype=float)
        if len(vals) < 10:
            return respond({"change_points": []},
                           missing=[f"{scope}/{metric} 데이터 부족"])
        idx = rpt.Pelt(model="rbf").fit(vals).predict(pen=10)[:-1]
        cps = []
        for i in idx:
            cp_ts = ts[i]
            nearby = query(  # ±1일 이내 이벤트 정렬
                "SELECT ts, kind, detail FROM event_log "
                "WHERE scope=? AND ABS(julianday(ts)-julianday(?))<=1 ORDER BY ts",
                (scope, cp_ts))
            cps.append({"ts": cp_ts, "nearby_events": [dict(r) for r in nearby]})
        return respond({"metric": metric, "scope": scope, "change_points": cps},
                       queried=str(time_range))