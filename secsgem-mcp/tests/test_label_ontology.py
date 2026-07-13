from preprocess.label_ontology import to_kg_entity, onehot_to_kg

def test_three_way_alignment():
    assert to_kg_entity("Edge_Ring") == "Edge-Ring"   # MW38 표기
    assert to_kg_entity("Edge-Ring") == "Edge-Ring"   # WM811K/KG 표기
    assert to_kg_entity("none") == "Normal"

def test_onehot_mixed():
    # C+ER (Center + Edge_Ring)
    assert set(onehot_to_kg([1,0,0,1,0,0,0,0])) == {"Center", "Edge-Ring"}
    assert onehot_to_kg([0]*8) == ["Normal"]          # all-zero = Normal