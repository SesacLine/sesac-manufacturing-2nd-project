import yaml, pathlib

def _load(p):
    return yaml.safe_load(pathlib.Path(p).read_text())

def test_route_steps_have_equipment():
    fab = _load("simulator/fab_model.yaml")
    missing = [s for s in fab["route"] if s not in fab["equipment"]]
    assert not missing, f"route step에 장비 정의 없음: {missing}"

def test_mapping_params_exist_in_fab_model():
    fab, mapping = _load("simulator/fab_model.yaml"), _load("simulator/mapping_table.yaml")
    for pattern, causes in mapping.items():
        for c in causes:
            param = c["telemetry_signature"]["param"]
            if param in (None, "none"):     # 이력에만 단서가 있는 원인 (§4.4)
                continue
            group_params = fab["equipment"][c["equipment_group"]]["params"]
            assert param in group_params, (
                f"{pattern}/{c['cause']}의 단서 param '{param}'이 "
                f"{c['equipment_group']} 장비 params에 없음 (§4.6)")