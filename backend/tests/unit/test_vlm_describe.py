"""③ 관측 생산(observe_groups) — 스켈레톤 폴백 + die_map→quantitative 실경로 + ④ 배선 테스트."""

from __future__ import annotations

import logging

import numpy as np

from backend.nodes import graphrag
from backend.nodes import vlm_describe as vlm_describe_module
from backend.nodes.vlm_describe import (
    _build_observation,
    _observation_from_die_maps,
    _observe_group_live,
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


# --- VLM_LIVE 경로(_observe_group_live) 실패 격리 ---

class _RaisingVLMReader:
    """VLMCallError가 아닌 예외(인증 실패·RateLimitError 등)를 흉내낸다."""

    def describe_group(self, pattern, die_maps):
        raise RuntimeError("401 Unauthorized")


def test_vlm_live_backend_failure_degrades_to_deterministic_observation(monkeypatch):
    """2026-07-27 회귀 — VLM 백엔드가 VLMCallError가 아닌 예외를 던져도 관측은 결정적
    값으로 폴백해야 한다. observe_groups(③)는 배치 그래프 노드라 그룹별 격리(④~⑦ 전용)
    밖이라, 여기서 예외가 새면 그룹 하나의 API 실패가 배치 전체를 status=failed로
    끌고 내려간다 — 좁은 except 시절 실제로 가능했던 경로."""
    monkeypatch.setattr(vlm_describe_module, "_member_keys", lambda *a, **k: [("LOT1", "1")])
    monkeypatch.setattr(
        vlm_describe_module, "_fetch_die_maps_by_keys",
        lambda keys: [np.ones((8, 8), dtype=np.uint8)],
    )
    monkeypatch.setattr(vlm_describe_module, "_get_vlm_reader", lambda: _RaisingVLMReader())

    group = {"group_id": "g1", "pattern": "Center", "lot_ids": ["LOT1"], "status": "ok"}
    result = _observe_group_live(group, {"cnn_results": []})

    assert "vlm_track" not in result["observation"]   # VLM 실생성 흔적 없음 — 결정적 관측만
    assert result["lot_ids"] == ["LOT1"]               # 기존 필드는 보존(예외 삼키다 상태 훼손 없음)


# --- #127 실패 폴백이 조용하지 않아야 한다(caplog) ---

class _StubVLMReader:
    def describe_group(self, pattern, die_maps):
        return {
            "location_text": "center",
            "morphology_text": "blob",
            "total_description": "center blob",
            "vlm_track": "pty",
            "image_mode": "stack",
            "vlm_pattern_guess": pattern,
        }


def _live_warnings(caplog):
    return [r for r in caplog.records if r.levelno == logging.WARNING]


def test_vlm_failure_logs_warning_with_group_id(monkeypatch, caplog):
    """VLM이 죽으면 폴백은 그대로 두되 원인이 로그에 남아야 한다 — 카드에 description이
    없을 때 'VLM 실패'와 '이미지 없음'과 'VLM_LIVE 미설정'을 구분할 수단이 이것뿐이다."""
    monkeypatch.setattr(vlm_describe_module, "_member_keys", lambda *a, **k: [("LOT1", "1")])
    monkeypatch.setattr(
        vlm_describe_module, "_fetch_die_maps_by_keys",
        lambda keys: [np.ones((8, 8), dtype=np.uint8)],
    )
    monkeypatch.setattr(vlm_describe_module, "_get_vlm_reader", lambda: _RaisingVLMReader())

    group = {"group_id": "g1", "pattern": "Center", "lot_ids": ["LOT1"], "status": "ok"}
    with caplog.at_level(logging.WARNING, logger="backend.nodes.vlm_describe"):
        result = _observe_group_live(group, {"cnn_results": []})

    warnings = _live_warnings(caplog)
    assert len(warnings) == 1
    assert "g1" in warnings[0].getMessage()
    assert "401 Unauthorized" in warnings[0].getMessage()   # 어떤 예외였는지까지 남아야 함
    assert "vlm_track" not in result["observation"]         # 폴백 동작은 그대로


def test_missing_die_maps_logs_distinct_warning(monkeypatch, caplog):
    """이미지를 못 읽은 경우도 조용히 넘어가면 안 되고, VLM 실패와 구분돼야 한다."""
    monkeypatch.delenv("FAB_DB", raising=False)
    monkeypatch.setattr(vlm_describe_module, "_member_keys", lambda *a, **k: [("LOT1", "1")])
    monkeypatch.setattr(vlm_describe_module, "_fetch_die_maps_by_keys", lambda keys: [])

    group = {"group_id": "g2", "pattern": "Center", "lot_ids": ["LOT1"], "status": "ok"}
    with caplog.at_level(logging.WARNING, logger="backend.nodes.vlm_describe"):
        result = _observe_group_live(group, {"cnn_results": []})

    warnings = _live_warnings(caplog)
    assert len(warnings) == 1
    assert "g2" in warnings[0].getMessage()
    assert "die_map" in warnings[0].getMessage()            # VLM 실패 메시지와 구분되는 키워드
    assert "vlm_track" not in result["observation"]


def test_vlm_success_logs_no_warning(monkeypatch, caplog):
    """회귀 방지 — 정상 경로에서 경고가 뜨면 로그가 늑대소년이 된다."""
    monkeypatch.setattr(vlm_describe_module, "_member_keys", lambda *a, **k: [("LOT1", "1")])
    monkeypatch.setattr(
        vlm_describe_module, "_fetch_die_maps_by_keys",
        lambda keys: [np.ones((8, 8), dtype=np.uint8)],
    )
    monkeypatch.setattr(vlm_describe_module, "_get_vlm_reader", lambda: _StubVLMReader())

    group = {"group_id": "g3", "pattern": "Center", "lot_ids": ["LOT1"], "status": "ok"}
    with caplog.at_level(logging.WARNING, logger="backend.nodes.vlm_describe"):
        result = _observe_group_live(group, {"cnn_results": []})

    assert _live_warnings(caplog) == []
    assert result["observation"]["vlm_track"] == "pty"
