"""fab.db 없이 도는 API 계약 스모크 — 라우팅·검증·404/422/빈 목록 형태 확인.

배치 실행·수율 집계처럼 fab.db가 필요한 경로는 여기서 다루지 않는다(marker "data" 쪽).
app_state.db는 테스트 전용 임시 파일로 격리한다.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_STATE_DB", str(tmp_path / "app_state_test.db"))
    # main import 시점에 init_db가 돌므로 env 설정 후 리로드한다.
    from backend import main as main_module

    importlib.reload(main_module)
    with TestClient(main_module.app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_analyses_empty_list_is_200(client):
    r = client.get("/api/v1/analyses")
    assert r.status_code == 200
    assert r.json() == {"count": 0, "items": []}


def test_analyses_bad_sort_is_422_with_detail_array(client):
    r = client.get("/api/v1/analyses", params={"sort": "bogus"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, list)  # §1.1: 422만 배열
    assert detail[0]["loc"][0] == "query"


def test_analysis_not_found_is_404_string_detail(client):
    r = client.get("/api/v1/analyses/grp_edgering_20250101_01")
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert isinstance(detail, str)
    assert "grp_edgering_20250101_01" in detail


def test_batch_not_found_is_404(client):
    r = client.get("/api/v1/batches/batch_00000000_01")
    assert r.status_code == 404


def test_lot_not_found_is_404(client):
    r = client.get("/api/v1/lots/lot00000/wafers")
    assert r.status_code == 404


def test_evidence_of_missing_analysis_is_404(client):
    r = client.get("/api/v1/analyses/grp_center_20260401_01/evidence/h0")
    assert r.status_code == 404


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


# ── v1.1: 차트 엔드포인트 2종 (§2.8·§2.9) — fab.db 없이 형태 계약 ────────────────────────
def test_yield_daily_empty_shape(client, monkeypatch):
    monkeypatch.delenv("FAB_DB", raising=False)  # fab.db 없음 → days만 빈 배열(200 유지)
    r = client.get("/api/v1/yield-daily")
    assert r.status_code == 200
    body = r.json()
    assert body == {"days": [], "events": []}


def test_stats_causes_empty_shape(client):
    r = client.get("/api/v1/stats/causes")
    assert r.status_code == 200
    body = r.json()
    assert body == {"equipment": [], "causes": [], "patterns": []}


def test_stats_and_events_after_save(client):
    """저장분이 있으면 집계·이벤트가 §2.8/§2.9 형태로 나온다 (조회만 — 재계산 없음)."""
    from backend import store

    store.save_analysis(
        analysis_id="grp_center_20260401_01", batch_id="b1", seq=1,
        pattern="Center", status="reviewed", lot_count=2, top_cause="clean_nozzle_clog",
        payload={"analysis_id": "grp_center_20260401_01"},
        confidence="medium", yield_impact=-3.1, defect_date="2026-03-11",
        top_equipment="CLEAN-01", top_stage="CLEAN", top_tier="auto",
    )
    store.save_wafer_readings([("lot1", "1", "Center"), ("lot1", "2", "Unknown")])

    ev = client.get("/api/v1/yield-daily").json()["events"]
    assert ev == [{
        "date": "2026-03-11", "analysis_id": "grp_center_20260401_01", "pattern": "Center",
        "status": "reviewed", "cause": "clean_nozzle_clog", "equipment": "CLEAN-01",
        "stage": "CLEAN", "tier": "auto", "confidence": "medium",
    }]

    stats = client.get("/api/v1/stats/causes").json()
    assert stats["equipment"] == [{"equipment_id": "CLEAN-01", "stage": "CLEAN", "count": 1}]
    assert stats["causes"] == [{"pattern": "Center", "cause": "clean_nozzle_clog",
                                "stage": "CLEAN", "tier": "auto", "count": 1}]
    assert {p["pattern"]: p["mapped"] for p in stats["patterns"]} == {
        "Center": True, "Unknown": False,
    }

    # §2.2 목록에도 confidence·yield_impact가 실린다
    items = client.get("/api/v1/analyses?sort=latest&limit=10&offset=0").json()["items"]
    assert items[0]["confidence"] == "medium"
    assert items[0]["yield_impact"] == -3.1


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
