from server.schemas import respond
from server.db import query

def register(mcp):
    @mcp.tool()
    def get_maintenance_history(equipment_id: str,
                                time_range: tuple[str, str] | None = None) -> dict:
        """PM/BM 이력 (ts, type, 교체 부품)."""
        sql = ("SELECT ts, type, parts FROM maintenance WHERE equipment_id=?" +
               (" AND ts BETWEEN ? AND ?" if time_range else "") + " ORDER BY ts")
        rows = [dict(r) for r in query(sql, (equipment_id, *(time_range or ())))]
        return respond(rows, queried=str(time_range) if time_range else None,
                       missing=[] if rows else [f"{equipment_id} 정비 이력 없음"])