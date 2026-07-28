"""차트 데이터 2종 (명세 v1.1 §2.8·§2.9) — 대시보드 확장 차트(와이어프레임 v8)의 원천.

GET /yield-daily   일별 라인 수율 전 구간 + 분석 이벤트 오버레이(급락 지점 툴팁·마커).
GET /stats/causes  장비 구성(도넛)·패턴별 판독 웨이퍼 수(Pareto)·패턴별 채택 원인(칩) 집계.

시각 규약(§1): 날짜는 전부 데이터축(fab.db ts / 분석 defect_date)이다 — 벽시계 안 씀.
§2.7 원칙: 이벤트·집계는 배치 때 저장된 분석 row에서 조회만 한다(재계산 없음).
fab.db가 없으면 days만 빈 배열로 내려간다(이벤트·집계는 app_state.db라 CI에서도 동작).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import store, yield_calc
from ..schemas import MAPPED_PATTERNS

router = APIRouter()


@router.get("/yield-daily")
def get_yield_daily() -> dict:
    """§2.8 — { days: [{date, yield}], events: [{date, analysis_id, pattern, status,
    cause, equipment, stage, tier, confidence}] }.

    days: 웨이퍼 실집계 일일 라인 수율(yield_calc — EDS 종료일 귀속, 정상 웨이퍼 비율, 0~100 소수 1자리)을 배치 커서(분석 완료 지점)까지만 내림.
    파이프라인 (nodes/lowyield.py)의 저수율 판단과 같은 축이라 차트 급락 지점과 분석 카드가 같은 수율 정의를 가리킴 (events: defect_date가 잡힌 분석 전부)
    reviewed 외 상태도 이상 이벤트로 내림.

    왜 커서로 자르나 — 대시보드는 "지금까지 분석된 것"을 보여주는 화면이다. fab.db에는 아직
    배치가 닿지 않은 미래 구간까지 들어 있어서, 전 구간을 그리면 분석 카드가 없는 급락 지점이
    차트에만 뜬다("이 급락은 왜 분석이 없지?"). 커서까지만 그리면 차트 끝과 대기열이 같은
    시점을 가리키고, 배치를 돌릴 때마다 차트가 하루씩 자라 누적이 눈에 보인다.
    커서가 없으면(배치 이력 없음) 빈 배열 — 분석된 게 없으니 보여줄 실적도 없다.
    """
    try:
        events = store.list_analysis_events()
        cursor = store.get_cursor()
    except Exception:
        raise HTTPException(status_code=500, detail="분석 이벤트를 불러오지 못했습니다.")
    return {"days": _daily_line_yield(cursor), "events": events}


def _daily_line_yield(cursor: str | None) -> list[dict]:
    """웨이퍼 실집계 일별 라인 수율(커서 이하). fab.db 없으면 빈 배열(곱게 무너짐)."""
    if cursor is None:
        return []
    return [
        {"date": d["date"], "yield": round(d["ratio"] * 100, 1)}
        for d in yield_calc.daily_line_yield(upto=cursor)
    ]


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
