import pathlib, re

import pytest

def test_server_never_imports_ground_truth():
    for p in pathlib.Path("server").rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        assert "ground_truth" not in src, f"{p}가 ground_truth를 참조함 (정답 노출 위험)"


@pytest.mark.data
def test_db_text_never_contains_cause_ids():
    """툴이 그대로 반환하는 DB 텍스트 컬럼에 원인 ID가 노출되면 안 됨 —
    정비 이력은 부품명(part)까지만, 원인 판단은 에이전트 몫."""
    import yaml
    from server.db import query
    mapping = yaml.safe_load(pathlib.Path("simulator/mapping_table.yaml").read_text(encoding="utf-8"))
    cause_ids = {c["cause"] for causes in mapping.values() for c in causes}
    texts = [r["t"] for sql in (
        "SELECT DISTINCT parts t FROM maintenance",
        "SELECT DISTINCT text t FROM alarm",
        "SELECT DISTINCT detail t FROM event_log",
    ) for r in query(sql)]
    for cid in cause_ids:
        hit = [t for t in texts if cid in t]
        assert not hit, f"원인 ID '{cid}'가 DB 텍스트에 노출: {hit[:3]}"


# 실행 스크립트
# pytest tests/test_no_ground_truth_leak.py -q