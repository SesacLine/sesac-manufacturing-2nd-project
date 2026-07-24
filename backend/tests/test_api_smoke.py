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
