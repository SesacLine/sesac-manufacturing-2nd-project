"""POST /batches (§2.3) · GET /batches/{batch_id} (§2.4).

배치는 비동기 접수(202 즉시 반환) 후 batch_runner가 백그라운드로 돌린다.
하루 1회 정책 + 고정 기준일(§1) 때문에 완료 배치가 1건이라도 있으면 이후 요청은 전부 409.
failed 배치는 "완료"가 아니므로 재시도를 허용한다.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, HTTPException

from .. import batch_runner, deps, store
from ..config import compact, event_date_for
from ..schemas import STEPS

router = APIRouter()


@router.post("/batches", status_code=202)
async def create_batch() -> dict:
    if store.find_batch_by_status(["running"]):
        raise HTTPException(status_code=409, detail="이미 진행 중인 배치가 있습니다.")

    # 서버 '오늘'은 커서에서 파생된다(config.event_date_for) — 배치가 끝나 커서가 전진하면
    # 오늘도 하루 앞으로 가고, 그래서 "오늘의 배치"가 없어져 다음 클릭이 통과한다.
    # 하루 1회 정책은 **그 오늘 날짜의 완료 배치**만 막는다(예전엔 완료 배치가 하나라도
    # 있으면 영구 차단이라, 매일 눌러야 하는 서비스인데 실제로는 한 번만 가능했다).
    today = event_date_for(store.get_cursor())
    if store.find_completed_batch_on(compact(today)):
        raise HTTPException(status_code=409, detail=f"{today} 분석이 이미 완료되었습니다.")

    seq = store.next_batch_seq()
    batch_id = f"batch_{compact(today)}_{seq:02d}"
    # 이벤트 시각: 날짜는 서버 기준일(§1), 시·분·초만 실제 실행 시각.
    started_at = f"{today}T{datetime.datetime.now().strftime('%H:%M:%S')}Z"
    try:
        # 시작 시점 커서를 함께 남긴다 — 초기화(POST /batches/reset)가 여기로 되돌린다.
        store.create_batch(batch_id, seq, started_at, cursor_start=store.get_cursor())
        batch_runner.launch_batch(batch_id, deps.kg_client(), deps.mcp_client())
    except Exception:
        raise HTTPException(status_code=500, detail="배치 실행을 시작하지 못했습니다.")
    return {"batch_id": batch_id, "status": "running"}


@router.post("/batches/reset")
def reset_last_batch() -> dict:
    """가장 최근 배치를 통째로 되돌린다 — 시연 중 "방금 그 날짜를 다시 돌려보기"용.

    지우는 것: 그 배치가 만든 analysis 전부 · batch row · 전진했던 커서(시작 지점으로 복원).
    커서가 되돌아가면 서버 '오늘'도 하루 뒤로 가므로, 버튼을 다시 누르면 같은 날짜를
    재분석한다. 진행 중인 배치가 있으면 거절한다(중간 상태를 지우면 결과가 꼬인다).
    """
    if store.find_batch_by_status(["running"]):
        raise HTTPException(status_code=409, detail="진행 중인 배치가 있어 초기화할 수 없습니다.")
    try:
        removed = store.rollback_last_batch()
    except Exception:
        raise HTTPException(status_code=500, detail="초기화에 실패했습니다.")
    if removed is None:
        raise HTTPException(status_code=404, detail="되돌릴 배치가 없습니다.")
    return removed


@router.get("/batches/today")
def get_today() -> dict:
    """서버가 인식하는 '오늘'과 이번 클릭이 처리할 대상 구간 — 화면1 배지·버튼 문구용.

    '오늘'은 커서에서 파생되므로(config.event_date_for) 배치를 한 번 돌릴 때마다 하루씩
    전진한다. 화면1이 이 값을 그대로 찍으면 "일 1회 배치"가 어느 날짜의 배치인지가
    누를 때마다 바뀌어 보인다.

    done=True면 그 날짜 배치가 이미 완료돼 POST /batches가 409를 준다 — 프론트가 클릭
    전에 버튼을 잠그는 데 쓴다(예전엔 눌러서 409를 받아야만 잠겼다).

    ⚠️ 이 라우트는 /batches/{batch_id}보다 **먼저** 등록돼야 한다 — 순서가 바뀌면
    "today"가 batch_id로 잡혀 404가 난다.
    """
    cursor = store.get_cursor()
    today = event_date_for(cursor)
    try:
        start, end = batch_runner.pending_range()
        # start는 배타(그 다음 날부터가 대상)라 하루 밀어 표시한다.
        target_from = (datetime.date.fromisoformat(start) + datetime.timedelta(days=1)).isoformat()
        target_to = end
    except Exception:  # noqa: BLE001 — fab.db 없으면 구간 없이 날짜만 (차트와 같은 폴백)
        target_from = target_to = None
    done = store.find_completed_batch_on(compact(today))
    return {
        "today": today,
        "target_from": target_from,
        "target_to": target_to,
        "done": done is not None,
        "batch_id": done["batch_id"] if done else None,
    }


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
