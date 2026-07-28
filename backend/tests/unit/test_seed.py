"""데모 시딩(backend/seed.py) — 설정 해석과 "목표까지 따라잡기" 규칙.

실배치는 돌리지 않는다(LLM·MCP 필요). run_batch를 가짜로 바꿔 커서만 전진시키고,
seed가 **몇 번·어느 구간을 돌리는지**만 본다 — 여기서 잡고 싶은 건 배치 내용이 아니라
"언제 멈추고 언제 이어서 도는가"라는 제어 규칙이다.
"""

from __future__ import annotations

import asyncio
import datetime

import pytest

from backend import seed


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_STATE_DB", str(tmp_path / "app_state.db"))
    from backend import store

    store.init_db()
    yield


def _fake_batch_runner(monkeypatch, data_max: str):
    """run_batch를 "커서를 하루 전진시키고 completed로 만드는" 가짜로 대체한다."""
    from backend import batch_runner, store

    def pending_range() -> tuple[str, str]:
        cursor = store.get_cursor()
        end = min(data_max, (datetime.date.fromisoformat(seed.event_date_for(cursor))
                             - datetime.timedelta(days=1)).isoformat())
        return cursor, end

    async def run_batch(batch_id, kg_client, mcp):
        _start, end = pending_range()
        store.finish_batch(batch_id, result_ids=[])
        store.set_cursor(end)

    monkeypatch.setattr(batch_runner, "pending_range", pending_range)
    monkeypatch.setattr(batch_runner, "run_batch", run_batch)


# ── SEED_UNTIL 해석 ────────────────────────────────────────────────────────────────────
def test_seed_off_by_default(monkeypatch):
    """미설정이면 기능 자체가 꺼진다 — CI·운영에서 실수로 돌지 않게 하는 기본값."""
    monkeypatch.delenv("SEED_UNTIL", raising=False)
    assert seed.seed_target() is None


def test_malformed_date_disables_seeding_instead_of_crashing(monkeypatch):
    """날짜가 아니면 기동을 죽이지 말고 시딩만 끈다(서버는 계속 떠야 한다)."""
    monkeypatch.setenv("SEED_UNTIL", "2026/02/08")
    assert seed.seed_target() is None


# ── 따라잡기 규칙 ──────────────────────────────────────────────────────────────────────
def test_seeds_one_batch_per_day_from_empty_db(monkeypatch):
    """빈 DB → 커서를 EPOCH 전날에 심고 **하루 한 배치씩** 목표까지."""
    from backend import store

    _fake_batch_runner(monkeypatch, data_max="2026-03-30")
    ran = asyncio.run(seed.catch_up_to("2026-01-05", None, None))

    assert store.get_cursor() == "2026-01-05"
    assert ran == 5, "1/1~1/5 = 5배치 (한 방에 삼키면 1이 된다 — D2 캐치업 회귀)"


def test_moving_target_forward_seeds_only_the_gap(monkeypatch):
    """SEED_UNTIL을 뒤로 옮기면 **차이 구간만** 이어서 돈다(날짜 변경이 곧 반영)."""
    from backend import store

    _fake_batch_runner(monkeypatch, data_max="2026-03-30")
    asyncio.run(seed.catch_up_to("2026-01-05", None, None))

    ran = asyncio.run(seed.catch_up_to("2026-01-08", None, None))
    assert ran == 3, "1/6~1/8만"
    assert store.get_cursor() == "2026-01-08"


def test_reaching_target_is_idempotent(monkeypatch):
    """이미 도달했으면 no-op — 재시작·다중 기동에 안전해야 한다."""
    _fake_batch_runner(monkeypatch, data_max="2026-03-30")
    asyncio.run(seed.catch_up_to("2026-01-05", None, None))

    assert asyncio.run(seed.catch_up_to("2026-01-05", None, None)) == 0
    assert asyncio.run(seed.catch_up_to("2026-01-03", None, None)) == 0, "목표가 과거여도 되돌리지 않는다"


def test_stops_at_end_of_data(monkeypatch):
    """데이터축을 넘겨 잡아도 있는 데까지만 돌고 멈춘다(빈 배치 무한 반복 금지)."""
    from backend import store

    _fake_batch_runner(monkeypatch, data_max="2026-01-03")
    ran = asyncio.run(seed.catch_up_to("2026-02-28", None, None))

    assert store.get_cursor() == "2026-01-03"
    assert ran == 3
