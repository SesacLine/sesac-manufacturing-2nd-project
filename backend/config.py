"""서버 전역 설정 상수.

EVENT_DATE — API 명세 §1 "고정 기준일". batch_id/analysis_id의 {배치날짜}와 배치 시작
시각의 날짜, logs[].time이 파생하는 날짜에 쓰인다. 데이터축 시각(fab.db max(ts) 기준
조회 창)에는 적용하지 않는다. 데모 전용 고정값 — 실데이터 전환 시 now()로 되돌린다.
"""

from __future__ import annotations

import os

# 명세 §1: 이벤트/조회 시각의 고정 기준일 (데이터축 90일 구간 직후)
EVENT_DATE = "2026-04-01"
EVENT_DATE_COMPACT = EVENT_DATE.replace("-", "")  # ID 채번용 "20260401"

# 데이터축 시작일(EPOCH). 첫 배치의 누적 스코프 시작점으로 쓴다(§2.3 누적 스코프 —
# 직전 배치가 없으면 데이터셋 전체가 대상. BACKEND_DECISIONS.md D2 참고).
DATA_EPOCH = "2026-01-01"


def app_state_db_path() -> str:
    return os.environ.get("APP_STATE_DB", "./app_state.db")


def fab_db_path() -> str:
    return os.environ["FAB_DB"]
