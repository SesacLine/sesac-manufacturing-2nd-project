"""② grouper — Normal 로트 분리(이슈 #69)와 다수결 동률 우선순위(07-22 확정) 테스트.

데이터/GPU/키 불필요(순수 함수) — CI(-m "not data")에서도 돈다.
"""

from __future__ import annotations

from backend.nodes.grouper import group_by_pattern


def _state(cnn_results):
    return {"cursor_date": "2026-03-04", "cnn_results": cnn_results}


def _wafers(lot_id, patterns):
    return [
        {"lot_id": lot_id, "wafer_id": str(i), "pattern": p, "confidence": 0.9}
        for i, p in enumerate(patterns)
    ]


def test_majority_normal_lot_goes_to_normal_lots_not_groups():
    """과반 Normal 로트: 그룹 미생성(기획 §6.1) + normal_lots로 운반(이슈 #69 (b)안)."""
    out = group_by_pattern(
        _state(
            _wafers("lotN", ["Normal", "Normal", "Normal", "Center"])  # 과반 Normal
            + _wafers("lotC", ["Center", "Center", "Normal"])          # 과반 Center
        )
    )
    assert out["normal_lots"] == ["lotN"]
    patterns = {g["pattern"] for g in out["groups"]}
    assert "Normal" not in patterns, "Normal 그룹이 생성됨 — 기획 §6.1 위반"
    assert any(g["pattern"] == "Center" and g["lot_ids"] == ["lotC"] for g in out["groups"])


def test_no_normal_lots_yields_empty_list():
    out = group_by_pattern(_state(_wafers("lotA", ["Scratch", "Scratch"])))
    assert out["normal_lots"] == []
    assert len(out["groups"]) == 1


def test_tie_between_normal_and_defect_prefers_defect():
    """Normal은 우선순위 제외 — 동률이면 결함 패턴이 이긴다(설계서 §3)."""
    out = group_by_pattern(_state(_wafers("lotT", ["Normal", "Center"])))  # 1:1 동률
    assert out["normal_lots"] == []
    assert out["groups"][0]["pattern"] == "Center"


def test_tie_priority_edge_ring_over_center():
    """동률 우선순위: Edge-Ring > Center > Scratch > Unknown (07-22 확정)."""
    out = group_by_pattern(_state(_wafers("lotT", ["Center", "Edge-Ring"])))
    assert out["groups"][0]["pattern"] == "Edge-Ring"
    out = group_by_pattern(_state(_wafers("lotT", ["Unknown", "Scratch"])))
    assert out["groups"][0]["pattern"] == "Scratch"


def test_all_normal_batch_produces_no_groups():
    """전 로트 Normal이어도 예외 없이 그룹 0개 + normal_lots 전체."""
    out = group_by_pattern(
        _state(_wafers("lot1", ["Normal"]) + _wafers("lot2", ["Normal", "Normal"]))
    )
    assert out["groups"] == []
    assert out["normal_lots"] == ["lot1", "lot2"]
