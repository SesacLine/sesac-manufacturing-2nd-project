from server.schemas import respond
from server.db import query

def register(mcp):
    @mcp.tool()
    def get_alarm_history(equipment_id: str | None = None, lot_id: str | None = None,
                          time_range: tuple[str, str] | None = None) -> dict:
        """S5F1 알람 목록 (ts, alarm_id, text)."""
        assert equipment_id or lot_id
        col, val = ("equipment_id", equipment_id) if equipment_id else ("lot_id", lot_id)
        sql = (f"SELECT ts, alarm_id, text FROM alarm WHERE {col}=?" +
               (" AND ts BETWEEN ? AND ?" if time_range else "") + " ORDER BY ts")
        rows = [dict(r) for r in query(sql, (val, *(time_range or ())))]
        return respond(rows, queried=str(time_range) if time_range else None,
                       missing=[] if rows else [f"{val} 알람 없음"])