import yaml, pathlib

def _load(p):
    return yaml.safe_load(pathlib.Path(p).read_text(encoding="utf-8"))

def test_route_steps_have_equipment():
    fab = _load("simulator/fab_model.yaml")
    missing = [s for s in fab["route"] if s not in fab["equipment"]]
    assert not missing, f"route step에 장비 정의 없음: {missing}"

def test_mapping_params_exist_in_fab_model():
    fab, mapping = _load("simulator/fab_model.yaml"), _load("simulator/mapping_table.yaml")
    for pattern, causes in mapping.items():
        for c in causes:
            param = c["telemetry_signature"]["param"]
            if param in (None, "none"):     # 이력에만 단서가 있는 원인
                continue
            group_params = fab["equipment"][c["equipment_group"]]["params"]
            assert param in group_params, (
                f"{pattern}/{c['cause']}의 단서 param '{param}'이 "
                f"{c['equipment_group']} 장비 params에 없음")


def test_mapping_drift_declared_in_fab_model():
    """mapping이 부여한 drift는 해당 param의 drift_models 선언에 속해야 함 —
    fab_model이 허용 drift의 단일 원천. 수명 아크 원인은 카운터로 실현되므로 제외."""
    fab, mapping = _load("simulator/fab_model.yaml"), _load("simulator/mapping_table.yaml")
    for pattern, causes in mapping.items():
        for c in causes:
            sig = c["telemetry_signature"]
            if sig["param"] in (None, "none") or c.get("shape") == "consumable_wear":
                continue
            declared = fab["equipment"][c["equipment_group"]]["params"][sig["param"]] \
                .get("drift_models", [])
            base = "none" if sig["drift"] == "none" else sig["drift"].rsplit("_", 1)[0]
            assert base in declared, (
                f"{pattern}/{c['cause']}: drift '{sig['drift']}'({base})가 "
                f"{sig['param']}의 drift_models {declared}에 선언되지 않음")


def test_consumable_wear_param_is_counter():
    """shape: consumable_wear 원인의 param은 counter_rate_per_day를 가져야 함
    (generate.py가 직접 인덱싱 — 누락 시 생성 단계 KeyError).
    또한 일일누적률 × PM 주기 < 정상 상한 — 정기 교체가 지켜지는 동안은 수명 초과 없음."""
    fab, mapping = _load("simulator/fab_model.yaml"), _load("simulator/mapping_table.yaml")
    checked = 0
    for pattern, causes in mapping.items():
        for c in causes:
            if c.get("shape") != "consumable_wear":
                continue
            spec = fab["equipment"][c["equipment_group"]]
            ps = spec["params"][c["telemetry_signature"]["param"]]
            assert "counter_rate_per_day" in ps, (
                f"{pattern}/{c['cause']}: 수명 아크 param에 counter_rate_per_day 없음")
            budget = ps["counter_rate_per_day"] * spec["maintenance"]["pm_interval_days"]
            assert budget < ps["normal"][1], (
                f"{pattern}/{c['cause']}: 정기 PM 주기 내 누적({budget})이 "
                f"정상 상한({ps['normal'][1]})을 초과 — 배경 장비도 수명 초과 알람 발생")
            checked += 1
    assert checked, "consumable_wear 원인이 mapping에 없음 — shape 오타 여부 확인"

# 실행 스크립트
# pytest tests/test_fab_model_consistency.py -q