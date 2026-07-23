"""③ VLM description 생성 스켈레톤(describe_groups) + ④로의 배선 테스트."""

from __future__ import annotations

from backend.nodes import graphrag
from backend.nodes.describer import describe_groups


def _state(patterns):
    return {
        "groups": [
            {"group_id": f"{p}-2026-01-05", "pattern": p, "lot_ids": ["LOT1"], "status": "ok"}
            for p in patterns
        ]
    }


def test_every_group_gets_observation_and_keeps_fields():
    out = describe_groups(_state(["Center", "Edge-Ring", "Scratch"]))
    assert len(out["groups"]) == 3
    for group in out["groups"]:
        assert group["lot_ids"] == ["LOT1"]                      # 기존 필드 보존
        obs = group["observation"]
        assert obs["pattern_candidate"] == group["pattern"]


def test_known_pattern_template_is_meaningful():
    out = describe_groups(_state(["Edge-Ring"]))
    obs = out["groups"][0]["observation"]
    assert "edge" in obs["location_text"]                        # 의미 진입이 닿을 어휘
    assert "ring" in obs["morphology_text"]
    assert obs["angular_coverage"] == "full"
    assert obs["clock_positions"] == []


def test_unknown_pattern_gets_minimal_observation():
    # 자연어를 지어내지 않는다 — 빈 텍스트면 LiveKGClient가 candidates=[]로 UC-3 흐름.
    out = describe_groups(_state(["Donut"]))
    obs = out["groups"][0]["observation"]
    assert obs["pattern_candidate"] == "Donut"
    assert obs["location_text"] == "" and obs["morphology_text"] == ""


def test_observations_are_independent_copies():
    out = describe_groups(_state(["Center", "Center"]))
    a, b = (g["observation"] for g in out["groups"])
    a["density"] = "low"
    assert b["density"] == "high"                                # 템플릿 공유 변조 없음


class _CapturingKG:
    def __init__(self):
        self.calls = []

    def get_candidates(self, pattern, observation=None):
        self.calls.append((pattern, observation))
        return {"pattern": pattern, "candidates": []}


def test_graphrag_passes_observation_to_kg_client():
    state = describe_groups(_state(["Edge-Ring"]))                # ③이 만든 groups를
    kg = _CapturingKG()
    graphrag.fetch_graphrag_candidates(state, kg)                # ④가 소비
    (pattern, observation), = kg.calls
    assert pattern == "Edge-Ring"
    assert observation is not None
    assert observation["angular_coverage"] == "full"             # 관측이 실제로 도달
