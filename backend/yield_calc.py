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

import io
import os
import sqlite3

import numpy as np

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


# ── v1.1: die 단위 Y_S × Y_R 분해 ─────────────
#
# DY = Y_S × Y_R — die 수율(DY)을 무작위 결함 베이스라인(Y_R)과 체계적 손실 수율(Y_S)로 분해
# Y_R은 논문의 windowing 계열: 최근 관측일 윈도우의 DY 최대치(라벨 불사용 — 정답 누출 차단 원칙 유지).
# 웨이퍼 단위 수율(daily_line_yield)은 손실이 전부 패턴 웨이퍼라 분해가 퇴화하므로, 분해는 die 단위에서만.
# die_map 값 규약(WM-811K): 0=die 없음 · 1=정상 die · 2=불량 die.

# Y_R 추정 윈도우(최근 관측일 수). 윈도우 안에 정상일이 하나는 들어온다는 가정 —
# 시나리오 불량은 이벤트성이라 14일 연속 지속되지 않음(fab_model 시나리오 구성 기준).
# TODO(팀 결정 필요, D6): binomial-sigma 등 통계적 추정으로 올릴지, 윈도우 길이 조정.
YR_WINDOW_DAYS = 14

# die_map 파싱(보유 웨이퍼 ~2k장 — 시나리오 로트에만 존재, 실측 ~0.2초)은 요청마다 반복할 이유가 없음
# (경로, mtime) 키로 1회 계산·캐시. fab.db는 배포 단위로 불변이라
# mtime 키면 충분하고, 테스트의 tmp 경로 교체도 키가 갈라져 안전함.
_die_cache: dict[tuple[str, float], list[dict]] = {}


def _daily_die_yield() -> list[dict]:
    """[{date, ratio}] — 일별 die 수율(그날 EDS를 끝낸 로트들의 정상 die 비율)."""
    path = fab_db_path()
    key = (path, os.path.getmtime(path))
    if key not in _die_cache:
        _die_cache.clear()  # 파일이 바뀌면 옛 캐시는 무의미 — 항상 1개만 유지
        _die_cache[key] = _compute_daily_die_yield(path)
    return _die_cache[key]


def _compute_daily_die_yield(path: str) -> list[dict]:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            f"SELECT date(h.ts_out) AS d, w.die_map AS m {_EDS_JOIN}"
            "WHERE w.die_map IS NOT NULL"
        ).fetchall()
    finally:
        con.close()
    acc: dict[str, tuple[int, int]] = {}
    for r in rows:
        m = np.load(io.BytesIO(r["m"]), allow_pickle=False)
        g, b = acc.get(r["d"], (0, 0))
        acc[r["d"]] = (g + int((m == 1).sum()), b + int((m == 2).sum()))
    return [
        {"date": d, "ratio": g / (g + b)}
        for d, (g, b) in sorted(acc.items())
        if g + b
    ]


def daily_yield_decomposition(upto: str | None = None) -> list[dict]:
    """[{date, die_ratio, random_ratio, systematic_ratio}] 날짜 오름차순.

    die_ratio(DY) = random_ratio(Y_R) × systematic_ratio(Y_S)가 항상 성립.
    Y_R = 최근 YR_WINDOW_DAYS 관측일(당일 포함) DY 최대치 → Y_S = DY / Y_R (≤ 1.0).
    당일이 윈도우에 포함되므로 정상일은 Y_S=1.0, 시나리오 주입일만 Y_S가 꺼짐.
    """
    try:
        raw = _daily_die_yield()
    except Exception:  # noqa: BLE001 — FAB_DB 미설정/부재 시 빈 값(곱게 무너짐)
        return []
    if upto is not None:
        raw = [r for r in raw if r["date"] <= upto]
    out = []
    for i, r in enumerate(raw):
        window = raw[max(0, i - YR_WINDOW_DAYS + 1): i + 1]
        y_r = max(x["ratio"] for x in window)
        out.append(
            {
                "date": r["date"],
                "die_ratio": r["ratio"],
                "random_ratio": y_r,
                "systematic_ratio": r["ratio"] / y_r if y_r > 0 else None,
            }
        )
    return out
