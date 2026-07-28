"""일일 수율 계산 — fab.db 원시 데이터(wafer × lot_history) 실집계.

- 대시보드가 쓰던 metric_series(metric='yield')는 시뮬레이터가 변화점 탐지(detect_change_points)용으로
사전 계산한 장비 감시 신호(defect-lot 비율)라 라인 수율 정의로 부적합
— 여기서는 파이프라인 (nodes/lowyield.py)과 같은 축으로 원시 데이터에서 직접 계산:

    일일 수율(d) = d에 EDS(최종 공정)를 끝낸 로트들의 웨이퍼 중 정상 웨이퍼 비율
    (날짜 귀속 = lot_history.step='EDS'의 ts_out, 가중치 = 웨이퍼 1장 1표)

반환은 전부 0~1 비율 — ×100·반올림은 라우터 책임(현행 규약 유지: charts 소수 1자리, yield_summary 정수)
fab.db 부재/미설정 시 빈 값으로 처리(CI에는 fab.db가 없다).
fab.db는 read-only (SELECT만 사용)
"""

from __future__ import annotations

import sqlite3

from .config import fab_db_path

_EDS_JOIN = """
    FROM wafer w
    JOIN lot_history h ON h.lot_id = w.lot_id AND h.step = 'EDS'
"""


def _query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    con = sqlite3.connect(fab_db_path())
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def daily_line_yield(upto: str | None = None) -> list[dict]:
    """[{date: 'YYYY-MM-DD', ratio: 0.0~1.0}] 날짜 오름차순.

    upto(YYYY-MM-DD)가 있으면 그 날짜 이하만 — /yield-daily의 배치 커서 컷용.
    """
    where = "WHERE date(h.ts_out) <= date(?)" if upto is not None else ""
    sql = f"""
        SELECT date(h.ts_out) AS d,
               AVG(CASE WHEN w.is_normal THEN 1.0 ELSE 0.0 END) AS ratio
        {_EDS_JOIN}
        {where}
        GROUP BY d
        ORDER BY d ASC
    """
    try:
        rows = _query(sql, (upto,) if upto is not None else ())
    except Exception:  # noqa: BLE001 — FAB_DB 미설정/부재 시 빈 값(곱게 무너짐)
        return []
    return [{"date": r["d"], "ratio": r["ratio"]} for r in rows]


def latest_eds_date() -> str | None:
    """데이터축 최신일 = EDS ts_out의 최대 날짜. "최근 7일" 창 기준일(§1 시각 규약 —
    벽시계 안 씀). metric_series max(ts) 기준이던 것을 원천 일관성 위해 교체."""
    try:
        rows = _query("SELECT MAX(date(ts_out)) AS m FROM lot_history WHERE step = 'EDS'")
    except Exception:  # noqa: BLE001
        return None
    return rows[0]["m"] if rows else None


def daily_equipment_yield(date_from: str, date_to: str) -> dict[str, dict[str, float]]:
    """{equipment_id: {date: ratio}} — /yield-summary의 low_yield_eq(최저 장비) 선정용.

    그 날 EDS를 끝낸 로트의 웨이퍼 수율을 로트가 지나간 모든 장비에 중복 귀속한다
    (로트 하나가 step 수만큼 여러 장비에 반영 — 시뮬레이터 metric_series 산출과 같은 방식)
    """
    sql = f"""
        SELECT h2.equipment_id AS eq, date(h.ts_out) AS d,
               AVG(CASE WHEN w.is_normal THEN 1.0 ELSE 0.0 END) AS ratio
        {_EDS_JOIN}
        JOIN lot_history h2 ON h2.lot_id = w.lot_id
        WHERE date(h.ts_out) >= date(?) AND date(h.ts_out) <= date(?)
        GROUP BY eq, d
    """
    try:
        rows = _query(sql, (date_from, date_to))
    except Exception:  # noqa: BLE001
        return {}
    by_eq: dict[str, dict[str, float]] = {}
    for r in rows:
        by_eq.setdefault(r["eq"], {})[r["d"]] = r["ratio"]
    return by_eq
