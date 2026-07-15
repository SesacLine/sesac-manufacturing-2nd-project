from __future__ import annotations
from preprocess.label_ontology import to_kg_entity, scope_of, SCENARIO_CLASSES

def test_alignment():
    assert to_kg_entity("Edge_Ring") == "Edge-Ring"   # 언더스코어 변형 흡수
    assert to_kg_entity("Edge-Ring") == "Edge-Ring"
    assert to_kg_entity("none") == "Normal"
    assert to_kg_entity("Near-full") == "Near-Full"   # 제외 클래스도 인식하게 둘지는 미정

def test_scope_partition():
    assert scope_of("Center") == "scenario"
    assert scope_of("Normal") == "normal"
    assert scope_of("Donut") == "excluded"            # 제외 클래스도 인식하게 둘지는 미정
    assert scope_of(None) == "unlabeled"              # 배경 물량 후보
    assert SCENARIO_CLASSES == {"Center", "Edge-Ring", "Scratch"}
    
# 실행 스크립트
# pytest tests/test_label_ontology.py -q