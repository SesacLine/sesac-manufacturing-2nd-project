# 시나리오 형상 검증 (결측 창/소모품 수명 아크/무이벤트 누적형) — 데이터 빌드 이후에만 유효
import json
import pathlib

import pytest

pytestmark = pytest.mark.data   # fab.db 필요 — CI(-m "not data")에서는 제외


def _cards():
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(pathlib.Path("datasets/ground_truth").glob("SC-*.json"))]


def _query(sql, params=()):
    from server.db import query
    return query(sql, params)


def test_coverage_gap_absent_in_telemetry():
    """카드가 선언한 결측 창에는 텔레메트리가 실제로 없어야 함 (C2 근거)"""
    gapped = [c for c in _cards() if c.get("coverage_gap")]
    assert gapped, "결측 창 시나리오가 한 건도 없음 — 생성 로직 확인"
    for c in gapped:
        g = c["coverage_gap"]
        inside = _query("SELECT COUNT(*) n FROM telemetry "
                        "WHERE equipment_id=? AND ts > ? AND ts < ?",
                        (g["equipment"], g["from"], g["to"]))[0]["n"]
        total = _query("SELECT COUNT(*) n FROM telemetry WHERE equipment_id=?",
                       (g["equipment"],))[0]["n"]
        assert inside == 0, f"{c['scenario_id']}: 결측 창 안에 텔레메트리 {inside}건 존재"
        assert total > 0, f"{c['scenario_id']}: {g['equipment']} 텔레메트리 자체가 없음"


def test_consumable_arc_shape():
    """수명 아크: 교체 순서, 교체 이력 존재, 수명 초과 구간의 카운터 상한 돌파,
    불량 lot 처리 시각이 (수명 초과 ~ 종결 교체) 창 안에 있어야 함"""
    arcs = [c for c in _cards() if c.get("lifecycle") and not c.get("clue_overwritten")]
    if not arcs:
        pytest.skip("이번 빌드에 cmp_pad_wear 시나리오 없음 (확률 추첨 결과)")
    for c in arcs:
        for arc in c["lifecycle"]:
            eq = arc["equipment"]
            assert arc["prev_replacement"] < arc["life_exceeded"] < arc["replacement"]
            for t in (arc["prev_replacement"], arc["replacement"]):
                hit = _query("SELECT 1 FROM maintenance "
                             "WHERE equipment_id=? AND ts=? AND parts LIKE '%소모품 교체%'",
                             (eq, t))
                assert hit, f"{c['scenario_id']}: {eq} {t} 교체 이력 없음"
            peak = _query("SELECT MAX(value) v FROM telemetry "
                          "WHERE equipment_id=? AND param='pad_usage_hours' "
                          "AND ts BETWEEN ? AND ?",
                          (eq, arc["life_exceeded"], arc["replacement"]))[0]["v"]
            assert peak is not None and peak > 250, (
                f"{c['scenario_id']}: 수명 초과 구간 카운터 최대 {peak} ≤ 250")
            for lot in c["lot_ids"]:
                rows = _query("SELECT ts_in, ts_out FROM lot_history "
                              "WHERE lot_id=? AND equipment_id=?", (lot, eq))
                for r in rows:
                    assert arc["life_exceeded"] <= r["ts_in"], (
                        f"{c['scenario_id']}/{lot}: 수명 초과 이전에 처리됨 — 교체 직전 집중 위반")
                    assert r["ts_out"] <= arc["replacement"], (
                        f"{c['scenario_id']}/{lot}: 종결 교체 이후에 처리됨")


def test_no_event_cumulative_has_no_t0_maintenance():
    """무이벤트 누적형(maint_event: false) 원인은 t0에 정비 기록이 없어야 함 —
    시작점 단서는 T8 변화점뿐이라는 시나리오 전제의 데이터 검증."""
    import yaml
    mapping = yaml.safe_load(pathlib.Path("simulator/mapping_table.yaml").read_text(encoding="utf-8"))
    no_event = {c["cause"] for causes in mapping.values() for c in causes
                if c.get("maint_event", True) is False}
    checked = 0
    for c in _cards():
        if c["is_unmatched"] or not set(c["true_root_causes"]) & no_event:
            continue
        for (eq, _ch) in c["cause_sites"]:
            hit = _query("SELECT 1 FROM maintenance WHERE equipment_id=? AND ts=?",
                         (eq, c["t0"]))
            assert not hit, f"{c['scenario_id']}: 무이벤트 원인인데 t0 정비 기록 존재"
            checked += 1
    if not checked:
        pytest.skip("이번 빌드에 무이벤트 누적형 시나리오 없음 (확률 추첨 결과)")
