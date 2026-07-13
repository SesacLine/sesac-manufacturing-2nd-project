# 공통 원천 정합 + 순환성 + 플레이스홀더 차단
import yaml, pathlib

def _mapping():
    return yaml.safe_load(pathlib.Path("simulator/mapping_table.yaml").read_text())

def test_md_matches_yaml():
    md = pathlib.Path("simulator/mapping_table.md").read_text()
    for pattern, causes in _mapping().items():
        for c in causes:
            assert c["cause"] in md, (
                f"{pattern}/{c['cause']}가 .md에 없음 — yaml에서 재렌더링 필요")

def test_probs_sum_to_one():
    for pattern, causes in _mapping().items():
        assert abs(sum(c["prob"] for c in causes) - 1.0) < 1e-6, (
            f"{pattern}의 원인 확률 합이 1이 아님: {[c['prob'] for c in causes]}")

def test_multiple_causes_per_pattern():
    """순환성 방지: 매핑 수준에서 패턴당 원인 ≥2개 강제."""
    for pattern, causes in _mapping().items():
        assert len(causes) >= 2, f"{pattern}: 원인 1개 → 이미지만으로 역산 가능(순환성)"

def test_no_placeholders():
    """'...' 등 미완성 플레이스홀더 차단. TODO는 허용하되 M1 리뷰(사람)가 게이트."""
    for pattern, causes in _mapping().items():
        for c in causes:
            assert c["citation"].strip() not in ("", "..."), (
                f"{pattern}/{c['cause']}: citation이 플레이스홀더 — 문헌 또는 TODO(사유) 기입")
            for k in ("cause", "process", "equipment_group"):
                assert "..." not in str(c[k]), f"{pattern}/{k}에 '...' 플레이스홀더"
