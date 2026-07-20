"""GET /lots/{lot_id}/wafers (§2.6) · GET /lots/{lot_id}/wafers/{wafer_id}/die-map (§2.6.1).

웨이퍼 목록은 배치 실행 시 저장된 VLM 판독(wafer_reading)에서 조회한다 — "판독 웨이퍼"
목록이므로 배치가 판독한 로트만 존재 취급한다(미판독 lot_id는 404).
die-map은 MCP get_wafer_map이 렌더한 base64 PNG를 디코드해 image/png로 재서빙만 한다
(§2.6 "신규 렌더링 로직 0").
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, HTTPException, Response

from .. import deps, store

router = APIRouter()


@router.get("/lots/{lot_id}/wafers")
def get_lot_wafers(lot_id: str) -> dict:
    try:
        readings = store.get_wafer_readings(lot_id)
    except Exception:
        raise HTTPException(status_code=500, detail="웨이퍼 목록을 불러오지 못했습니다.")
    if not readings:
        raise HTTPException(status_code=404, detail=f"'{lot_id}' 로트를 찾을 수 없습니다.")

    wafers = [
        {
            "wafer_id": r["wafer_id"],
            "defect_pattern": r["defect_pattern"],
            # §2.6: Base URL 성분(/api/v1) 없는 경로 — 절대 URL 조립은 프론트 몫.
            "die_map_url": f"/lots/{lot_id}/wafers/{r['wafer_id']}/die-map",
        }
        for r in readings  # store가 이미 wafer_id 정수 오름차순으로 정렬해 준다
    ]
    defect_count = sum(1 for w in wafers if w["defect_pattern"] != "Normal")
    return {
        "lot_id": lot_id,
        "wafer_count": len(wafers),
        "defect_count": defect_count,
        "normal_count": len(wafers) - defect_count,
        "wafers": wafers,
    }


@router.get("/lots/{lot_id}/wafers/{wafer_id}/die-map")
async def get_die_map(lot_id: str, wafer_id: str) -> Response:
    try:
        result = await deps.mcp_client().get_wafer_map(lot_id, wafer_id)
    except Exception:
        raise HTTPException(status_code=500, detail="웨이퍼 이미지를 불러오지 못했습니다.")
    data = result.get("data")
    if not data or not data.get("image_png_base64"):
        raise HTTPException(
            status_code=404,
            detail=f"{lot_id} 로트에 {wafer_id}번 웨이퍼의 die map 이미지가 없습니다.",
        )
    try:
        png = base64.b64decode(data["image_png_base64"])
    except Exception:
        raise HTTPException(status_code=500, detail="웨이퍼 이미지를 불러오지 못했습니다.")
    return Response(content=png, media_type="image/png")
