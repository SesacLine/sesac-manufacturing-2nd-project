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

import datetime
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


def event_date_for(cursor: str | None) -> str:
    """서버가 인식하는 "오늘". 배치를 돌릴 때마다 하루씩 앞으로 간다.

    이 서비스는 "아침에 한 번 눌러 **전날** 하루치를 본다"라, 마지막으로 분석한 날(cursor)이
    곧 "어제"다 → 오늘 = cursor + 1일. 그리고 다음 배치의 대상은 그 오늘의 전날이 아니라
    **아직 분석 안 한 다음 날**이므로, 오늘을 한 번 더 밀어 cursor + 2일로 잡는다:

        cursor=2/4  →  오늘 2/6, 대상 2/5   (2/5를 분석하고 cursor=2/5)
        cursor=2/5  →  오늘 2/7, 대상 2/6   (버튼을 다시 누르면 자동으로 다음 날)

    커서가 없으면(배치 이력 없음) env의 EVENT_DATE를 그대로 쓴다 — 첫 배치는 그 전날까지를
    한 번에 따라잡는 캐치업이라 기준점이 필요하다.

    벽시계는 여전히 안 쓴다(§1) — 커서도 EVENT_DATE도 데이터축 날짜다.
    """
    if cursor is None:
        return EVENT_DATE
    return (datetime.date.fromisoformat(cursor) + datetime.timedelta(days=2)).isoformat()


def compact(date_str: str) -> str:
    """ID 채번용 "YYYY-MM-DD" → "YYYYMMDD"."""
    return date_str.replace("-", "")


def app_state_db_path() -> str:
    return os.environ.get("APP_STATE_DB", "./app_state.db")


def fab_db_path() -> str:
    return os.environ["FAB_DB"]
