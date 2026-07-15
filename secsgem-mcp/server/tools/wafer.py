"""T1: get_wafer_map (웨이퍼맵 이미지 반환 (라벨 미포함))"""
from server.schemas import respond
from server.db import get_wafer_record
from preprocess.render import to_base64_png

def register(mcp):
    @mcp.tool()
    def get_wafer_map(lot_id: str, wafer_id: str) -> dict:
        """웨이퍼맵 이미지 반환 (라벨 미반환)"""
        rec = get_wafer_record(lot_id, wafer_id)
        if rec is None:
            return respond(None, missing=[f"{lot_id}/{wafer_id} 없음"])
        png_b64, orig_hw = to_base64_png(rec["die_map"])
        return respond({
            "image_png_base64": png_b64,
            "source": rec["source"],
            "original_resolution": orig_hw,
            "die_size": rec.get("die_size"),
        })