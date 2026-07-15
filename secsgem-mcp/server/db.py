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
    if r["die_map"] is None:
        return None
    return {
        "source": r["source"],
        "die_map": np.load(io.BytesIO(r["die_map"]), allow_pickle=False),
        "die_size": r["die_size"],
    }
