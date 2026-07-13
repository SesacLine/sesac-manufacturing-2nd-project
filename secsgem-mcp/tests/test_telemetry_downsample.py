# 텔레메트리 다운샘플 상한 검증 — 순수 로직이라 fab.db 불필요 (CI 포함)
import pytest

from server.tools.telemetry import MAX_POINTS, downsample


@pytest.mark.parametrize("n_raw", [0, 1, 499, 500, 501, 750, 999, 1000, 1001, 1500, 10000])
def test_returned_never_exceeds_max_points(n_raw):
    """어떤 원본 개수에서도 반환 개수는 max_points를 넘지 않는다 (특히 501~999 구간)."""
    out = downsample(list(range(n_raw)), MAX_POINTS)
    assert len(out) <= MAX_POINTS, f"n_raw={n_raw} → {len(out)}개 반환"


@pytest.mark.parametrize("n_raw", [0, 1, 499, 500])
def test_no_reduction_when_under_limit(n_raw):
    """상한 이하면 그대로 반환 — downsampled 플래그(n_raw > max_points)와 일치."""
    assert downsample(list(range(n_raw)), MAX_POINTS) == list(range(n_raw))


@pytest.mark.parametrize("n_raw", [501, 999, 1000, 1500])
def test_uniform_spacing_keeps_endpoints_side(n_raw):
    """균일 간격 표본 — 첫 포인트를 보존하고 간격이 일정하다."""
    rows = list(range(n_raw))
    out = downsample(rows, MAX_POINTS)
    assert out[0] == 0
    steps = {b - a for a, b in zip(out, out[1:])}
    assert len(steps) == 1, f"간격 불균일: {steps}"


@pytest.mark.data
def test_tool_in_regression_band_501_to_999(client):
    """501~999 구간(과거 미작동 구간)을 실제 툴 호출로 검증.
    텔레메트리는 2시간 간격이므로 param 1개 × 59일 = 708행."""
    from server.db import query
    row = query("SELECT equipment_id, param FROM telemetry LIMIT 1")[0]
    res = client.call("query_telemetry", equipment_id=row["equipment_id"],
                      params=[row["param"]],
                      time_range=("2026-01-15 00:00:00", "2026-03-15 00:00:00"))
    d = res["data"]
    assert 501 <= d["n_raw"] <= 999, f"회귀 구간 밖 (n_raw={d['n_raw']}) — 범위 조정 필요"
    assert d["n_returned"] <= MAX_POINTS
    assert d["n_returned"] == len(d["series"])
    assert d["downsampled"] is True
    assert d["n_returned"] < d["n_raw"]
