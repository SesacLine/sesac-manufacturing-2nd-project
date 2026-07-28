"""GET /yield-summary — 수율 현황 요약 (명세 §2.1).

원천은 yield_calc(웨이퍼 실집계 — EDS 종료일 귀속, 정상 웨이퍼 비율)
metric_series 집계였던 것을 교체(metric_series는 변화점 탐지용 장비 감시 신호라 라인 수율 정의로 부적합):
    - line_avg     : 일일 라인 수율(웨이퍼 1장 1표) — /yield-daily와 같은 원천·정의라
                     화면1 요약과 하단 차트가 같은 숫자를 가리킴
    - low_yield_eq : 7일 창에서 평균 수율 최저 장비 1개 선정(BACKEND_DECISIONS.md D3),
                     그 장비의 일별 시리즈(로트 수율을 통과 장비 전부에 귀속 — 설계서 D2)
"최근 7일"의 기준일은 벽시계가 아니라 데이터축 최신일(EDS ts_out 최대 날짜)이다(§1 시각 규약).
비율(0~1)에 ×100을 서버가 적용해 0~100 정수로 내려주고, 빈 날은 null로 채워 길이 7을
유지한다(보간 없음). fab.db 부재/데이터 없음 = 200 + 빈 배열(§2.1 형태 계약).
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, HTTPException

from .. import yield_calc

router = APIRouter()


@router.get("/yield-summary")
def get_yield_summary() -> dict:
    try:
        return _build_summary()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="수율 데이터를 불러오지 못했습니다.")


def _build_summary() -> dict:
    max_d = yield_calc.latest_eds_date()
    if max_d is None:
        return {"series": []}  # 데이터 없음 = 200 + 빈 배열 (§2.1 형태 계약)
    max_date = datetime.date.fromisoformat(max_d)
    days = [(max_date - datetime.timedelta(days=6 - i)).isoformat() for i in range(7)]

    by_scope = yield_calc.daily_equipment_yield(days[0], days[-1])
    if not by_scope:
        return {"series": []}

    # line_avg: 일일 라인 수율(웨이퍼 실집계) — 7일 창만 취해 빈 날은 null
    line_by_date = {
        d["date"]: d["ratio"]
        for d in yield_calc.daily_line_yield(upto=days[-1])
        if d["date"] >= days[0]
    }
    line_avg = [
        round(line_by_date[d] * 100) if d in line_by_date else None for d in days
    ]

    # low_yield_eq: 창 내 평균 수율 최저 장비 1개
    def scope_mean(m: dict[str, float]) -> float:
        return sum(m.values()) / len(m)

    worst_scope = min(by_scope, key=lambda s: scope_mean(by_scope[s]))
    worst = by_scope[worst_scope]
    low_yield = [round(worst[d] * 100) if d in worst else None for d in days]

    return {
        "series": [
            {"name": "low_yield_eq", "points": low_yield},
            {"name": "line_avg", "points": line_avg},
        ]
    }
