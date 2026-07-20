"""POST /batches (§2.3) · GET /batches/{batch_id} (§2.4).

배치는 비동기 접수(202 즉시 반환) 후 batch_runner가 백그라운드로 돌린다.
하루 1회 정책 + 고정 기준일(§1) 때문에 완료 배치가 1건이라도 있으면 이후 요청은 전부 409.
failed 배치는 "완료"가 아니므로 재시도를 허용한다.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, HTTPException

from .. import batch_runner, deps, store
from ..config import EVENT_DATE, EVENT_DATE_COMPACT
from ..schemas import STEPS

router = APIRouter()


@router.post("/batches", status_code=202)
async def create_batch() -> dict:
    if store.find_batch_by_status(["running"]):
        raise HTTPException(status_code=409, detail="이미 진행 중인 배치가 있습니다.")
    if store.find_batch_by_status(["completed"]):
        raise HTTPException(status_code=409, detail="기존 완료된 분석이 있습니다.")

    seq = store.next_batch_seq()
    batch_id = f"batch_{EVENT_DATE_COMPACT}_{seq:02d}"
    # 이벤트 시각: 날짜는 고정 기준일(§1), 시·분·초만 실제 실행 시각.
    started_at = f"{EVENT_DATE}T{datetime.datetime.now().strftime('%H:%M:%S')}Z"
    try:
        store.create_batch(batch_id, seq, started_at)
        batch_runner.launch_batch(batch_id, deps.kg_client(), deps.mcp_client())
    except Exception:
        raise HTTPException(status_code=500, detail="배치 실행을 시작하지 못했습니다.")
    return {"batch_id": batch_id, "status": "running"}


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str) -> dict:
    batch = store.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"'{batch_id}' 배치를 찾을 수 없습니다.")
    # 필드 존재 계약(§2.4): status와 무관하게 7키 superset, 해당 없는 값은 null.
    return {
        "batch_id": batch["batch_id"],
        "status": batch["status"],
        "current_step": batch["current_step"],
        "steps": STEPS,
        "logs": batch["logs"],
        "result_ids": batch["result_ids"],
        "error": batch["error"],
    }
