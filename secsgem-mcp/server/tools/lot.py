"""T2: get_lot_history (lot의 공정 step별 장비 / chamber / recipe / 입출 시각)"""
from server.schemas import respond
from server.db import query

def register(mcp):
    @mcp.tool()
    def get_lot_history(lot_id: str) -> dict:
        """lot의 공정 step별 처리 이력 (모든 인스턴스 추적의 시작점)"""
        rows = query(
            "SELECT step, equipment_id, chamber, recipe_id, ts_in, ts_out "
            "FROM lot_history WHERE lot_id=? ORDER BY ts_in", (lot_id,))
        return respond([dict(r) for r in rows],
                       missing=[] if rows else [f"{lot_id} 이력 없음"])