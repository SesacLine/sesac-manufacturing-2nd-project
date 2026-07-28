"""기동 시 고아 배치 정리(store.reap_orphaned_batches).

배치는 프로세스 안의 asyncio 태스크로 돈다. 서버가 배치 도중 죽으면 태스크는 사라지지만
DB의 `running` 행은 남고, 그 행이 남아 있는 한 배치 시작 가드가 영구히 409를 낸다
(실측 0728 — 4단계 진행 중 서버를 내렸더니 재기동 후 버튼이 먹지 않았다).
여기서 잡고 싶은 건 "재기동하면 그 상태가 저절로 풀리는가"다.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_STATE_DB", str(tmp_path / "app_state.db"))
    from backend import store

    store.init_db()
    yield


def test_running_batch_is_reaped_and_unblocks_the_start_guard():
    """`running` 배치가 남아 있으면 정리되고, 가드가 다시 통과한다."""
    from backend import store

    store.create_batch("batch_20260206_36", seq=36,
                       started_at="2026-02-06T15:22:06Z", cursor_start="2026-02-04")
    assert store.find_batch_by_status(["running"]) is not None  # 가드가 막는 상태

    reaped = store.reap_orphaned_batches()

    assert reaped == ["batch_20260206_36"]
    assert store.find_batch_by_status(["running"]) is None  # 가드 통과

    batch = store.get_batch("batch_20260206_36")
    assert batch["status"] == "failed"
    # 화면2가 이 사유를 그대로 보여준다 — 조용히 사라지면 사용자가 원인을 알 수 없다.
    assert batch["error"] == store.ORPHANED_BATCH_ERROR


def test_reap_is_noop_when_nothing_is_running():
    """정상 기동(고아 없음)에서는 아무것도 건드리지 않는다 — 재시작마다 도는 코드다."""
    from backend import store

    assert store.reap_orphaned_batches() == []

    store.create_batch("batch_20260206_36", seq=36,
                       started_at="2026-02-06T15:22:06Z", cursor_start="2026-02-04")
    store.finish_batch("batch_20260206_36", ["grp_center_20260206_36"])

    assert store.reap_orphaned_batches() == []
    # 완료된 배치를 failed로 되돌리지 않는다.
    assert store.get_batch("batch_20260206_36")["status"] == "completed"
