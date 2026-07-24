"""③ 관측 생산(observe_groups) — 스켈레톤 폴백 + die_map→quantitative 실경로 + ④ 배선 테스트."""

from __future__ import annotations

import numpy as np

from backend.nodes import graphrag
from backend.nodes.vlm_describe import (
    _build_observation,
    _observation_from_die_maps,
    observe_groups,
)


def _state(patterns):
    return {
        "groups": [
            {"group_id": f"{p}-2026-01-05", "pattern": p, "lot_ids": ["LOT1"], "status": "ok"}
            for p in patterns
        ]
    }


# --- 합성 die_map (0/1/2) — quantitative 실경로 검증용 ---
_SIZE = 64


def _die_map(defect_mask_fn) -> np.ndarray:
    yy, xx = np.mgrid[0:_SIZE, 0:_SIZE]
    cy = cx = (_SIZE - 1) / 2
    r = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2) / (_SIZE / 2)
    arr = np.zeros((_SIZE, _SIZE), dtype=np.uint8)
    die = r <= 1.0
    arr[die] = 1
    arr[die & defect_mask_fn(r, yy, xx, cy, cx)] = 2
    return arr


def test_every_group_gets_observation_and_keeps_fields():
    out = observe_groups(_state(["Center", "Edge-Ring", "Scratch"]))
    assert len(out["groups"]) == 3
    for group in out["groups"]:
        assert group["lot_ids"] == ["LOT1"]                      # 기존 필드 보존
        obs = group["observation"]
        assert obs["pattern_candidate"] == group["pattern"]


def test_known_pattern_template_is_meaningful():
    out = observe_groups(_state(["Edge-Ring"]))
    obs = out["groups"][0]["observation"]
    assert "edge" in obs["location_text"]                        # 의미 진입이 닿을 어휘
    assert "ring" in obs["morphology_text"]
    assert obs["angular_coverage"] == "full"
    assert obs["clock_positions"] == []


def test_unknown_pattern_gets_minimal_observation():
    # 자연어를 지어내지 않는다 — 빈 텍스트면 LiveKGClient가 candidates=[]로 UC-3 흐름.
    out = observe_groups(_state(["Donut"]))
    obs = out["groups"][0]["observation"]
    assert obs["pattern_candidate"] == "Donut"
    assert obs["location_text"] == "" and obs["morphology_text"] == ""


def test_observations_are_independent_copies():
    out = observe_groups(_state(["Center", "Center"]))
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
    state = observe_groups(_state(["Edge-Ring"]))                # ③이 만든 groups를
    kg = _CapturingKG()
    # #33 평탄화: ④는 배치 groups가 아니라 그룹 1건짜리 GroupState를 받는다.
    graphrag.fetch_graphrag_candidates(state["groups"][0], kg)   # ④가 소비
    (pattern, observation), = kg.calls
    assert pattern == "Edge-Ring"
    assert observation is not None
    assert observation["angular_coverage"] == "full"             # 관측이 실제로 도달


# --- die_map → quantitative 실경로 ---

def test_die_maps_edge_ring_produces_signature_and_structured():
    maps = [_die_map(lambda r, yy, xx, cy, cx: r >= 0.82) for _ in range(3)]
    obs = _observation_from_die_maps("Edge-Ring", maps)
    assert obs["signature"] == "ring@edge"          # quantitative가 shape@zone 직접 산출 → enum 진입
    assert obs["angular_coverage"] == "full"
    assert obs["defect_die_ratio"] > 0
    assert obs["location_text"] == ""               # VLM 미연동 — 자연어 없음(signature로 진입)


def test_die_maps_partial_arc_gives_partial_and_clock():
    def arc(r, yy, xx, cy, cx):
        return (r >= 0.72) & (yy - cy > 0.5 * np.abs(xx - cx))
    maps = [_die_map(arc) for _ in range(3)]
    obs = _observation_from_die_maps("Edge-Ring", maps)
    assert obs["signature"] == "ring@edge"
    assert obs["angular_coverage"] == "partial"
    assert obs["clock_positions"] != []


def test_no_defect_die_maps_falls_back_to_skeleton():
    maps = [_die_map(lambda r, yy, xx, cy, cx: np.zeros_like(r, dtype=bool)) for _ in range(2)]
    obs = _observation_from_die_maps("Edge-Ring", maps)
    assert "signature" not in obs                   # 결함 0 → 스켈레톤(구조화 신호 없음)
    assert obs["angular_coverage"] == "full"        # 스켈레톤 템플릿 값


def test_build_observation_fallback_without_fab_db(monkeypatch):
    monkeypatch.delenv("FAB_DB", raising=False)     # fab.db 없음 → 스켈레톤 폴백
    obs = _build_observation("Edge-Ring", ["LOT1"])
    assert "signature" not in obs
    assert obs["location_text"]                      # 스켈레톤 자연어 존재
