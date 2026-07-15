# M4 E2E 스모크 테스트 — 시나리오 ID는 generate.py의 SC-{패턴}-{NN} 체계와 일치해야 함
import pytest

pytestmark = pytest.mark.data   # fab.db + ground_truth 필요 — CI(-m "not data")에서는 제외


@pytest.fixture
def run_pipeline():
    """진단 파이프라인 진입점 — 스켈레톤(sesac-manufacturing-2nd-project) 연동 후 교체."""
    pytest.skip("run_pipeline 미구현 — M4 에이전트 파이프라인 연동 후 활성화")


@pytest.mark.parametrize("scenario_id, expect", [
    ("SC-EDGE-RING-01", "adopt_etch"),      # §8.1 지지 신호 → 식각 채택 (etch_nonuniformity)
    ("SC-CENTER-02",    "reject_trap"),     # §8.2 route 공유 함정(LITHO) 기각 (무이벤트 누적형)
    ("SC-UNMATCHED-01", "judge_unknown"),   # 매칭불가 → 판단불가+확인항목
])
def test_end_to_end(scenario_id, expect, run_pipeline):
    out = run_pipeline(scenario_id)
    assert out.verdict == expect
    assert out.has_next_actions_section
