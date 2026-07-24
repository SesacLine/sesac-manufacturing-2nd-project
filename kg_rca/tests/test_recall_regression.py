"""KG 검색 품질 회귀 테스트 — 골든셋(golden/recall_cases.yaml) 기반.

목적: KG를 재빌드했을 때 "시뮬레이터가 주입할 수 있는 정답 원인"을 여전히 후보로
떠올리는지 감시한다. **절대 성능이 아니라 떨어지면 알림**이 목적(회귀 가드).

두 층으로 검사한다:
  1. coverage(이 파일, CI) — 정답 cause가 그 pattern의 KG 후보 어딘가에 matched_cause로
     존재하는가. fab.db·관측 불필요 → CI에서 돈다. 재빌드가 정답을 후보에서 잃으면 fail.
  2. recall@k(top-k 순위, 미구현) — 관측 없이는 무의미하다. raw hypotheses.json은 문헌
     빈도순이라 정답이 rank 35~367에 있어 recall@20=0. 실제 순위는 ③ 관측 morphology
     재랭킹 + ⑤ fab 재랭킹이 만든다 → 관측/fab이 필요한 별도 -m data 테스트 몫(§note).

대조 키는 candidate.matched_cause다(cause 아님). KG cause 문자열과 시뮬레이터 어휘는
표기가 달라 직접 비교하면 0%가 나오고, mapping.matched_cause가 둘을 잇는 번역 키다.

정본: golden/recall_cases.yaml (kg_rca 내부 committed 스냅샷 — 이 테스트는 secsgem-mcp를
읽지 않는다. 골든의 출처(mapping_table.yaml)는 YAML 헤더에 문서로만 남긴다).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# matched_causes_by_pattern fixture는 conftest.py에 있다.

_KG_ROOT = Path(__file__).resolve().parents[1]
_GOLDEN = Path(__file__).resolve().parent / "golden" / "recall_cases.yaml"


# ============================================================
# fixtures
# ============================================================

@pytest.fixture(scope="session")
def golden() -> dict:
    if not _GOLDEN.exists():
        pytest.skip(f"골든셋 없음({_GOLDEN.name})")
    return yaml.safe_load(_GOLDEN.read_text(encoding="utf-8"))


# matched_causes_by_pattern fixture는 conftest.py로 이동(test_scenario_recall.py와 공유).


def _cases(golden: dict) -> list[dict]:
    return golden["cases"]


# ============================================================
# 골든셋 자체 정합 (kg_rca 내부만 — secsgem-mcp 미참조)
#   출처(mapping_table.yaml)와의 대조는 컴포넌트 경계를 넘으므로 하지 않는다. 대신
#   ground_truth와의 정합(golden ⊇ 실제 시나리오 정답)을 test_scenario_recall.py가 잡는다.
# ============================================================

_PATTERNS = {"Center", "Scratch", "Edge-Ring"}


def test_golden_is_well_formed(golden):
    """golden이 구조적으로 온전한가 — 패턴 3종 소속, 중복 없음, 각 패턴 최소 1건.

    출처 표류 감지(새 원인이 시뮬레이터에 생겼는지)는 여기서 못 한다(경계 밖). 그건
    ground_truth가 witness다 — test_scenario_recall.py가 "실제 시나리오 정답이 golden 안에
    있나"로 잡는다. 시뮬레이터에 원인을 추가하면 ground_truth 재빌드 → 그 테스트가 알림.
    """
    cases = golden["cases"]
    assert cases, "golden에 케이스가 없음"
    pairs = [(c["pattern"], c["gold_cause"]) for c in cases]
    bad = {p for p, _ in pairs} - _PATTERNS
    assert not bad, f"golden에 미정의 pattern: {bad}"
    assert len(pairs) == len(set(pairs)), "golden에 중복 (pattern, cause)"
    covered_patterns = {p for p, _ in pairs}
    assert covered_patterns == _PATTERNS, f"패턴 누락: {_PATTERNS - covered_patterns}"


# ============================================================
# coverage — 정답 cause가 KG 후보에 matched_cause로 존재하는가
# ============================================================

def _covered(case: dict, matched: dict[str, set[str]]) -> bool:
    return case["gold_cause"] in matched.get(case["pattern"], set())


def test_coverage_above_threshold(golden, matched_causes_by_pattern):
    """정답 원인 커버리지가 골든에 박은 하한 이상인가 — 이 파일의 핵심 게이트.

    이 선이 무너지면 = 재빌드가 정답 원인을 후보에서 잃었다는 신호(순위가 아니라 존재).
    known_miss(현재 미커버로 알려진) 케이스도 분모에 포함해 실제 커버리지를 정직하게 센다.
    """
    cases = _cases(golden)
    covered = [c for c in cases if _covered(c, matched_causes_by_pattern)]
    floor = golden["thresholds"]["coverage_min"]
    missing = [c["gold_cause"] for c in cases if not _covered(c, matched_causes_by_pattern)]
    assert len(covered) >= floor, (
        f"coverage {len(covered)}/{len(cases)} < 하한 {floor} — "
        f"미커버: {missing}"
    )


def _case_params(known_miss: bool):
    """collection 시점에 golden을 직접 읽어 케이스별 파라미터를 만든다(known_miss로 분기)."""
    if not _GOLDEN.exists():
        return []
    golden = yaml.safe_load(_GOLDEN.read_text(encoding="utf-8"))
    params = []
    for c in golden["cases"]:
        is_miss = bool(c.get("known_miss"))
        if is_miss != known_miss:
            continue
        marks = []
        if is_miss:
            # strict xfail: 매핑이 고쳐져 커버되기 시작하면 XPASS로 실패시켜 골든 갱신을 강제.
            marks.append(pytest.mark.xfail(reason=c.get("note", "known_miss"), strict=True))
        params.append(pytest.param(c["pattern"], c["gold_cause"], marks=marks,
                                    id=f"{c['pattern']}:{c['gold_cause']}"))
    return params


@pytest.mark.parametrize("pattern, gold_cause", _case_params(known_miss=False))
def test_each_gold_cause_covered(pattern, gold_cause, matched_causes_by_pattern):
    """케이스별 커버리지 — 어느 정답이 빠졌는지 개별로 드러낸다(집계 게이트의 보조)."""
    assert gold_cause in matched_causes_by_pattern.get(pattern, set()), (
        f"{pattern}의 정답 '{gold_cause}'가 KG 후보의 matched_cause에 없음"
    )


@pytest.mark.parametrize("pattern, gold_cause", _case_params(known_miss=True))
def test_known_miss_still_missing(pattern, gold_cause, matched_causes_by_pattern):
    """known_miss로 표시된 케이스 — 지금은 실패(xfail)가 정상.

    매핑이 고쳐져 이게 통과하기 시작하면 strict xfail이 XPASS로 뒤집혀 실패한다
    → 골든의 known_miss 표시를 걷어내라는 알림. '조용히 좋아짐'을 놓치지 않기 위함.
    """
    assert gold_cause in matched_causes_by_pattern.get(pattern, set()), (
        f"{pattern}의 '{gold_cause}'는 아직 미커버(known_miss) — 예상된 실패"
    )
