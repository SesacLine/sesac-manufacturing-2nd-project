"""T3: run_commonality_analysis (불량 lot 집합의 공통 장비 / chamber / recipe 집계)"""
from collections import Counter
from server.schemas import respond
from server.db import query

def register(mcp):
    @mcp.tool()
    def run_commonality_analysis(lot_ids: list[str], step: str | None = None) -> dict:
        """불량 lot들의 공통 장비/chamber/recipe 집계 ('몰림' 판단은 Hypo Agent의 단일 책임)"""
        n = len(lot_ids)
        counters = {"equipment_id": Counter(), "chamber": Counter(), "recipe_id": Counter()}
        for lot in lot_ids:
            sql = ("SELECT DISTINCT equipment_id, chamber, recipe_id "
                   "FROM lot_history WHERE lot_id=?" + (" AND step=?" if step else ""))
            args = (lot, step) if step else (lot,)
            for r in query(sql, args):
                for k in counters:
                    if r[k] is not None:
                        counters[k][r[k]] += 1
        data = {dim: [{"value": v, "lot_count": c, "ratio": round(c / n, 3)}
                      for v, c in cnt.most_common()]
                for dim, cnt in counters.items()}
        return respond({"n_lots": n, "step": step, "commonality": data})