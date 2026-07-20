"""GET /analyses (§2.2) · GET /analyses/{id} (§2.5) · GET /analyses/{id}/evidence/{hid} (§2.7).

전부 app_state.db 저장분 조회만 한다 — 배치 실행 시 조립·보존된 payload를 꺼내 내려줄 뿐,
온디맨드 재계산(MCP 재호출)은 하지 않는다(§2.7 원칙).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from .. import store

router = APIRouter()


@router.get("/analyses")
def list_analyses(
    sort: Literal["latest", "oldest"] = Query("latest"),
    limit: int = Query(10, ge=1),
    offset: int = Query(0, ge=0),
) -> dict:
    try:
        count, items = store.list_analyses(sort=sort, limit=limit, offset=offset)
    except Exception:
        raise HTTPException(status_code=500, detail="분석 목록을 불러오지 못했습니다.")
    # 필드 존재 계약(§2.2): items[] 5키 항상 존재, top_cause만 Nullable.
    return {"count": count, "items": items}


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: str) -> dict:
    payload = _load_payload(analysis_id)
    # 저장 payload에서 §2.7 전용 evidence 맵만 제외하고 §2.5 키 집합 그대로 반환.
    return {k: v for k, v in payload.items() if k != "evidence"}


@router.get("/analyses/{analysis_id}/evidence/{hypothesis_id}")
def get_evidence(analysis_id: str, hypothesis_id: str) -> dict:
    payload = _load_payload(analysis_id)
    if payload["status"] == "unmapped":
        raise HTTPException(
            status_code=404, detail="이 그룹은 원인 매핑이 없어 근거를 제공하지 않습니다."
        )
    evidence = payload.get("evidence", {}).get(hypothesis_id)
    if evidence is None:
        raise HTTPException(
            status_code=404,
            detail=f"'{analysis_id}' 분석에 '{hypothesis_id}' 가설이 없습니다.",
        )
    return evidence


def _load_payload(analysis_id: str) -> dict:
    try:
        payload = store.get_analysis(analysis_id)
    except Exception:
        raise HTTPException(status_code=500, detail="분석을 불러오지 못했습니다.")
    if payload is None:
        raise HTTPException(status_code=404, detail=f"'{analysis_id}' 분석을 찾을 수 없습니다.")
    return payload
