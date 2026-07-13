"""P5 — 해석 문구 금지 회귀 테스트. 툴은 사실만, 판단은 에이전트."""
import pytest

pytestmark = pytest.mark.data   # fab.db 필요 — CI(-m "not data")에서는 제외

BANNED = ["원인일 가능성", "때문", "likely cause", "root cause is", "책임"]


def test_tools_return_facts_only(all_tool_responses):
    for resp in all_tool_responses:
        blob = str(resp["data"]).lower()
        assert not any(b.lower() in blob for b in BANNED), "툴이 해석 문구 반환 (P5 위반)"
