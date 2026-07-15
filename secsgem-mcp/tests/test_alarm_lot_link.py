# 알람-lot 연결 검증 — 데이터 빌드(simulator.generate) 이후에만 유효
import pytest

pytestmark = pytest.mark.data   # fab.db 필요 — CI(-m "not data")에서는 제외


def _query(sql, params=()):
    from server.db import query
    return query(sql, params)


def test_some_alarms_linked_to_lots():
    """lot 처리 구간과 겹치는 알람이 존재하는 이상, lot_id가 전부 None이면 안 됨"""
    total = _query("SELECT COUNT(*) c FROM alarm")[0]["c"]
    linked = _query("SELECT COUNT(*) c FROM alarm WHERE lot_id IS NOT NULL")[0]["c"]
    assert total, "알람이 한 건도 없음 - 생성 로직 확인"
    assert linked > 0, "lot이 연결된 알람이 0건 — 알람 lot_id가 전부 None"


def test_linked_alarm_ts_within_lot_window():
    """연결된 알람의 시각은 그 lot이 해당 장비를 지나던 구간 안이어야 함"""
    rows = _query("SELECT equipment_id, lot_id, ts FROM alarm "
                  "WHERE lot_id IS NOT NULL")
    for r in rows:
        hit = _query("SELECT 1 FROM lot_history "
                     "WHERE lot_id=? AND equipment_id=? AND ts_in<=? AND ts_out>=?",
                     (r["lot_id"], r["equipment_id"], r["ts"], r["ts"]))
        assert hit, (f"{r['lot_id']} @ {r['equipment_id']} {r['ts']} — "
                     "처리 구간 밖 알람에 lot이 연결됨")


def test_unlinked_alarm_has_no_containing_window():
    """lot_id 없는 알람은 실제로 어느 lot 처리 구간에도 안 들어야 함 (유휴 중 알람)"""
    rows = _query("SELECT equipment_id, ts FROM alarm WHERE lot_id IS NULL")
    for r in rows:
        hit = _query("SELECT 1 FROM lot_history "
                     "WHERE equipment_id=? AND ts_in<=? AND ts_out>=?",
                     (r["equipment_id"], r["ts"], r["ts"]))
        assert not hit, (f"{r['equipment_id']} {r['ts']} — "
                         "연결 가능한 lot이 있는데 None으로 남음")


def test_scenario_cause_alarms_visible_in_lot_timeline():
    """시나리오 원인 알람('out of range')이 최소 1건은 어떤 lot 타임라인에 잡혀야 함"""
    linked = _query("SELECT COUNT(*) c FROM alarm "
                    "WHERE lot_id IS NOT NULL AND text LIKE '%out of range%'")[0]["c"]
    assert linked > 0, "원인 시점 알람이 어느 lot에도 연결되지 않음 — 선후관계 검증 근거 부재"
