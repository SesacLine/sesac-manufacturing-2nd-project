# 공통 원천 정합 + 순환성 + 플레이스홀더 차단
import yaml, pathlib

def _mapping():
    return yaml.safe_load(pathlib.Path("simulator/mapping_table.yaml").read_text(encoding="utf-8"))

def test_md_matches_yaml():
    md = pathlib.Path("simulator/mapping_table.md").read_text(encoding="utf-8")
    for pattern, causes in _mapping().items():
        for c in causes:
            assert c["cause"] in md, (
                f"{pattern}/{c['cause']}가 .md에 없음 — yaml에서 재렌더링 필요")

def test_probs_sum_to_one():
    for pattern, causes in _mapping().items():
        assert abs(sum(c["prob"] for c in causes) - 1.0) < 1e-6, (
            f"{pattern}의 원인 확률 합이 1이 아님: {[c['prob'] for c in causes]}")

def test_multiple_causes_per_pattern():
    """순환성 방지: 3 클래스 체제에서는 결함 패턴당 원인 ≥ 3개 강제"""
    for pattern, causes in _mapping().items():
        assert len(causes) >= 3, f"{pattern}: 원인 후보 부족"

def test_field_values_valid():
    """행동을 결정하는 선택 필드의 값 검증 — 오타가 조용한 분기 오류로 새지 않게"""
    drift_vocab = {"step_up", "step_down", "linear_up", "linear_down", "none"}
    for pattern, causes in _mapping().items():
        for c in causes:
            assert isinstance(c.get("maint_event", True), bool), (
                f"{pattern}/{c['cause']}: maint_event는 불리언이어야 함")
            assert c.get("shape") in (None, "consumable_wear"), (
                f"{pattern}/{c['cause']}: 알 수 없는 shape '{c.get('shape')}'")
            assert c["telemetry_signature"]["drift"] in drift_vocab, (
                f"{pattern}/{c['cause']}: drift '{c['telemetry_signature']['drift']}'가 "
                f"inject_drift 어휘 {sorted(drift_vocab)}에 없음")

def test_no_placeholders():
    """'...' 등 미완성 플레이스홀더 차단"""
    for pattern, causes in _mapping().items():
        for c in causes:
            assert c["citation"].strip() not in ("", "..."), (
                f"{pattern}/{c['cause']}: citation이 플레이스홀더 — 문헌 또는 사유 기입")
            for k in ("cause", "process", "equipment_group"):
                assert "..." not in str(c[k]), f"{pattern}/{k}에 '...' 플레이스홀더"
