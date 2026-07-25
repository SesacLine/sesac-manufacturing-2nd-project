"""차트 데이터 2종 (명세 v1.1 §2.8·§2.9) — 대시보드 확장 차트(와이어프레임 v8)의 원천.

GET /yield-daily   일별 라인 수율 전 구간 + 분석 이벤트 오버레이(급락 지점 툴팁·마커).
GET /stats/causes  장비 구성(도넛)·패턴별 판독 웨이퍼 수(Pareto)·패턴별 채택 원인(칩) 집계.

시각 규약(§1): 날짜는 전부 데이터축(fab.db ts / 분석 defect_date)이다 — 벽시계 안 씀.
§2.7 원칙: 이벤트·집계는 배치 때 저장된 분석 row에서 조회만 한다(재계산 없음).
fab.db가 없으면 days만 빈 배열로 내려간다(이벤트·집계는 app_state.db라 CI에서도 동작).
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException

from .. import store
from ..config import fab_db_path
from ..schemas import MAPPED_PATTERNS

router = APIRouter()


@router.get("/yield-daily")
def get_yield_daily() -> dict:
    """§2.8 — { days: [{date, yield}], events: [{date, analysis_id, pattern, status,
    cause, equipment, stage, tier, confidence}] }.

    days: metric_series(metric='yield') 전 구간의 날짜별 장비 단순평균(0~100, 소수 1자리).
    events: defect_date가 잡힌 분석 전부(§2.7 저장분 조회) — reviewed 외 상태도 이상 이벤트로 내림.
    """
    try:
        events = store.list_analysis_events()
    except Exception:
        raise HTTPException(status_code=500, detail="분석 이벤트를 불러오지 못했습니다.")
    return {"days": _daily_line_yield(), "events": events}


def _daily_line_yield() -> list[dict]:
    """metric_series 전 구간 일별 라인 평균 수율. fab.db 없으면 빈 배열(곱게 무너짐)."""
    try:
        con = sqlite3.connect(fab_db_path())
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                """
                SELECT date(ts) AS d, AVG(value) AS v
                FROM metric_series
                WHERE metric = 'yield'
                GROUP BY date(ts)
                ORDER BY d ASC
                """
            ).fetchall()
        finally:
            con.close()
    except Exception:  # noqa: BLE001 — FAB_DB 미설정/부재 시 차트 라인만 비운다
        return []
    return [{"date": r["d"], "yield": round(r["v"] * 100, 1)} for r in rows]


@router.get("/stats/causes")
def get_cause_stats() -> dict:
    """§2.9 — { equipment: [{equipment_id, stage, count}],
               causes: [{pattern, cause, stage, tier, count}],
               patterns: [{pattern, wafer_count, mapped}] }.

    전부 app_state.db 저장분 집계(조회만). patterns는 CNN 판독 저장분(wafer_reading)이라
    정답 라벨 누출이 없다. mapped = KG 매핑 대상 3종 여부(§3 vocabulary).
    """
    try:
        stats = store.aggregate_cause_stats()
    except Exception:
        raise HTTPException(status_code=500, detail="원인 통계를 불러오지 못했습니다.")
    for p in stats["patterns"]:
        p["mapped"] = p["pattern"] in MAPPED_PATTERNS
    return stats
