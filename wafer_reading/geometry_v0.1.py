"""웨이퍼맵 기하 통계 추출 코드
"""
from __future__ import annotations

import math
from typing import Dict

import numpy as np
from scipy import ndimage

from ..constants import (
    ANGULAR_BINS,
    MIN_CLUSTER_SIZE,
    NEAR_FULL_RATIO,
    R_EDGE,
    R_INNER,
)

_EIGHT_CONN = np.ones((3, 3), dtype=int)


def extract_features(arr: np.ndarray) -> Dict[str, object]:
    """0/1/2 웨이퍼맵 → 기하 특징 dict"""
    die = arr > 0
    defect = arr == 2
    n_die = int(die.sum())
    n_defect = int(defect.sum())
    feats: Dict[str, object] = {
        "n_die": n_die,
        "n_defect": n_defect,
        "defect_ratio": (n_defect / n_die) if n_die else 0.0,
    }
    if n_defect == 0 or n_die == 0:
        feats.update(
            r_mean=0.0, r_std=0.0, r_p90=0.0, frac_inner=0.0, frac_mid=0.0,
            frac_edge=0.0, angular_coverage=0.0, angular_concentration=0.0,
            clock="전방위", n_clusters=0, largest_cluster_frac=0.0,
            linearity=0.0, zone="center", shape="none",
        )
        return feats

    ys, xs = np.nonzero(die)
    cy, cx = ys.mean(), xs.mean()
    r_max = float(np.sqrt((ys - cy) ** 2 + (xs - cx) ** 2).max()) or 1.0

    # 실팹 맵의 배경 노이즈(고립 불량 die) 강건성: 유의미한 군집(core)이 충분하면
    # 공간 통계(반경/각도/zone/방향)는 core 기준으로 계산함. 
    # 산발 노이즈가 Center 등의 실제 밀집 위치를 가리는 것을 방지
    labeled_comp, _ = ndimage.label(defect, structure=_EIGHT_CONN)
    comp_sizes = np.bincount(labeled_comp.ravel())
    core_mask = defect & (comp_sizes[labeled_comp] >= MIN_CLUSTER_SIZE)
    n_core = int(core_mask.sum())
    use_core = n_core >= max(MIN_CLUSTER_SIZE * 2, int(0.15 * n_defect))
    spatial_mask = core_mask if use_core else defect
    feats["core_frac"] = (n_core / n_defect) if n_defect else 0.0

    dy, dx = np.nonzero(spatial_mask)
    r = np.sqrt((dy - cy) ** 2 + (dx - cx) ** 2) / r_max
    # 화면 좌표계(y 아래 증가)에서 12시 = -y 방향
    theta = np.arctan2(dx - cx, -(dy - cy))  # 12시=0, 시계방향 양수

    feats["r_mean"] = float(r.mean())
    feats["r_std"] = float(r.std())
    feats["r_p90"] = float(np.quantile(r, 0.9))
    feats["frac_inner"] = float((r <= R_INNER).mean())
    feats["frac_edge"] = float((r >= R_EDGE).mean())
    feats["frac_mid"] = float(((r > R_INNER) & (r < R_EDGE)).mean())

    # 각도 분포: 12방위 히스토그램 점유율 + 평균 벡터 집중도
    bins = ((theta % (2 * math.pi)) / (2 * math.pi) * ANGULAR_BINS).astype(int)
    bins = np.clip(bins, 0, ANGULAR_BINS - 1)
    occupied = np.bincount(bins, minlength=ANGULAR_BINS) > max(1, len(theta) * 0.01)
    feats["angular_coverage"] = float(occupied.mean())
    resultant = np.hypot(np.cos(theta).mean(), np.sin(theta).mean())
    feats["angular_concentration"] = float(resultant)

    if resultant >= 0.3:
        mean_theta = math.atan2(np.sin(theta).mean(), np.cos(theta).mean())
        hour = int(round((mean_theta % (2 * math.pi)) / (2 * math.pi) * 12)) % 12
        feats["clock"] = f"{12 if hour == 0 else hour}시"
    else:
        feats["clock"] = "전방위"

    # 군집 분석 (위에서 계산한 라벨링 재사용)
    labeled = labeled_comp
    sizes = comp_sizes[1:] if labeled_comp.max() else np.array([])
    big = sizes[sizes >= MIN_CLUSTER_SIZE]
    feats["n_clusters"] = int(len(big))
    largest = int(sizes.max()) if len(sizes) else 0
    feats["largest_cluster_frac"] = (largest / n_defect) if n_defect else 0.0

    # 최대 군집의 선형성 (PCA 제1주성분 설명 비율)
    feats["linearity"] = 0.0
    if largest >= MIN_CLUSTER_SIZE:
        target = int(np.argmax(sizes)) + 1
        cy2, cx2 = np.nonzero(labeled == target)
        pts = np.stack([cy2, cx2], axis=1).astype(float)
        pts -= pts.mean(axis=0)
        cov = pts.T @ pts / len(pts)
        eig = np.sort(np.linalg.eigvalsh(cov))[::-1]
        total = eig.sum()
        if total > 0:
            feats["linearity"] = float(eig[0] / total)

    feats["zone"] = _zone(feats)
    feats["shape"] = _shape(feats)
    return feats


def _zone(f: Dict[str, object]) -> str:
    if f["defect_ratio"] >= NEAR_FULL_RATIO:
        return "full"
    fracs = {"center": f["frac_inner"], "mid": f["frac_mid"], "edge": f["frac_edge"]}
    return max(fracs, key=fracs.get)


def _shape(f: Dict[str, object]) -> str:
    """기하 통계 기반 형상 판정"""
    if f["n_defect"] == 0:
        return "none"
    if f["defect_ratio"] >= NEAR_FULL_RATIO:
        return "blob"
    # 좁은 반경 대역 밀집(합성/저노이즈) 또는 edge 우세(실팹 노이즈 강건) 둘 다 링 후보.
    # 링은 둘레 전반 + 특정 방위 집중 없음. 방위 집중이 있으면 호(arc)로 격하 (Edge-Loc 구분).
    ring_radial = (f["r_std"] < 0.13 and f["r_mean"] > 0.35) or f["frac_edge"] >= 0.6
    if ring_radial and f["angular_coverage"] >= 0.7 and f["angular_concentration"] < 0.35:
        return "ring"
    if ring_radial and f["angular_coverage"] >= 0.35:
        return "arc"
    if f["linearity"] >= 0.92 and f["largest_cluster_frac"] >= 0.4:
        return "line"
    if f["largest_cluster_frac"] >= 0.5:
        return "cluster"
    if f["n_clusters"] >= 4 or f["largest_cluster_frac"] < 0.25:
        return "scatter"
    return "cluster"
