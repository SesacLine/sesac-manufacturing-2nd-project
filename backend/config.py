"""서버 전역 설정 상수.

EVENT_DATE — API 명세 §1 "고정 기준일"(= 서버시간). batch_id/analysis_id의 {배치날짜}와
배치 시작 시각의 날짜, logs[].time이 파생하는 날짜에 쓰인다. 데이터축 시각(fab.db max(ts)
기준 조회 창)에는 적용하지 않는다.

**서버시간 오버라이드 장치**: 데이터가 2026-01~03월분이라 벽시계 now()를 쓰면 시간이 안
맞는다. 그래서 서버의 "오늘"은 벽시계가 아니라 EVENT_DATE(기본 2026-04-01 = 데이터축 직후)
로 고정하고, 다른 날짜로 테스트하고 싶으면 env `EVENT_DATE=2026-05-01`처럼 오버라이드한다
(.env 또는 셸 환경변수). 코드 어디서도 날짜에 datetime.now()를 쓰지 않는 것이 규약이다
(시각 HH:MM:SS 부분만 now() 허용 — 날짜는 항상 여기서 파생).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

# config가 가장 먼저 import되는 모듈이라 여기서 .env를 로드한다(idempotent) —
# deps.py의 load_dotenv보다 먼저 EVENT_DATE env가 필요하기 때문(모듈 상수 평가 시점).
load_dotenv()

# 명세 §1: 이벤트/조회 시각의 고정 기준일 (데이터축 90일 구간 직후). env로 오버라이드 가능.
EVENT_DATE = os.environ.get("EVENT_DATE", "2026-04-01")
EVENT_DATE_COMPACT = EVENT_DATE.replace("-", "")  # ID 채번용 "20260401"

# 데이터축 시작일(EPOCH). 첫 배치의 누적 스코프 시작점으로 쓴다(§2.3 누적 스코프 —
# 직전 배치가 없으면 데이터셋 전체가 대상. BACKEND_DECISIONS.md D2 참고).
DATA_EPOCH = "2026-01-01"


def app_state_db_path() -> str:
    return os.environ.get("APP_STATE_DB", "./app_state.db")


def fab_db_path() -> str:
    return os.environ["FAB_DB"]
