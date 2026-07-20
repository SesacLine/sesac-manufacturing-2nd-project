"""GET /yield-summary — 수율 현황 요약 (명세 §2.1).

metric_series 단독 집계(다른 테이블 조인 없음):
    - line_avg     : 날짜별 장비 단순평균 AVG(value) (§2.1 확정 — 가중평균 아님)
    - low_yield_eq : 7일 창에서 평균 수율 최저 장비 1개 선정(BACKEND_DECISIONS.md D3),
                     그 장비의 일별 시리즈
"최근 7일"의 기준일은 벽시계가 아니라 데이터축 최신일 max(ts)다(§1 시각 규약).
DB value(0~1)에 ×100을 서버가 적용해 0~100 정수로 내려주고, 빈 날은 null로 채워
길이 7을 유지한다(보간 없음).
"""

from __future__ import annotations

import datetime
import sqlite3

from fastapi import APIRouter, HTTPException

from ..config import fab_db_path

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
    con = sqlite3.connect(fab_db_path())
    con.row_factory = sqlite3.Row
    try:
        max_row = con.execute(
            "SELECT MAX(date(ts)) AS m FROM metric_series WHERE metric = 'yield'"
        ).fetchone()
        if max_row is None or max_row["m"] is None:
            return {"series": []}  # 데이터 없음 = 200 + 빈 배열 (§2.1 형태 계약)
        max_date = datetime.date.fromisoformat(max_row["m"])
        days = [(max_date - datetime.timedelta(days=6 - i)).isoformat() for i in range(7)]

        rows = con.execute(
            """
            SELECT date(ts) AS d, scope, AVG(value) AS v
            FROM metric_series
            WHERE metric = 'yield' AND date(ts) >= ? AND date(ts) <= ?
            GROUP BY date(ts), scope
            """,
            (days[0], days[-1]),
        ).fetchall()
    finally:
        con.close()

    if not rows:
        return {"series": []}

    # scope(장비) → {날짜: 값}
    by_scope: dict[str, dict[str, float]] = {}
    for r in rows:
        by_scope.setdefault(r["scope"], {})[r["d"]] = r["v"]

    # line_avg: 날짜별 장비 단순평균
    line_avg: list[int | None] = []
    for d in days:
        vals = [m[d] for m in by_scope.values() if d in m]
        line_avg.append(round(sum(vals) / len(vals) * 100) if vals else None)

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
