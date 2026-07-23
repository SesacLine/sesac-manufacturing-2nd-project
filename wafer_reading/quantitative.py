"""그룹 정량값 계산 — 스택맵 → KG 어휘 die-matrix 통계.

같은 결함 패턴 웨이퍼들을 겹친 StackedHeatmap(stacking.py) 1장에서 기하 통계를 뽑아,
KG 조회의 구조화 관측(shape/zone/angular_coverage/clock_positions/density/continuity +
defect_die_ratio)을 **KG 고정 enum 그대로** 낸다. 별도 매핑 어댑터 없이 여기서 바로 KG 어휘로.

기하 계산(반경/각도/군집/선형성)은 geometry_v0.1.py를 이식. 다른 점은 출력 어휘:
- geometry의 arc(호)는 KG에 없음 → KG는 "ring + angular_coverage=partial"로 표현한다
  (전방위 링 vs 한쪽 호를 shape가 아니라 angular로 가른다 — KG 판별자 설계와 정합).
- geometry의 scatter → random, near-full → global, zone "full" → "any".
- density/continuity는 geometry에 없어 여기서 파생한다.

입력은 StackedHeatmap (그룹 단위). 웨이퍼 1장이면 stack_wafer_maps([wm])로 감싸 넣으면 된다.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
from scipy import ndimage

from . import constants as C
from .stacking import StackedHeatmap

_EIGHT_CONN = np.ones((3, 3), dtype=int)


def compute_group_stats(heatmap: StackedHeatmap) -> dict:
    """StackedHeatmap → KG 어휘 관측 dict.

    반환(구조화 관측 — observe 노드가 Observation의 die-matrix 절반으로 쓴다):
        shape, zone, signature("{shape}@{zone}"),
        angular_coverage, clock_positions, density, continuity, defect_die_ratio,
        raw(원시 float 통계 — 튜닝/디버깅용)
    결함이 없으면 shape/signature=None (그룹이 정상 — 상위에서 스킵/normal 처리).
    """
    die = heatmap.die_coverage > 0
    defect = die & (heatmap.heat >= C.DEFECT_HEAT_THRESHOLD)
    n_die = int(die.sum())
    n_defect = int(defect.sum())
    ratio = (n_defect / n_die) if n_die else 0.0

    if n_defect == 0 or n_die == 0:
        return _empty(ratio)

    feats = _geometry_features(die, defect, n_defect)
    feats["defect_ratio"] = ratio

    shape = _shape(feats)
    zone = _zone(feats)
    angular = _angular(shape, feats)
    clock = _clock(angular, feats)
    density = _density(ratio)
    continuity = _continuity(shape, feats)

    return {
        "shape": shape,
        "zone": zone,
        "signature": f"{shape}@{zone}" if shape else None,
        "angular_coverage": angular,
        "clock_positions": clock,
        "density": density,
        "continuity": continuity,
        "defect_die_ratio": round(ratio, 4),
        "raw": feats,
    }


# =========================
# 기하 통계 (geometry_v0.1.py 이식 — 어휘 무관 순수 계산)
# =========================

def _geometry_features(die: np.ndarray, defect: np.ndarray, n_defect: int) -> dict:
    ys, xs = np.nonzero(die)
    cy, cx = ys.mean(), xs.mean()
    r_max = float(np.sqrt((ys - cy) ** 2 + (xs - cx) ** 2).max()) or 1.0

    # 배경 노이즈(고립 불량) 강건성: 유의미 군집(core)이 충분하면 공간 통계는 core 기준.
    labeled, _ = ndimage.label(defect, structure=_EIGHT_CONN)
    comp_sizes = np.bincount(labeled.ravel())
    core_mask = defect & (comp_sizes[labeled] >= C.MIN_CLUSTER_SIZE)
    n_core = int(core_mask.sum())
    use_core = n_core >= max(C.MIN_CLUSTER_SIZE * 2, int(0.15 * n_defect))
    spatial = core_mask if use_core else defect

    dy, dx = np.nonzero(spatial)
    r = np.sqrt((dy - cy) ** 2 + (dx - cx) ** 2) / r_max
    theta = np.arctan2(dx - cx, -(dy - cy))  # 12시=0, 시계방향 양수

    f: dict = {
        "core_frac": (n_core / n_defect) if n_defect else 0.0,
        "r_mean": float(r.mean()),
        "r_std": float(r.std()),
        "frac_inner": float((r <= C.R_INNER).mean()),
        "frac_edge": float((r >= C.R_EDGE).mean()),
        "frac_mid": float(((r > C.R_INNER) & (r < C.R_EDGE)).mean()),
    }

    # 각도: 12방위 점유율 + 평균벡터 집중도
    bins = ((theta % (2 * math.pi)) / (2 * math.pi) * C.ANGULAR_BINS).astype(int)
    bins = np.clip(bins, 0, C.ANGULAR_BINS - 1)
    occupied = np.bincount(bins, minlength=C.ANGULAR_BINS) > max(1, len(theta) * 0.01)
    f["angular_coverage_frac"] = float(occupied.mean())
    f["angular_concentration"] = float(np.hypot(np.cos(theta).mean(), np.sin(theta).mean()))
    f["mean_theta"] = float(math.atan2(np.sin(theta).mean(), np.cos(theta).mean()))

    # 군집 / 선형성
    sizes = comp_sizes[1:] if labeled.max() else np.array([])
    big = sizes[sizes >= C.MIN_CLUSTER_SIZE]
    largest = int(sizes.max()) if len(sizes) else 0
    f["n_clusters"] = int(len(big))
    f["largest_cluster_frac"] = (largest / n_defect) if n_defect else 0.0
    f["linearity"] = _linearity(labeled, sizes, largest)
    return f


def _linearity(labeled: np.ndarray, sizes: np.ndarray, largest: int) -> float:
    if largest < C.MIN_CLUSTER_SIZE:
        return 0.0
    target = int(np.argmax(sizes)) + 1
    cy, cx = np.nonzero(labeled == target)
    pts = np.stack([cy, cx], axis=1).astype(float)
    pts -= pts.mean(axis=0)
    cov = pts.T @ pts / len(pts)
    eig = np.sort(np.linalg.eigvalsh(cov))[::-1]
    total = eig.sum()
    return float(eig[0] / total) if total > 0 else 0.0


# =========================
# KG 어휘 분류 (출력 = KG 고정 enum)
# =========================

def _shape(f: dict) -> Optional[str]:
    """KG ShapeId: ring / cluster / line / blob / global / random.
    geometry의 arc는 여기서 ring으로 흡수하고(angular가 full/partial을 가름), scatter→random.
    """
    if f["defect_ratio"] >= C.NEAR_FULL_RATIO:
        return "global"
    ring_radial = (
        (f["r_std"] < C.RING_RSTD_MAX and f["r_mean"] > C.RING_RMEAN_MIN)
        or f["frac_edge"] >= C.RING_EDGE_FRAC
    )
    # 링 or 호 — 둘 다 ring. 전방위/부분은 angular_coverage가 표현.
    if ring_radial and f["angular_coverage_frac"] >= C.ANGULAR_PARTIAL:
        return "ring"
    if f["linearity"] >= C.LINE_LINEARITY_MIN and f["largest_cluster_frac"] >= C.LINE_CLUSTER_FRAC_MIN:
        return "line"
    if f["largest_cluster_frac"] >= C.CLUSTER_FRAC_MIN:
        return "cluster"
    if f["n_clusters"] >= C.SCATTER_CLUSTERS_MIN or f["largest_cluster_frac"] < C.SCATTER_CLUSTER_FRAC_MAX:
        return "random"
    return "cluster"


def _zone(f: dict) -> str:
    """KG ZoneId: center / mid / edge / any (geometry의 full → any)."""
    if f["defect_ratio"] >= C.NEAR_FULL_RATIO:
        return "any"
    fracs = {"center": f["frac_inner"], "mid": f["frac_mid"], "edge": f["frac_edge"]}
    return max(fracs, key=fracs.get)


def _angular(shape: Optional[str], f: dict) -> str:
    """KG AngularCoverage: full / partial / unknown.
    원주 방향 개념이 있는 ring에만 의미. 나머지 형상은 unknown(판별자가 비교를 건너뜀).
    """
    if shape != "ring":
        return "unknown"
    ac = f["angular_coverage_frac"]
    conc = f["angular_concentration"]
    if ac >= C.ANGULAR_FULL and conc < C.ANGULAR_CONCENTRATION_MAX:
        return "full"          # 전방위 균등
    if ac >= C.ANGULAR_PARTIAL:
        return "partial"       # 한쪽 호 / 방위 편중
    return "unknown"


def _clock(angular: str, f: dict) -> list[int]:
    """KG clock_positions: partial일 때만 대표 시각 1개. full/그 외는 빈 리스트."""
    if angular != "partial":
        return []
    if f["angular_concentration"] < C.CLOCK_MIN_CONCENTRATION:
        return []
    hour = int(round((f["mean_theta"] % (2 * math.pi)) / (2 * math.pi) * 12)) % 12
    return [12 if hour == 0 else hour]


def _density(ratio: float) -> str:
    """KG Density: high / medium / low / unknown (defect_die_ratio 기준)."""
    if ratio >= C.DENSITY_HIGH:
        return "high"
    if ratio >= C.DENSITY_MEDIUM:
        return "medium"
    if ratio > 0:
        return "low"
    return "unknown"


def _continuity(shape: Optional[str], f: dict) -> str:
    """KG Continuity: continuous / intermittent / discontinuous / not_applicable / unknown."""
    if shape in ("cluster", "blob", "global"):
        return "not_applicable"       # 덩어리 형상엔 연속성 개념이 없다
    if shape == "line":
        return "continuous"           # 선은 본질적으로 연속
    if shape == "random":
        return "discontinuous"
    if shape == "ring":
        ac = f["angular_coverage_frac"]
        if ac >= C.CONTINUITY_FULL_ANGULAR and f["n_clusters"] <= C.CONTINUITY_MAX_CLUSTERS:
            return "continuous"
        if ac >= C.ANGULAR_PARTIAL:
            return "intermittent"
        return "discontinuous"
    return "unknown"


def _empty(ratio: float) -> dict:
    return {
        "shape": None, "zone": None, "signature": None,
        "angular_coverage": "unknown", "clock_positions": [],
        "density": _density(ratio), "continuity": "unknown",
        "defect_die_ratio": round(ratio, 4), "raw": {},
    }
