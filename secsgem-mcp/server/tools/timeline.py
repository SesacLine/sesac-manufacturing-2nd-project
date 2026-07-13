from server.schemas import respond
from server.db import query

def register(mcp):
    @mcp.tool()
    def get_lot_timeline(lot_id: str) -> dict:
        """lot 처리 전후 관련 장비 이벤트 통합 타임라인 — 선후관계 판단 보조 (P2)."""
        rows = query(
            "SELECT ts, source_kind, equipment_id, detail FROM ("
            "  SELECT ts_in ts, 'process' source_kind, equipment_id, step detail "
            "    FROM lot_history WHERE lot_id=? "
            "  UNION ALL SELECT ts,'alarm',equipment_id,text FROM alarm WHERE lot_id=? "
            ") ORDER BY ts", (lot_id, lot_id))
        return respond([dict(r) for r in rows],
                       missing=[] if rows else [f"{lot_id} 타임라인 없음"])