"""assembler·response 순수함수 계약 — HTTP를 안 타고 함수만 직접 검증한다.

server/test_api_contract.py에서 분리해 나왔다(2026-07-27 테스트 폴더 정리). 그 파일은
TestClient로 라우팅·상태코드를 보고, 여기는 payload 조립·계산식·템플릿 같은 **순수 함수**만
본다 — 계약(§2.5/§2.7 키 집합)이 깨지면 여기가 먼저 빨개진다.

fab.db·app_state.db·네트워크 전부 불필요(CI의 `-m "not data"`에서 그대로 돈다).
"""

from __future__ import annotations

import importlib


def test_batch_response_superset_keys():
    """§2.4 필드 존재 계약 — 7키 superset을 store 레벨에서 확인."""
    from backend.schemas import STEPS

    assert len(STEPS) == 8
    assert STEPS[0] == "lot_selection" and STEPS[7] == "response_gen"


def test_assembler_shapes():
    """assembler가 §2.5/§2.7 키 집합 계약을 지키는지 fab.db 없이 확인."""
    from backend.assembler import build_analysis_payload

    final = {
        "pattern": "Center",
        "status": "reviewed",
        "reason": None,
        "lot_ids": ["lot1", "lot2"],
        "lot_count": 2,
        "hypotheses": [
            {
                "hypothesis_id": "h0",
                "cause": "clean_nozzle_clog",
                "stage": "CLEAN",
                "tier": "자동",
                "verdict": "accepted",
                "verdict_reason": None,
                "equipment": "CLEAN-01",
                "sentence": "테스트 서술",
                "citations": [{"id": 1, "text": "doc"}],
                "evidence": {
                    "commonality_rows": [
                        {"equipment_id": "CLEAN-01", "chamber_id": None,
                         "matched_lots": 2, "total_lots": 2, "ratio": 1.0, "note": None}
                    ],
                    "normal_ratio": 0.2,
                    "telemetry_collected": True,
                    "telemetry_param": "flow_rate",
                    "telemetry_series": [{"ts": "2026-03-11T00:00:00", "value": 900.0}],
                    "telemetry_normal_range": [950, 1050],
                    "drift_detected": True,
                },
            },
            {
                "hypothesis_id": "h1",
                "cause": "unknown_cause",
                "stage": None,
                "tier": "근거없음",
                "verdict": "insufficient",
                "verdict_reason": "KG 메커니즘 연결(VERIFIED_BY) 없음",
                "equipment": None,
                "sentence": "문헌 서술만",
                "citations": [],
                "evidence": {},
            },
        ],
    }
    payload = build_analysis_payload("grp_center_20260401_01", final)

    # §2.5 키 집합
    for key in ("analysis_id", "pattern", "description", "status", "reason",
                "lot_count", "lot_ids", "hypotheses"):
        assert key in payload
    card = payload["hypotheses"][0]
    for key in ("hypothesis_id", "cause", "stage", "tier", "verdict",
                "verdict_reason", "narrative", "next_actions", "citations",
                "cluster_id", "is_primary"):  # R2 원인군 카드용 필드(additive)
        assert key in card
    assert card["tier"] == "auto"  # enum 정규화는 API 경계에서

    # §2.7 키 집합 + available 분기
    ev0 = payload["evidence"]["h0"]
    assert ev0["suspect"] == {"equipment_id": "CLEAN-01", "chamber_id": None}
    assert ev0["sections"]["commonality"]["available"] is True
    tel = ev0["sections"]["telemetry"]
    assert tel["available"] is True and tel["param"] == "flow_rate"
    events = ev0["sections"]["events"]
    assert events["available"] is False and events["reason"] == "not_collected_for_tier"

    ev1 = payload["evidence"]["h1"]
    assert ev1["tier"] == "none"
    assert ev1["sections"]["telemetry"] == {
        "available": False, "reason": "none_tier", "series": []
    }
    assert ev1["note"] is not None


def test_assembler_surfaces_cluster_id_for_grouping():
    """R2 — ⑤가 채운 cluster_id/is_primary가 §2.5 카드로 그대로 흘러가야(프론트 원인군 묶기용)."""
    from backend.assembler import build_analysis_payload

    final = {
        "pattern": "Center",
        "status": "reviewed",
        "reason": None,
        "lot_ids": ["lot1"],
        "lot_count": 1,
        "hypotheses": [
            {"hypothesis_id": "h0", "cause": "clean_nozzle_clog", "stage": "CLEAN",
             "tier": "자동", "verdict": "accepted", "verdict_reason": None,
             "equipment": "CLEAN-01", "sentence": "s", "citations": [], "evidence": {},
             "cluster_id": "CLEAN|low", "is_primary": True},
            {"hypothesis_id": "h1", "cause": "low_chemical_flow_rate", "stage": "CLEAN",
             "tier": "자동", "verdict": "accepted", "verdict_reason": None,
             "equipment": "CLEAN-01", "sentence": "s", "citations": [], "evidence": {},
             "cluster_id": "CLEAN|low", "is_primary": False},
        ],
    }
    payload = build_analysis_payload("grp_center_20260401_01", final)
    c0, c1 = payload["hypotheses"]
    # 같은 cluster_id → 프론트가 한 원인군으로 묶는다
    assert c0["cluster_id"] == c1["cluster_id"] == "CLEAN|low"
    assert c0["is_primary"] is True and c1["is_primary"] is False


def test_assembler_cluster_id_none_when_absent():
    """R2 — ⑤가 cluster_id를 안 채웠으면 None(프론트가 단독 후보로 취급)."""
    from backend.assembler import build_analysis_payload

    final = {
        "pattern": "Scratch", "status": "reviewed", "reason": None,
        "lot_ids": ["lot1"], "lot_count": 1,
        "hypotheses": [
            {"hypothesis_id": "h0", "cause": "c", "stage": "CMP", "tier": "자동",
             "verdict": "accepted", "verdict_reason": None, "equipment": "CMP-01",
             "sentence": "s", "citations": [], "evidence": {}},
        ],
    }
    card = build_analysis_payload("grp_scratch_20260401_01", final)["hypotheses"][0]
    assert card["cluster_id"] is None
    assert card["is_primary"] is False


# ── v1.1: yield_impact 계산식 (compute_yield_impact — 순수함수) ──────────────────────────
def test_compute_yield_impact_group_contribution():
    """impact = Σ(y_lot − 창평균)/N × 100 — 저수율 그룹이 라인 평균을 끌어내린 %p."""
    from backend.assembler import compute_yield_impact

    lot_yields = {"L1": 0.5, "L2": 0.6, "L3": 0.9, "L4": 1.0}  # 창평균 0.75, N=4
    # 그룹 {L1,L2}: (0.5-0.75)+(0.6-0.75) = -0.4 → -0.4/4×100 = -10.0
    assert compute_yield_impact(["L1", "L2"], lot_yields) == -10.0
    # 정상 그룹은 양수(평균 위) — 부호가 방향을 담는다
    assert compute_yield_impact(["L3", "L4"], lot_yields) == 10.0


def test_compute_yield_impact_nullable_when_no_window():
    from backend.assembler import compute_yield_impact

    assert compute_yield_impact(["L1"], {}) is None       # 창 데이터 없음 → Nullable
    assert compute_yield_impact([], {"L1": 0.5}) == 0.0   # 빈 그룹 → 기여 0
    # 창 밖 로트(수율 미상)는 건너뛴다
    assert compute_yield_impact(["없는로트"], {"L1": 0.5, "L2": 0.7}) == 0.0


def test_assembler_exposes_yield_impact_and_actions():
    """v1.1 — payload에 yield_impact(주입값)·actions(⑦ 생성분)가 실린다."""
    from backend.assembler import build_analysis_payload

    final = {
        "pattern": "Center", "status": "reviewed", "reason": None,
        "lot_ids": ["lot1"], "lot_count": 1, "hypotheses": [],
        "yield_impact": -3.8,
        "actions": [{"type": "containment", "hold": True, "text": "격리 검토"}],
    }
    payload = build_analysis_payload("grp_center_20260401_01", final)
    assert payload["yield_impact"] == -3.8
    assert payload["actions"] == [{"type": "containment", "hold": True, "text": "격리 검토"}]
    # 구 저장분(미주입) 폴백 — Nullable/빈 배열
    old = build_analysis_payload("grp_center_20260401_02", {
        "pattern": "Center", "status": "unmapped", "reason": None,
        "lot_ids": [], "lot_count": 0, "hypotheses": [],
    })
    assert old["yield_impact"] is None
    assert old["actions"] == []


# ── v1.1: status novel (Unknown → OSR 분리) ─────────────────────────────────────────────
def test_respond_without_llm_unknown_pattern_is_novel():
    from backend.nodes.response import respond_without_llm

    state = {
        "group_id": "g-unknown", "pattern": "Unknown", "lot_ids": ["L1", "L2"],
        "candidates": [], "critic_result": None,
    }
    fr = respond_without_llm(state)["final_response"]
    assert fr["status"] == "novel"
    assert fr["confidence"] == "low"
    assert fr["hypotheses"] == []
    # novel 조치: 격리(hold) + 재판독·등록 조사
    assert fr["actions"][0]["type"] == "containment" and fr["actions"][0]["hold"] is True
    assert all(a["type"] == "investigation" for a in fr["actions"][1:])


def test_known_pattern_without_candidates_stays_unmapped():
    """기지 패턴 + 후보 0건은 여전히 unmapped(지식 공백) — novel과 구분."""
    from backend.nodes.response import respond_without_llm

    state = {
        "group_id": "g-center", "pattern": "Center", "lot_ids": ["L1"],
        "candidates": [], "critic_result": None,
    }
    assert respond_without_llm(state)["final_response"]["status"] == "unmapped"


def test_group_actions_normal_reading_template():
    """조치 템플릿 단일 소스 — ⑦ 노드를 안 타도 같은 함수에서 문구가 나온다."""
    from backend.nodes.response import group_actions

    actions = group_actions("normal_reading", "Normal", 3, None)
    assert len(actions) == 2
    assert all(a["type"] == "investigation" and a["hold"] is False for a in actions)
    assert "EDS" in actions[0]["text"]


# ── v1.1: 서버시간(EVENT_DATE) env 오버라이드 ──────────────────────────────────────────
def test_event_date_env_override(monkeypatch):
    """EVENT_DATE env로 서버 '오늘'을 바꿀 수 있다(기본 2026-04-01) — 재로드로 검증."""
    from backend import config

    monkeypatch.setenv("EVENT_DATE", "2026-05-15")
    importlib.reload(config)
    try:
        assert config.EVENT_DATE == "2026-05-15"
        assert config.EVENT_DATE_COMPACT == "20260515"
    finally:
        monkeypatch.delenv("EVENT_DATE")
        importlib.reload(config)  # 기본값 복원 — 다른 테스트 오염 방지
    assert config.EVENT_DATE == "2026-04-01"
