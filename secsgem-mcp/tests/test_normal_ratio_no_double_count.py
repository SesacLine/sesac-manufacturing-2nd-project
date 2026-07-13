# normal_ratio 이중 집계 검증 — 데이터 빌드(simulator.generate) 이후에만 유효
import pytest

pytestmark = pytest.mark.data   # fab.db 필요 — CI(-m "not data")에서는 제외


def _query(sql, params=()):
    from server.db import query
    return query(sql, params)


def test_mixed_lots_exist_in_dataset():
    """혼합 lot(정상+불량 wafer 공존)이 실재해야 이 회귀 테스트가 유효하다."""
    mixed = _query("SELECT COUNT(*) c FROM ("
                   "SELECT lot_id FROM wafer GROUP BY lot_id "
                   "HAVING MIN(is_normal)=0 AND MAX(is_normal)=1)")[0]["c"]
    assert mixed > 0, "혼합 lot 0건 — 이중 집계 회귀를 검출할 수 없는 데이터"


def test_totals_match_distinct_lots(client):
    """모든 장비에서 normal+defect == 그 장비를 지난 고유 lot 수 (lot당 1회 집계)."""
    for e in _query("SELECT DISTINCT equipment_id FROM lot_history"):
        eq = e["equipment_id"]
        d = client.call("get_normal_lot_ratio", equipment_id=eq)["data"]
        expected = _query("SELECT COUNT(DISTINCT h.lot_id) c FROM lot_history h "
                          "JOIN wafer w USING(lot_id) WHERE h.equipment_id=?",
                          (eq,))[0]["c"]
        assert d["normal_lots"] + d["defect_lots"] == d["total_lots"] == expected, \
            f"{eq}: normal={d['normal_lots']} defect={d['defect_lots']} " \
            f"total={d['total_lots']} vs 고유 lot {expected}"


def test_defect_count_follows_lot_label_definition(client):
    """defect_lots는 'MIN(is_normal)=0인 lot' 정의와 일치해야 한다."""
    eq = _query("SELECT DISTINCT equipment_id FROM lot_history LIMIT 1")[0]["equipment_id"]
    d = client.call("get_normal_lot_ratio", equipment_id=eq)["data"]
    expected = _query("SELECT COUNT(*) c FROM ("
                      "SELECT h.lot_id FROM lot_history h JOIN wafer w USING(lot_id) "
                      "WHERE h.equipment_id=? GROUP BY h.lot_id "
                      "HAVING MIN(w.is_normal)=0)", (eq,))[0]["c"]
    assert d["defect_lots"] == expected


def test_chamber_path_also_single_counts(client):
    """chamber_id 경로도 동일하게 lot당 1회 집계."""
    ch = _query("SELECT chamber FROM lot_history LIMIT 1")[0]["chamber"]
    d = client.call("get_normal_lot_ratio", chamber_id=ch)["data"]
    expected = _query("SELECT COUNT(DISTINCT h.lot_id) c FROM lot_history h "
                      "JOIN wafer w USING(lot_id) WHERE h.chamber=?", (ch,))[0]["c"]
    assert d["normal_lots"] + d["defect_lots"] == d["total_lots"] == expected
