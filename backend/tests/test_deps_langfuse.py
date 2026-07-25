"""deps의 Langfuse 게이트 팩토리 배선 테스트.

싱글턴 모듈이라 각 테스트 앞에서 로드 상태를 리셋한다. Langfuse 서버는 부르지 않는다 —
게이트가 실체를 만들기 전에 None으로 빠지는 두 경로(트레이싱 off / 키 없음)만 검증한다.
(핸들러 실체·콜백 주입·flush·전파는 테스트가 아니라 Langfuse UI 육안 검증 — 플랜 §구현방법론.)

핵심: 개발자 .env에 LANGFUSE_TRACING=1 + 키가 있어도, monkeypatch로 env를 테스트 안에서
직접 제어하므로 결정적으로 통과한다(.env 내용에 의존하지 않는다).
"""

from __future__ import annotations

import pytest

from backend import deps


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch):
    monkeypatch.setattr(deps, "_langfuse_handler", None)
    monkeypatch.setattr(deps, "_langfuse_checked", False)


def test_langfuse_handler_disabled_by_default_and_without_keys(monkeypatch):
    # (1) LANGFUSE_TRACING 미설정 → None. 키가 있어도 게이트가 먼저 막는다(off가 기본).
    monkeypatch.delenv("LANGFUSE_TRACING", raising=False)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    assert deps.langfuse_handler() is None

    # 캐시 리셋 — 두 번째 호출이 캐시된 None을 그냥 돌려주지 않고 실제로 키-없음 분기를 타게 한다.
    monkeypatch.setattr(deps, "_langfuse_handler", None)
    monkeypatch.setattr(deps, "_langfuse_checked", False)

    # (2) LANGFUSE_TRACING=1인데 키 없음 → None(트레이싱 비활성).
    monkeypatch.setenv("LANGFUSE_TRACING", "1")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert deps.langfuse_handler() is None
