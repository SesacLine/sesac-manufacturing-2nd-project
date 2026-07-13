"""라벨 누출 회귀 테스트 (§5.1) — get_wafer_map은 라벨을 절대 반환하지 않는다."""
import pytest

pytestmark = pytest.mark.data   # fab.db 필요 — CI(-m "not data")에서는 제외


def test_get_wafer_map_omits_label(client, sample_wafer):
    r = client.call("get_wafer_map", **sample_wafer)
    assert r["data"] is not None, "존재 보장된 웨이퍼인데 응답 없음"
    keys = set(r["data"])
    assert not (keys & {"kg_label", "failureType", "onehot", "label"})


def test_missing_wafer_reports_via_coverage(client):
    """없는 웨이퍼는 빈 결과 + coverage.missing (P4 — 보간·추측 금지)."""
    r = client.call("get_wafer_map", lot_id="lot-없음", wafer_id="1")
    assert r["data"] is None
    assert r["meta"]["coverage"]["missing"]
