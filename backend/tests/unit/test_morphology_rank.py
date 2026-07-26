"""angular_coverage 판별자 재정렬 단위 테스트.

LLM/Neo4j 없이 결정적으로 도는 순수 함수 검증.
"""

from __future__ import annotations

from backend.graph_client.morphology_rank import (
    morphology_penalty,
    rerank_by_observation,
)


def _cand(cause, morphology):
    return {"cause": cause, "morphology": morphology}


FULL = {"density": "high", "continuity": "continuous", "angular_coverage": "full", "clock_positions": []}
PARTIAL = {"density": "low", "continuity": "discontinuous", "angular_coverage": "partial", "clock_positions": [5, 6, 7]}


def test_no_observation_preserves_order():
    cands = [_cand("a", FULL), _cand("b", PARTIAL)]
    out = rerank_by_observation(cands, None)
    assert [c["cause"] for c in out] == ["a", "b"]


def test_strong_contradiction_is_dropped():
    # 관측 = partial arc. full-ring 후보(a)는 강한 모순(-10) → 리스트에서 제외, partial(b)만 남음.
    obs = PARTIAL
    cands = [_cand("a", FULL), _cand("b", PARTIAL)]
    out = rerank_by_observation(cands, obs)
    assert [c["cause"] for c in out] == ["b"]        # a 드롭됨
    assert out[0]["morphology_score"] == 0.0         # partial 일치 → 무벌점


def test_drop_can_be_disabled_for_debug():
    # drop_contradictions=False면 옛 동작(강등만) — 모순 후보가 남되 맨 아래로.
    obs = PARTIAL
    cands = [_cand("a", FULL), _cand("b", PARTIAL)]
    out = rerank_by_observation(cands, obs, drop_contradictions=False)
    assert [c["cause"] for c in out] == ["b", "a"]
    assert out[1]["morphology_score"] <= -10.0


def test_soft_contradiction_is_not_dropped():
    # clock/density/continuity만 어긋나면(합 -5까지) 강한 모순 아님 → 남긴다(감점만).
    obs = {"angular_coverage": "partial", "clock_positions": [1, 2], "density": "high"}
    cand_soft = {"angular_coverage": "partial", "clock_positions": [7, 8], "density": "low"}  # -3-1=-4
    out = rerank_by_observation([_cand("a", cand_soft)], obs)
    assert [c["cause"] for c in out] == ["a"]         # 드롭 안 됨
    assert out[0]["morphology_score"] == -4.0


def test_demote_only_never_promotes_over_evidence():
    # 완전 일치해도 점수는 0(중립). 근거 기반 원래 순서를 인위적으로 끌어올리지 않는다.
    obs = FULL
    cands = [_cand("strong_step_route", None), _cand("matching_signature", FULL)]
    out = rerank_by_observation(cands, obs)
    assert [c["cause"] for c in out] == ["strong_step_route", "matching_signature"]
    assert all(c["morphology_score"] == 0.0 for c in out)


def test_no_morphology_candidate_is_neutral():
    # step/direct 경로(morphology=None)는 어떤 관측에도 0점 → 순서에 영향 없음.
    assert morphology_penalty(PARTIAL, None) == 0.0


def test_partial_clock_disjoint_small_penalty():
    obs = {"angular_coverage": "partial", "clock_positions": [1, 2]}
    cand = {"angular_coverage": "partial", "clock_positions": [7, 8]}
    # angular 일치(partial==partial)라 판별자 무벌점, 시계만 완전히 어긋나 소폭 감점.
    assert morphology_penalty(obs, cand) == -3.0


def test_unknown_is_skipped():
    obs = {"angular_coverage": "unknown", "density": "high", "continuity": "unknown"}
    cand = {"angular_coverage": "full", "density": "low", "continuity": "continuous"}
    # angular/continuity는 unknown이라 건너뛰고, density만 상충 → -1.
    assert morphology_penalty(obs, cand) == -1.0
