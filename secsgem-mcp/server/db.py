"""fab.db 읽기 전용 접근 헬퍼.

정답 격리: server/ 는 datasets/fab.db 만 읽음.
정답 카드 디렉토리는 여기서도, 다른 server/ 코드에서도 절대 열지 않음.
(디렉토리명 리터럴 언급조차 tests/의 누출 가드 테스트에 걸림).
"""
import io
import os
import pathlib
import sqlite3

import numpy as np

DB_PATH = pathlib.Path(os.environ.get("FAB_DB", "datasets/fab.db"))

_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        if not DB_PATH.exists():
            raise FileNotFoundError(
                f"{DB_PATH} 없음 — 먼저 `python -m simulator.generate ...` 로 빌드")
        # mode=ro: 서버는 어떤 경로로도 fab.db를 수정할 수 없다 (P5)
        _conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True,
                                check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return get_conn().execute(sql, params).fetchall()


def get_wafer_record(lot_id: str, wafer_id: str) -> dict | None:
    rows = query("SELECT source, die_map, die_size FROM wafer "
                 "WHERE lot_id=? AND wafer_id=?", (lot_id, wafer_id))
    if not rows:
        return None
    r = rows[0]
    if r["die_map"] is None:      # 배경 lot은 이미지 미저장 (용량 절약)
        return None
    return {
        "source": r["source"],
        "die_map": np.load(io.BytesIO(r["die_map"]), allow_pickle=False),
        "die_size": r["die_size"],
    }
