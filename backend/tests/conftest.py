"""backend 테스트 공용 fixture."""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# ⚠️ 데모 시딩은 테스트에서 **절대** 돌면 안 된다. TestClient는 lifespan을 실행하므로,
# 개발자 .env에 SEED_UNTIL이 있으면 테스트가 진짜 배치(LLM 과금·수 분)를 돌려버린다.
# CI에는 .env가 없어 원래 안전하지만, 로컬에서만 터지는 사고는 발견이 늦다 — 여기서 끈다.
os.environ.pop("SEED_UNTIL", None)

# ⚠️ 같은 이유로 EVENT_DATE도 테스트 기준값으로 고정한다.
# 테스트는 배치/분석 ID의 날짜 파생(`grp_center_20260401_01` 등)을 검증하므로 명세 §1의
# 기본 기준일(2026-04-01)을 전제한다. 그런데 데모용 .env는 EVENT_DATE를 다른 날짜로 두므로
# (0728 현재 2026-02-06), 로컬에서만 그 값이 새어 들어와 ID 관련 테스트가 무더기로 깨졌다.
# CI는 .env가 없어 통과 → "로컬만 빨간" 상태가 방치되기 쉽다.
#
# pop이 아니라 **명시 대입**인 이유: backend/config.py가 import마다 load_dotenv()를 부르는데,
# load_dotenv는 이미 있는 값은 덮지 않지만 **없으면 파일에서 채운다**. 지워두면 config를
# import(또는 reload)하는 순간 .env의 값이 되돌아온다. 값을 박아둬야 그 경로가 막힌다.
os.environ["EVENT_DATE"] = "2026-04-01"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
