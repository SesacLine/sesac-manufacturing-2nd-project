"""⑤ _commonality_cohort — commonality 전용 이력 코호트(0727, 그룹 단위/증거 코호트 분리).

카드·P2 단위(그룹 lot_ids)는 불변이고, commonality 입력만 "같은 패턴 최근 K일 로트"로
확장된다. 여기서는 코호트 선정 규칙만 검증한다(그룹 로트 우선·패턴 일치·K일 창·미래 제외·
콜드 스타트 폴백).
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.nodes.hypothesis import COHORT_MAX_LOTS, _commonality_cohort

DEFECT_TS = "2026-02-05 12:00:00"


def _make_dbs(tmp_path, monkeypatch, readings, eds):
    """(app_state.wafer_reading, fab.lot_history) 최소 스키마 생성 + env 지정."""
    app_db = tmp_path / "app_state.db"
    con = sqlite3.connect(app_db)
    con.execute(
        "CREATE TABLE wafer_reading (lot_id TEXT, wafer_id TEXT, defect_pattern TEXT)"
    )
    con.executemany("INSERT INTO wafer_reading VALUES (?, '1', ?)", readings)
    con.commit()
    con.close()

    fab_db = tmp_path / "fab.db"
    con = sqlite3.connect(fab_db)
    con.execute("CREATE TABLE lot_history (lot_id TEXT, step TEXT, ts_out TEXT)")
    con.executemany("INSERT INTO lot_history VALUES (?, 'EDS', ?)", eds)
    con.commit()
    con.close()

    monkeypatch.setenv("APP_STATE_DB", str(app_db))
    monkeypatch.setenv("FAB_DB", str(fab_db))


def test_cohort_extends_with_recent_same_pattern(tmp_path, monkeypatch):
    _make_dbs(
        tmp_path,
        monkeypatch,
        readings=[
            ("lotA", "Edge-Ring"),   # 3일 전 — 포함
            ("lotB", "Edge-Ring"),   # 6일 전 — 포함 (K=7 창 안)
            ("lotC", "Center"),      # 다른 패턴 — 제외
            ("lotD", "Edge-Ring"),   # 9일 전 — 창 밖 제외
            ("lotE", "Edge-Ring"),   # defect_ts 이후(미래) — 제외
        ],
        eds=[
            ("lotA", "2026-02-02 10:00:00"),
            ("lotB", "2026-01-30 10:00:00"),
            ("lotC", "2026-02-03 10:00:00"),
            ("lotD", "2026-01-27 10:00:00"),
            ("lotE", "2026-02-07 10:00:00"),
        ],
    )
    cohort = _commonality_cohort("Edge-Ring", ["lotG"], DEFECT_TS)
    # 그룹 로트 선두 + 이력은 EDS 최신순
    assert cohort == ["lotG", "lotA", "lotB"]


def test_cohort_excludes_group_lots_from_history(tmp_path, monkeypatch):
    _make_dbs(
        tmp_path,
        monkeypatch,
        readings=[("lotG", "Edge-Ring"), ("lotA", "Edge-Ring")],
        eds=[("lotG", "2026-02-05 09:00:00"), ("lotA", "2026-02-02 10:00:00")],
    )
    cohort = _commonality_cohort("Edge-Ring", ["lotG"], DEFECT_TS)
    assert cohort == ["lotG", "lotA"]          # lotG 중복 편입 없음


def test_cohort_caps_history_size(tmp_path, monkeypatch):
    lots = [f"lot{i:02d}" for i in range(COHORT_MAX_LOTS + 5)]
    _make_dbs(
        tmp_path,
        monkeypatch,
        readings=[(lot, "Center") for lot in lots],
        eds=[(lot, f"2026-02-0{1 + i % 5} 10:00:{i:02d}") for i, lot in enumerate(lots)],
    )
    cohort = _commonality_cohort("Center", ["lotG"], DEFECT_TS)
    assert len(cohort) == 1 + COHORT_MAX_LOTS


def test_cohort_cold_start_returns_group(tmp_path, monkeypatch):
    # app_state.db 자체가 없음(첫 배치) → 그룹 그대로(곱게 무너짐)
    monkeypatch.setenv("APP_STATE_DB", str(tmp_path / "missing.db"))
    monkeypatch.setenv("FAB_DB", str(tmp_path / "missing_fab.db"))
    assert _commonality_cohort("Center", ["lotG"], DEFECT_TS) == ["lotG"]


def test_cohort_no_defect_ts_returns_group(tmp_path, monkeypatch):
    assert _commonality_cohort("Center", ["lotG"], None) == ["lotG"]
