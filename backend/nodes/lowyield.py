"""⓪ 저수율 로트 선별. 결정적 함수, 모델 불필요.

wafer.die_map을 직접 집계해 저수율 로트를 뽑는다(fab.db는 read-only).
산출물_기능목록_유스케이스.md §1 참고.
"""

from __future__ import annotations

import os
import sqlite3

from ..state import RCAState

# TODO(팀 결정 필요, jiun_work_0710.md 참고): 고정값 대신 mean - k*std 같은 동적 임계값도 검토.
LOW_YIELD_THRESHOLD = 0.8


def select_low_yield_lots(state: RCAState) -> dict:
    """누적 구간(cursor_date 초과 ~ cursor_end 이하)에 EDS(최종 공정)를 끝낸 로트 중
    저수율 로트만 골라 target_lot_ids를 채운다.

    스코프는 "직전 배치 이후 누적된 저수율 로트"다(API 명세 §2.3 확정) — 하루 창이 아니라
    직전 배치 커서 이후 전체 구간이며, 첫 배치는 데이터축 처음부터 전부 본다.

    fab.db는 read-only라 MCP를 거치지 않고 직접 SQL로 집계한다(내부 배치 단계이므로
    에이전트용 MCP 계약과 무관 — MCP는 Hypothesis/Critic처럼 "확인"이 필요한 단계에서만 쓴다).
    """
    con = sqlite3.connect(os.environ["FAB_DB"])
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT w.lot_id AS lot_id,
               AVG(CASE WHEN w.is_normal THEN 1.0 ELSE 0.0 END) AS yield_ratio
        FROM wafer w
        JOIN lot_history h ON h.lot_id = w.lot_id AND h.step = 'EDS'
        WHERE date(h.ts_out) > date(?) AND date(h.ts_out) <= date(?)
        GROUP BY w.lot_id
        """,
        (state["cursor_date"], state["cursor_end"]),
    ).fetchall()
    con.close()

    target_lot_ids = [r["lot_id"] for r in rows if r["yield_ratio"] < LOW_YIELD_THRESHOLD]
    return {"target_lot_ids": target_lot_ids}
