"""yield_calc 순수 계산 계약 — 임시 SQLite에 wafer/lot_history를 심어 검증한다.

fab.db 불필요(CI의 `-m "not data"`에서 그대로 돈다).
검증 대상은 계산 정의:
    - 날짜 귀속 = EDS ts_out (lowyield.py와 같은 축)
    - 가중치 = 웨이퍼 1장 1표 (로트 단순평균 아님)
    - 장비별은 통과 장비 전부에 중복 귀속
    - fab.db 부재 시 빈 값
"""

from __future__ import annotations

import sqlite3

import pytest

from backend import yield_calc

# lot1(EDS 01-02, EQ-A→EDS-01): 웨이퍼 4장 중 3장 정상 → 0.75
# lot2(EDS 01-02, EQ-B→EDS-01): 웨이퍼 2장 중 2장 정상 → 1.0
# lot3(EDS 01-03, EQ-A→EDS-01): 웨이퍼 2장 중 1장 정상 → 0.5
_WAFERS = [
    ("lot1", "1", 1), ("lot1", "2", 1), ("lot1", "3", 1), ("lot1", "4", 0),
    ("lot2", "1", 1), ("lot2", "2", 1),
    ("lot3", "1", 1), ("lot3", "2", 0),
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
        "INSERT INTO wafer VALUES('t', ?, ?, NULL, 1.0, ?)", _WAFERS
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
