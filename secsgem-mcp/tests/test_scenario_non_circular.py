# 순환성 회피 검증 — 데이터 빌드(simulator.generate) 이후에만 유효
import json, pathlib
from collections import defaultdict

import pytest

pytestmark = pytest.mark.data   # CI(-m "not data")에서는 제외


def _cards():
    return [json.loads(p.read_text())
            for p in sorted(pathlib.Path("datasets/ground_truth").glob("SC-*.json"))]


def test_defect_alone_underdetermines_cause():
    """같은 결함 패턴에 2개 이상 원인이 존재해야 순환성 회피 성립."""
    cards = _cards()
    assert cards, "ground_truth 없음 — python -m simulator.generate 먼저 실행"
    causes = defaultdict(set)
    for c in cards:
        if not c["is_unmatched"]:
            for pat in c["defect_patterns"]:
                causes[pat].update(c["true_root_causes"])
    single = [p for p, cs in causes.items() if len(cs) < 2]
    assert not single, f"단일 원인 패턴 {single} → 이미지만으로 역산 가능(순환성)"


def test_unmatched_ratio():
    """매칭불가 시나리오가 전체의 10~20% (§4.4-5, P7)."""
    cards = _cards()
    ratio = sum(c["is_unmatched"] for c in cards) / len(cards)
    assert 0.10 <= ratio <= 0.20, f"매칭불가 비율 {ratio:.2f}"
