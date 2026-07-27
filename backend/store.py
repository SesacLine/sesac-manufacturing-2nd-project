"""app_state.db 접근 계층 — 배치·분석 결과·웨이퍼 판독의 유일한 저장소.

명세 §2.7 원칙("배치 실행 시 리치하게 보존 → 조회만, 재계산 금지")에 따라
분석/근거는 배치 완료 시점에 JSON으로 통째로 저장하고, 조회 API는 여기서 꺼내기만 한다.

테이블:
    cursor_state      — 배치 커서(직전 배치가 처리한 데이터축 마지막 날짜). §2.3 누적 스코프.
    batch             — 배치 진행 상태(§2.4 폴링 대상). logs/result_ids는 JSON 컬럼.
    analysis          — 분석 결과 상세(§2.5) + 가설별 근거(§2.7)를 payload JSON에 통째 보존.
    wafer_reading     — 배치 시 VLM 판독 결과(웨이퍼 단위). §2.6 웨이퍼 목록의 원천.
"""

from __future__ import annotations

import datetime
import json
import sqlite3
import threading

from .config import app_state_db_path

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(app_state_db_path())
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with _lock, _connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS cursor_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                cursor_date TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS batch (
                batch_id TEXT PRIMARY KEY,
                seq INTEGER NOT NULL,
                status TEXT NOT NULL,
                current_step INTEGER NOT NULL DEFAULT 0,
                logs_json TEXT NOT NULL DEFAULT '[]',
                result_ids_json TEXT,
                error TEXT,
                started_at TEXT NOT NULL,
                cursor_start TEXT
            );
            CREATE TABLE IF NOT EXISTS analysis (
                analysis_id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                pattern TEXT NOT NULL,
                status TEXT NOT NULL,
                lot_count INTEGER NOT NULL,
                top_cause TEXT,
                payload_json TEXT NOT NULL,
                confidence TEXT,
                yield_impact REAL,
                defect_date TEXT,
                top_equipment TEXT,
                top_stage TEXT,
                top_tier TEXT
            );
            CREATE TABLE IF NOT EXISTS wafer_reading (
                lot_id TEXT NOT NULL,
                wafer_id TEXT NOT NULL,
                defect_pattern TEXT NOT NULL,
                PRIMARY KEY (lot_id, wafer_id)
            );
            """
        )
        # v1.1 컬럼 마이그레이션 — 기존 app_state.db(구 스키마)에 새 컬럼을 얹는다.
        # CREATE TABLE IF NOT EXISTS는 기존 테이블에 컬럼을 추가하지 않으므로 ALTER로 보충.
        for col, decl in (
            ("confidence", "TEXT"), ("yield_impact", "REAL"), ("defect_date", "TEXT"),
            ("top_equipment", "TEXT"), ("top_stage", "TEXT"), ("top_tier", "TEXT"),
        ):
            try:
                con.execute(f"ALTER TABLE analysis ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:  # duplicate column — 이미 신 스키마
                pass
        # 배치 시작 시점의 커서 — 시연용 초기화(rollback_last_batch)의 복원 지점.
        try:
            con.execute("ALTER TABLE batch ADD COLUMN cursor_start TEXT")
        except sqlite3.OperationalError:
            pass


# ---------------------------------------------------------------- cursor

def get_cursor() -> str | None:
    with _lock, _connect() as con:
        row = con.execute("SELECT cursor_date FROM cursor_state WHERE id = 1").fetchone()
        return row["cursor_date"] if row else None


def set_cursor(cursor_date: str) -> None:
    with _lock, _connect() as con:
        con.execute(
            "INSERT INTO cursor_state (id, cursor_date) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET cursor_date = excluded.cursor_date",
            (cursor_date,),
        )


# ---------------------------------------------------------------- batch

def find_batch_by_status(statuses: list[str]) -> dict | None:
    with _lock, _connect() as con:
        placeholders = ",".join("?" * len(statuses))
        row = con.execute(
            f"SELECT * FROM batch WHERE status IN ({placeholders}) ORDER BY seq DESC LIMIT 1",
            statuses,
        ).fetchone()
        return _batch_row_to_dict(row) if row else None


def find_completed_batch_on(date_compact: str) -> dict | None:
    """그 날짜(YYYYMMDD)에 완료된 배치 1건. 하루 1회 정책(§2.3)을 **날짜 단위로** 판정한다.

    batch_id가 "batch_{YYYYMMDD}_{seq}"라 접두로 찾는다 — 커서가 전진하면 서버 '오늘'도
    바뀌므로 다음 날 배치는 자연히 통과한다.
    """
    with _lock, _connect() as con:
        row = con.execute(
            "SELECT * FROM batch WHERE status = 'completed' AND batch_id LIKE ? "
            "ORDER BY seq DESC LIMIT 1",
            (f"batch_{date_compact}_%",),
        ).fetchone()
        return _batch_row_to_dict(row) if row else None


def rollback_last_batch() -> dict | None:
    """가장 최근 배치와 그 분석 결과를 지우고 커서를 되돌린다(시연용 "초기화").

    되돌리는 것: 그 배치의 analysis row 전부 · batch row · 배치 커서.
    커서는 그 배치가 시작한 지점(cursor_start)으로 복원한다 — 저장돼 있지 않은 구 배치는
    "하루 전진" 규칙을 역산해 하루 되돌린다(현재 운영 방식이 하루 단위라 맞아떨어진다).

    wafer_reading(판독 결과)은 지우지 않는다 — batch_id를 안 들고 있어 어느 배치 것인지
    가릴 수 없고, 같은 로트를 다시 판독하면 어차피 덮어쓰기 때문이다.

    반환: 되돌린 배치 정보(없으면 None).
    """
    with _lock, _connect() as con:
        row = con.execute("SELECT * FROM batch ORDER BY seq DESC LIMIT 1").fetchone()
        if row is None:
            return None
        batch_id = row["batch_id"]
        removed = con.execute(
            "SELECT COUNT(*) AS c FROM analysis WHERE batch_id = ?", (batch_id,)
        ).fetchone()["c"]

        restored = row["cursor_start"] if "cursor_start" in row.keys() else None
        if restored is None:
            cur = con.execute("SELECT cursor_date FROM cursor_state WHERE id = 1").fetchone()
            if cur:
                restored = (
                    datetime.date.fromisoformat(cur["cursor_date"]) - datetime.timedelta(days=1)
                ).isoformat()

        con.execute("DELETE FROM analysis WHERE batch_id = ?", (batch_id,))
        con.execute("DELETE FROM batch WHERE batch_id = ?", (batch_id,))
        if restored is None:
            con.execute("DELETE FROM cursor_state")   # 첫 배치까지 되돌림 = 커서 없음
        else:
            con.execute(
                "INSERT INTO cursor_state (id, cursor_date) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET cursor_date = excluded.cursor_date",
                (restored,),
            )
        return {"batch_id": batch_id, "removed_analyses": removed, "cursor_restored_to": restored}


def next_batch_seq() -> int:
    with _lock, _connect() as con:
        row = con.execute("SELECT MAX(seq) AS m FROM batch").fetchone()
        return (row["m"] or 0) + 1


def create_batch(batch_id: str, seq: int, started_at: str, cursor_start: str | None = None) -> None:
    """배치 row 생성. cursor_start는 이 배치를 돌리기 직전의 커서 —
    시연용 "초기화"(rollback_last_batch)가 커서를 정확히 되돌리는 데 쓴다."""
    with _lock, _connect() as con:
        con.execute(
            "INSERT INTO batch (batch_id, seq, status, current_step, logs_json, started_at, "
            "                   cursor_start) "
            "VALUES (?, ?, 'running', 0, '[]', ?, ?)",
            (batch_id, seq, started_at, cursor_start),
        )


def get_batch(batch_id: str) -> dict | None:
    with _lock, _connect() as con:
        row = con.execute("SELECT * FROM batch WHERE batch_id = ?", (batch_id,)).fetchone()
        return _batch_row_to_dict(row) if row else None


def update_batch_step(batch_id: str, current_step: int) -> None:
    with _lock, _connect() as con:
        con.execute(
            "UPDATE batch SET current_step = ? WHERE batch_id = ?", (current_step, batch_id)
        )


def append_batch_log(batch_id: str, entry: dict) -> None:
    """logs[] 원소 1건 추가. entry = {time, tool, message, status} (§2.4)."""
    with _lock, _connect() as con:
        row = con.execute(
            "SELECT logs_json FROM batch WHERE batch_id = ?", (batch_id,)
        ).fetchone()
        if row is None:
            return
        logs = json.loads(row["logs_json"])
        logs.append(entry)
        con.execute(
            "UPDATE batch SET logs_json = ? WHERE batch_id = ?",
            (json.dumps(logs, ensure_ascii=False), batch_id),
        )


def finish_batch(batch_id: str, result_ids: list[str]) -> None:
    with _lock, _connect() as con:
        con.execute(
            "UPDATE batch SET status = 'completed', current_step = 7, result_ids_json = ? "
            "WHERE batch_id = ?",
            (json.dumps(result_ids), batch_id),
        )


def fail_batch(batch_id: str, error: str) -> None:
    with _lock, _connect() as con:
        con.execute(
            "UPDATE batch SET status = 'failed', error = ? WHERE batch_id = ?",
            (error, batch_id),
        )


def _batch_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "batch_id": row["batch_id"],
        "seq": row["seq"],
        "status": row["status"],
        "current_step": row["current_step"],
        "logs": json.loads(row["logs_json"]),
        "result_ids": json.loads(row["result_ids_json"]) if row["result_ids_json"] else None,
        "error": row["error"],
        "started_at": row["started_at"],
    }


# ---------------------------------------------------------------- analysis

def save_analysis(
    analysis_id: str,
    batch_id: str,
    seq: int,
    pattern: str,
    status: str,
    lot_count: int,
    top_cause: str | None,
    payload: dict,
    confidence: str | None = None,
    yield_impact: float | None = None,
    defect_date: str | None = None,
    top_equipment: str | None = None,
    top_stage: str | None = None,
    top_tier: str | None = None,
) -> None:
    """v1.1 확장 컬럼(confidence~top_tier)은 목록(§2.2)·차트(§2.8/§2.9) 조회용 비정규화 —
    정본은 여전히 payload_json이며, 확장 컬럼은 payload를 다시 파싱하지 않기 위한 캐시다."""
    with _lock, _connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO analysis "
            "(analysis_id, batch_id, seq, pattern, status, lot_count, top_cause, payload_json, "
            " confidence, yield_impact, defect_date, top_equipment, top_stage, top_tier) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                analysis_id,
                batch_id,
                seq,
                pattern,
                status,
                lot_count,
                top_cause,
                json.dumps(payload, ensure_ascii=False),
                confidence,
                yield_impact,
                defect_date,
                top_equipment,
                top_stage,
                top_tier,
            ),
        )


def list_analyses(sort: str, limit: int, offset: int) -> tuple[int, list[dict]]:
    """(전체 count, 페이지 items). 정렬 키는 배치 순번(seq) = 배치 실행 시각 순.

    v1.1: items에 confidence(구 저장분은 "low" 폴백)·yield_impact(Nullable)를 함께 내려
    프론트 대기열이 확신 수준·수율영향 컬럼을 그리게 한다.

    analyzed_date는 **분석 실행일**(그 분석을 만든 배치의 시작일)이다 — 결함 발생일
    (defect_date)이 아니다. 대기열은 "언제 돌린 분석인가" 순으로 쌓이므로 실행일을 보여
    누적 이력을 읽게 한다. batch.started_at은 "{EVENT_DATE}T{HH:MM:SS}Z"라 앞 10자가 날짜다
    (서버 '오늘' 기준 — 벽시계 아님, §1). 배치 row가 지워진 구 저장분은 NULL.
    """
    order = "DESC" if sort == "latest" else "ASC"
    with _lock, _connect() as con:
        count = con.execute("SELECT COUNT(*) AS c FROM analysis").fetchone()["c"]
        rows = con.execute(
            f"SELECT a.analysis_id, a.batch_id, a.pattern, a.lot_count, a.top_cause, a.status, "
            f"       COALESCE(a.confidence, 'low') AS confidence, a.yield_impact, "
            f"       substr(b.started_at, 1, 10) AS analyzed_date "
            f"FROM analysis a LEFT JOIN batch b ON b.batch_id = a.batch_id "
            f"ORDER BY a.seq {order}, a.analysis_id {order} LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return count, [dict(r) for r in rows]


def list_analysis_events() -> list[dict]:
    """§2.8 이벤트 오버레이 — defect_date가 잡힌 분석 전부(날짜 오름차순).

    reviewed가 아니어도(insufficient/novel) 이상 이벤트 자체는 유효하므로 내린다 —
    표시 구분은 프론트 몫. defect_date 없는 구 저장분은 제외된다.
    """
    with _lock, _connect() as con:
        rows = con.execute(
            "SELECT defect_date AS date, analysis_id, pattern, status, top_cause AS cause, "
            "       top_equipment AS equipment, top_stage AS stage, top_tier AS tier, "
            "       COALESCE(confidence, 'low') AS confidence "
            "FROM analysis WHERE defect_date IS NOT NULL "
            "ORDER BY defect_date ASC, analysis_id ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def aggregate_cause_stats() -> dict:
    """§2.9 집계 — 장비 구성(도넛)·패턴별 판독 웨이퍼 수(Pareto)·패턴별 채택 원인(칩).

    전부 app_state.db 자체 데이터만 읽는다(fab.db 불필요 → CI 안전). Pareto는 정답 라벨이
    아니라 CNN 판독 저장분(wafer_reading) 집계다 — 정답 누출 없음.
    """
    with _lock, _connect() as con:
        eq_rows = con.execute(
            "SELECT top_equipment AS equipment_id, top_stage AS stage, COUNT(*) AS count "
            "FROM analysis WHERE status = 'reviewed' AND top_equipment IS NOT NULL "
            "GROUP BY top_equipment, top_stage ORDER BY count DESC, equipment_id ASC"
        ).fetchall()
        cause_rows = con.execute(
            "SELECT pattern, top_cause AS cause, top_stage AS stage, top_tier AS tier, "
            "       COUNT(*) AS count "
            "FROM analysis WHERE status = 'reviewed' AND top_cause IS NOT NULL "
            "GROUP BY pattern, top_cause, top_stage, top_tier "
            "ORDER BY count DESC, pattern ASC, cause ASC"
        ).fetchall()
        pattern_rows = con.execute(
            "SELECT defect_pattern AS pattern, COUNT(*) AS wafer_count "
            "FROM wafer_reading GROUP BY defect_pattern ORDER BY wafer_count DESC"
        ).fetchall()
    return {
        "equipment": [dict(r) for r in eq_rows],
        "causes": [dict(r) for r in cause_rows],
        "patterns": [dict(r) for r in pattern_rows],
    }


def get_analysis(analysis_id: str) -> dict | None:
    with _lock, _connect() as con:
        row = con.execute(
            "SELECT payload_json FROM analysis WHERE analysis_id = ?", (analysis_id,)
        ).fetchone()
        return json.loads(row["payload_json"]) if row else None


# ---------------------------------------------------------------- wafer readings

def save_wafer_readings(readings: list[tuple[str, str, str]]) -> None:
    """(lot_id, wafer_id, defect_pattern) 목록 일괄 저장."""
    with _lock, _connect() as con:
        con.executemany(
            "INSERT OR REPLACE INTO wafer_reading (lot_id, wafer_id, defect_pattern) "
            "VALUES (?, ?, ?)",
            readings,
        )


def get_wafer_readings(lot_id: str) -> list[dict]:
    """lot의 판독 웨이퍼 목록 — wafer_id 정수 오름차순 정렬(§2.6)."""
    with _lock, _connect() as con:
        rows = con.execute(
            "SELECT wafer_id, defect_pattern FROM wafer_reading WHERE lot_id = ?", (lot_id,)
        ).fetchall()
    items = [dict(r) for r in rows]
    items.sort(key=lambda r: int(r["wafer_id"]))
    return items
