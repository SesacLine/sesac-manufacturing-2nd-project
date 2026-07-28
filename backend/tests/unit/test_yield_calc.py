"""yield_calc 순수 계산 계약 — 임시 SQLite에 wafer/lot_history를 심어 검증한다.

fab.db 불필요(CI의 `-m "not data"`에서 그대로 돈다).
검증 대상은 계산 정의:
    - 날짜 귀속 = EDS ts_out (lowyield.py와 같은 축)
    - 가중치 = 웨이퍼 1장 1표 (로트 단순평균 아님)
    - 장비별은 통과 장비 전부에 중복 귀속
    - fab.db 부재 시 빈 값
"""

from __future__ import annotations

import io
import sqlite3

import numpy as np
import pytest

from backend import yield_calc


def _blob(arr) -> bytes:
    """시뮬레이터 generate.py의 _blob과 동일한 np.save 직렬화."""
    buf = io.BytesIO()
    np.save(buf, np.asarray(arr, dtype=np.uint8), allow_pickle=False)
    return buf.getvalue()


# die_map 값: 0=die 없음 · 1=정상 · 2=불량
_MAP_A = _blob([[1, 1], [1, 2]])  # 3g 1b
_MAP_B = _blob([[1, 1], [1, 1]])  # 4g 0b
_MAP_C = _blob([[1, 2], [2, 2]])  # 1g 3b

# lot1(EDS 01-02, EQ-A→EDS-01): 웨이퍼 4장 중 3장 정상 → 0.75 (4번 웨이퍼는 die_map 없음)
# lot2(EDS 01-02, EQ-B→EDS-01): 웨이퍼 2장 중 2장 정상 → 1.0
# lot3(EDS 01-03, EQ-A→EDS-01): 웨이퍼 2장 중 1장 정상 → 0.5
# die 단위: 01-02 = 3×(3g1b)+2×(4g0b) = 17/20 = 0.85 · 01-03 = 2×(1g3b) = 2/8 = 0.25
_WAFERS = [
    ("lot1", "1", 1, _MAP_A), ("lot1", "2", 1, _MAP_A),
    ("lot1", "3", 1, _MAP_A), ("lot1", "4", 0, None),
    ("lot2", "1", 1, _MAP_B), ("lot2", "2", 1, _MAP_B),
    ("lot3", "1", 1, _MAP_C), ("lot3", "2", 0, _MAP_C),
]
_HISTORY = [
    ("lot1", "CLEAN", "EQ-A", "2026-01-01T10:00:00"),
    ("lot1", "EDS", "EDS-01", "2026-01-02T10:00:00"),
    ("lot2", "CLEAN", "EQ-B", "2026-01-01T11:00:00"),
    ("lot2", "EDS", "EDS-01", "2026-01-02T11:00:00"),
    ("lot3", "CLEAN", "EQ-A", "2026-01-02T10:00:00"),
    ("lot3", "EDS", "EDS-01", "2026-01-03T10:00:00"),
]


@pytest.fixture()
def fab_db(tmp_path, monkeypatch):
    path = tmp_path / "fab.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE wafer(source TEXT, lot_id TEXT, wafer_id TEXT,
            die_map BLOB, die_size REAL, is_normal INT,
            PRIMARY KEY(lot_id, wafer_id));
        CREATE TABLE lot_history(lot_id TEXT, step TEXT, equipment_id TEXT,
            chamber TEXT, recipe_id TEXT, ts_in TEXT, ts_out TEXT);
        """
    )
    con.executemany(
        "INSERT INTO wafer VALUES('t', ?, ?, ?, 1.0, ?)",
        [(l, w, m, n) for (l, w, n, m) in _WAFERS],
    )
    con.executemany(
        "INSERT INTO lot_history VALUES(?, ?, ?, NULL, NULL, ?, ?)",
        [(l, s, e, ts, ts) for (l, s, e, ts) in _HISTORY],
    )
    con.commit()
    con.close()
    monkeypatch.setenv("FAB_DB", str(path))
    return path


def test_daily_line_yield_wafer_weighted(fab_db):
    """웨이퍼 1장 1표 — 01-02는 6장 중 5장 정상(5/6), 로트 단순평균(0.875) 아님"""
    days = yield_calc.daily_line_yield()
    assert [d["date"] for d in days] == ["2026-01-02", "2026-01-03"]
    assert days[0]["ratio"] == pytest.approx(5 / 6)
    assert days[0]["ratio"] != pytest.approx((0.75 + 1.0) / 2)
    assert days[1]["ratio"] == pytest.approx(0.5)


def test_daily_line_yield_upto_cut(fab_db):
    """upto(배치 커서) 이하만 — /yield-daily 커서 컷 계약"""
    days = yield_calc.daily_line_yield(upto="2026-01-02")
    assert [d["date"] for d in days] == ["2026-01-02"]


def test_latest_eds_date(fab_db):
    """"최근 7일" 기준일 = EDS ts_out 최대 날짜(데이터축)"""
    assert yield_calc.latest_eds_date() == "2026-01-03"


def test_daily_equipment_yield_attribution(fab_db):
    """로트 수율이 통과 장비 전부에 중복 귀속"""
    by_eq = yield_calc.daily_equipment_yield("2026-01-02", "2026-01-03")
    # EQ-A: 01-02엔 lot1(0.75), 01-03엔 lot3(0.5)
    assert by_eq["EQ-A"]["2026-01-02"] == pytest.approx(0.75)
    assert by_eq["EQ-A"]["2026-01-03"] == pytest.approx(0.5)
    # EQ-B: lot2만 (1.0)
    assert by_eq["EQ-B"] == {"2026-01-02": pytest.approx(1.0)}
    # EDS-01: 세 로트 전부 지나갔다 — 01-02는 웨이퍼 가중 5/6
    assert by_eq["EDS-01"]["2026-01-02"] == pytest.approx(5 / 6)


def test_daily_equipment_yield_window(fab_db):
    """창 밖 날짜(EDS 기준)는 제외"""
    by_eq = yield_calc.daily_equipment_yield("2026-01-03", "2026-01-03")
    assert all("2026-01-02" not in dates for dates in by_eq.values())


def test_graceful_without_fab_db(monkeypatch):
    """FAB_DB 미설정이면 빈 값"""
    monkeypatch.delenv("FAB_DB", raising=False)
    assert yield_calc.daily_line_yield() == []
    assert yield_calc.daily_equipment_yield("2026-01-01", "2026-01-07") == {}
    assert yield_calc.latest_eds_date() is None


# ── v1.1: die 단위 Y_S × Y_R 분해 ───────────────────────────────────────────────


def test_daily_yield_decomposition(fab_db):
    """DY = Y_S × Y_R 항등식 + 윈도우 최대치 베이스라인 거동.

    01-02 die 수율 0.85(die_map 없는 웨이퍼는 제외), 01-03은 0.25로 급락 —
    베이스라인(Y_R)은 전날 최대 0.85를 유지하고 체계적 성분(Y_S)만 꺼진다.
    """
    out = yield_calc.daily_yield_decomposition()
    assert [d["date"] for d in out] == ["2026-01-02", "2026-01-03"]
    d1, d2 = out
    assert d1["die_ratio"] == pytest.approx(17 / 20)
    assert d1["systematic_ratio"] == pytest.approx(1.0)  # 당일 포함 윈도우 최대 = 자기 자신
    assert d2["die_ratio"] == pytest.approx(0.25)
    assert d2["random_ratio"] == pytest.approx(17 / 20)
    assert d2["systematic_ratio"] == pytest.approx(0.25 / (17 / 20))
    for d in out:
        assert d["die_ratio"] == pytest.approx(d["random_ratio"] * d["systematic_ratio"])


def test_decomposition_upto_cut(fab_db):
    """upto(배치 커서) 이하만 — /yield-daily additive 시리즈도 커서 컷 대상"""
    out = yield_calc.daily_yield_decomposition(upto="2026-01-02")
    assert [d["date"] for d in out] == ["2026-01-02"]


def test_decomposition_graceful_without_fab_db(monkeypatch):
    """FAB_DB 미설정이면 빈 값 — die 파싱 경로도 곱게 무너진다"""
    monkeypatch.delenv("FAB_DB", raising=False)
    assert yield_calc.daily_yield_decomposition() == []
