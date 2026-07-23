"""quantitative.compute_group_stats — 합성 스택맵으로 KG 어휘 출력 검증."""

from __future__ import annotations

import numpy as np

from wafer_reading.quantitative import compute_group_stats
from wafer_reading.stacking import stack_wafer_maps

SIZE = 64


def _wafer(defect_mask_fn) -> np.ndarray:
    """반지름 1 원판 die(값1) + defect 영역(값2)인 0/1/2 웨이퍼맵."""
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    cy = cx = (SIZE - 1) / 2
    r = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2) / (SIZE / 2)
    arr = np.zeros((SIZE, SIZE), dtype=int)
    die = r <= 1.0
    arr[die] = 1
    arr[die & defect_mask_fn(r, yy, xx, cy, cx)] = 2
    return arr


def _stats(defect_mask_fn, n=3):
    wafers = [_wafer(defect_mask_fn) for _ in range(n)]
    return compute_group_stats(stack_wafer_maps(wafers, grid_size=SIZE))


def test_full_edge_ring():
    s = _stats(lambda r, yy, xx, cy, cx: r >= 0.78)
    assert s["shape"] == "ring"
    assert s["zone"] == "edge"
    assert s["angular_coverage"] == "full"       # 전방위
    assert s["clock_positions"] == []
    assert s["signature"] == "ring@edge"
    assert s["continuity"] == "continuous"


def test_partial_arc_lower_edge():
    # 하단(6시 부근) 가장자리 호: y가 큰 쪽(화면 아래) + edge
    def arc(r, yy, xx, cy, cx):
        return (r >= 0.72) & (yy - cy > 0.5 * np.abs(xx - cx))
    s = _stats(arc)
    assert s["shape"] == "ring"
    assert s["zone"] == "edge"
    assert s["angular_coverage"] == "partial"     # 한쪽 호
    assert s["clock_positions"] != []             # 대표 시각 있음
    assert 5 <= s["clock_positions"][0] <= 7      # 6시 근방


def test_center_cluster():
    s = _stats(lambda r, yy, xx, cy, cx: r <= 0.28)
    assert s["shape"] in ("cluster", "blob")
    assert s["zone"] == "center"
    assert s["angular_coverage"] == "unknown"     # ring 아님 → 각도 무의미
    assert s["continuity"] == "not_applicable"


def test_diagonal_line():
    def line(r, yy, xx, cy, cx):
        return np.abs((yy - cy) - (xx - cx)) < 2.5
    s = _stats(line)
    assert s["shape"] == "line"
    assert s["continuity"] == "continuous"


def test_no_defect_returns_none_shape():
    s = _stats(lambda r, yy, xx, cy, cx: np.zeros_like(r, dtype=bool))
    assert s["shape"] is None
    assert s["signature"] is None
    assert s["defect_die_ratio"] == 0.0


def test_output_uses_kg_vocabulary_only():
    # 어떤 입력이든 KG enum 밖 토큰을 내면 안 된다 (arc/scatter/full 같은 geometry 어휘 금지)
    s = _stats(lambda r, yy, xx, cy, cx: r >= 0.78)
    assert s["shape"] in {"ring", "cluster", "line", "blob", "global", "random", None}
    assert s["zone"] in {"center", "mid", "edge", "any", None}
    assert s["angular_coverage"] in {"full", "partial", "unknown"}
    assert s["density"] in {"high", "medium", "low", "unknown"}
    assert s["continuity"] in {
        "continuous", "intermittent", "discontinuous", "not_applicable", "unknown"
    }
