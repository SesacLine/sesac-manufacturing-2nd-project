"""fab.db 없이 도는 API 계약 스모크 — TestClient로 라우팅·검증·404/422/빈 목록 형태 확인.

배치 실행·수율 집계처럼 fab.db가 필요한 경로는 여기서 다루지 않는다(marker "data" 쪽 —
실배치 HTTP 관통은 `../e2e/test_e2e_batch_http.py`). app_state.db는 테스트 전용 임시 파일로
격리한다.

payload 조립·계산식·조치 템플릿 같은 **순수 함수** 검증은 `../unit/test_assembler.py`로
분리했다(2026-07-27 테스트 폴더 정리) — 이 파일은 HTTP를 타는 것만 남긴다.
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


def test_batches_today_shape_and_route_order(client, monkeypatch):
    """§2.3 부속 — 'today'가 batch_id로 잡히지 않고(라우트 순서) 5키를 준다.

    fab.db가 없는 환경이라 대상 구간은 null로 떨어지지만 today는 커서에서 계산되므로
    항상 나온다. 배치 이력이 없으니 done=False.
    """
    monkeypatch.delenv("FAB_DB", raising=False)
    r = client.get("/api/v1/batches/today")
    assert r.status_code == 200  # 404면 /batches/{batch_id}가 먼저 잡은 것
    body = r.json()
    assert set(body) == {"today", "target_from", "target_to", "done", "batch_id"}
    assert body["done"] is False and body["batch_id"] is None
    assert body["today"].count("-") == 2  # YYYY-MM-DD


def test_lot_not_found_is_404(client):
    r = client.get("/api/v1/lots/lot00000/wafers")
    assert r.status_code == 404


def test_evidence_of_missing_analysis_is_404(client):
    r = client.get("/api/v1/analyses/grp_center_20260401_01/evidence/h0")
    assert r.status_code == 404


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


# ── #69: 판독상 정상 로트 전용 카드(normal_reading) ───────────────────────────────────
def test_normal_lots_are_persisted_as_normal_reading_card(client):
    """grouper가 분리한 normal_lots가 배치 저장에서 전용 analysis 1건으로 합성된다.

    이 로트들은 그룹 서브그래프를 타지 않으므로 final_response가 없다 — 저장 단계가 유일한
    노출 경로다(배선이 끊기면 "판독상 정상" 신호가 UI에서 통째로 사라진다).
    """
    from backend.batch_runner import _persist_results

    state = {
        "final_response": {},
        "normal_lots": ["lot123", "lot456", "lot789"],
        # 창 평균 대비 저수율 → yield_impact는 음수여야 한다(판독 정상 ≠ 수율 정상).
        "lot_yields": {"lot123": 0.70, "lot456": 0.72, "lot789": 0.74, "lot999": 0.95},
    }
    ids = _persist_results("b_normal_1", 1, state)
    assert ids == ["grp_normal_20260401_01"]

    body = client.get(f"/api/v1/analyses/{ids[0]}").json()
    assert body["status"] == "normal_reading"
    assert body["pattern"] == "Normal"
    assert body["confidence"] == "low"          # 채택 원인 없음 — R1 규약
    assert body["hypotheses"] == []             # KG 경로를 안 탐
    assert body["description"] is None          # 그룹 관측 없음 → 프론트 summary_line
    assert body["lot_count"] == 3
    assert body["lot_ids"] == ["lot123", "lot456", "lot789"]
    assert body["yield_impact"] is not None and body["yield_impact"] < 0
    # 조치는 조사 이관만 — 결함 패턴이 없어 Hold 근거가 없다.
    assert [a["type"] for a in body["actions"]] == ["investigation", "investigation"]
    assert not any(a["hold"] for a in body["actions"])

    # §2.2 목록에도 확신·수율영향이 실린다(대기열 정렬 원천)
    items = client.get("/api/v1/analyses?sort=latest&limit=10&offset=0").json()["items"]
    assert [i["status"] for i in items] == ["normal_reading"]
    assert items[0]["confidence"] == "low"


def test_normal_reading_evidence_is_404(client):
    """가설이 없으므로 근거 상세는 제공하지 않는다(unmapped·novel과 같은 계약)."""
    from backend.batch_runner import _persist_results

    _persist_results("b_normal_2", 2, {"final_response": {}, "normal_lots": ["lot1"]})
    r = client.get("/api/v1/analyses/grp_normal_20260401_02/evidence/h1")
    assert r.status_code == 404
    assert isinstance(r.json()["detail"], str)


def test_no_normal_card_when_no_normal_lots(client):
    """normal_lots가 비면 카드를 만들지 않는다(빈 카드 노출 금지)."""
    from backend.batch_runner import _persist_results

    assert _persist_results("b_normal_3", 3, {"final_response": {}, "normal_lots": []}) == []
    assert client.get("/api/v1/analyses").json()["count"] == 0
