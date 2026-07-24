"""실제 시나리오 기준 KG recall 회귀 테스트 — ground_truth/*.json 기반.

test_recall_regression.py가 "시뮬레이터가 **주입할 수 있는** 원인 어휘(mapping_table 9쌍)"를
보는 데 비해, 이 파일은 ground_truth가 **실제로 주입한** 시나리오를 본다. 둘의 차이:

  - 어휘 커버리지(9쌍)  : 시뮬레이터가 낼 수 있는 모든 정답을 KG가 아는가 (상한 점검)
  - 시나리오 recall(이 파일): 이번 문제지(11개)의 정답을 KG가 실제로 후보에 올리는가 (실전 점검)

ground_truth의 정답(true_root_causes)과 KG 후보의 matched_cause는 둘 다 시뮬레이터 어휘
(= golden에 고정)라 바로 대조된다. 이 테스트도 KG 조회(존재 여부)만 보므로 fab.db·관측이 필요 없다
— 순위·검증(⑤/⑥)까지 가는 SC-CENTER-01 파이프라인 골든(top-1 + P2 기각)은 별도 -m data 몫.

ground_truth는 시뮬레이터 산출물(seed 20260101 스냅샷)이다. 폴더가 없으면 전체 skip한다
— 커밋 안 한 환경에서도 CI가 죽지 않게. 재빌드(다른 seed)하면 시나리오가 표류할 수 있다.

known_miss는 golden/recall_cases.yaml을 단일 진실로 재사용한다(중복 선언 금지).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

_HERE = Path(__file__).resolve().parent
_GT_DIR = _HERE / "ground_truth"
_GOLDEN = _HERE / "golden" / "recall_cases.yaml"


def _known_miss_causes() -> set[str]:
    """golden에서 known_miss로 선언된 cause 집합 — 두 테스트가 공유하는 단일 진실."""
    if not _GOLDEN.exists():
        return set()
    golden = yaml.safe_load(_GOLDEN.read_text(encoding="utf-8"))
    return {c["gold_cause"] for c in golden["cases"] if c.get("known_miss")}


def _matched_scenarios() -> list[dict]:
    """정답이 있는(is_unmatched=False) 시나리오만. 폴더 없으면 빈 리스트(→ 전체 skip)."""
    if not _GT_DIR.exists():
        return []
    out = []
    for path in sorted(_GT_DIR.glob("*.json")):
        gt = json.loads(path.read_text(encoding="utf-8"))
        if not gt.get("is_unmatched") and gt.get("true_root_causes"):
            out.append(gt)
    return out


def _scenario_params():
    """시나리오별 파라미터. 정답 cause가 known_miss면 strict xfail로 표시."""
    known_miss = _known_miss_causes()
    params = []
    for gt in _matched_scenarios():
        sid = gt["scenario_id"]
        pattern = gt["defect_patterns"][0]
        cause = gt["true_root_causes"][0]
        marks = []
        if cause in known_miss:
            # 매핑이 고쳐져 recall되기 시작하면 XPASS로 실패 → 골든의 known_miss 갱신 알림.
            marks.append(pytest.mark.xfail(
                reason=f"{cause}는 golden known_miss — 매핑 매칭 실패", strict=True))
        params.append(pytest.param(pattern, cause, marks=marks, id=sid))
    return params


_PARAMS = _scenario_params()


@pytest.mark.skipif(not _PARAMS, reason="ground_truth 폴더 없음 — 시뮬레이터 빌드 산출물 배치 필요")
@pytest.mark.parametrize("pattern, cause", _PARAMS)
def test_scenario_cause_recalled(pattern, cause, matched_causes_by_pattern):
    """이 시나리오의 정답 원인을 KG가 후보의 matched_cause로 떠올리는가.

    실패 = 시스템이 이 시나리오를 end-to-end로 절대 못 맞힌다는 뜻(정답이 후보에 없으니
    뒤 단계가 아무리 똑똑해도 소용없음). 정답이 여럿(중복 시나리오)이어도 각 시나리오가
    독립 케이스라 자연히 처리된다.
    """
    surfaced = matched_causes_by_pattern.get(pattern, set())
    assert cause in surfaced, (
        f"{pattern} 시나리오의 정답 '{cause}'가 KG 후보의 matched_cause에 없음 "
        f"— 이 시나리오는 현재 recall 불가"
    )


def test_scenario_causes_covered_by_golden():
    """ground_truth 정답이 전부 golden 어휘 안인가 (golden ⊇ 실제 시나리오 정답).

    golden과 ground_truth는 둘 다 시뮬레이터(mapping_table)에서 나온 kg_rca 내부 스냅샷이다.
    이 테스트가 그 둘의 정합을 지킨다 — secsgem-mcp를 읽지 않고도 드리프트를 잡는 자리다:
    시뮬레이터에 새 원인을 넣고 ground_truth를 재빌드했는데 golden을 안 고치면, 여기서
    "golden 밖 시나리오 정답"으로 걸린다 → golden부터 갱신하라는 신호(안 그러면 recall 대조가
    matched_cause 번역 불가로 무의미해진다).
    """
    scenarios = _matched_scenarios()
    if not scenarios:
        pytest.skip("ground_truth 폴더 없음")
    if not _GOLDEN.exists():
        pytest.skip("golden 없음")
    golden = yaml.safe_load(_GOLDEN.read_text(encoding="utf-8"))
    golden_pairs = {(c["pattern"], c["gold_cause"]) for c in golden["cases"]}
    scenario_pairs = {(gt["defect_patterns"][0], gt["true_root_causes"][0]) for gt in scenarios}
    unknown = scenario_pairs - golden_pairs
    assert not unknown, f"golden 밖의 시나리오 정답: {sorted(unknown)} — golden 재생성 필요"
