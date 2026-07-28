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


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
