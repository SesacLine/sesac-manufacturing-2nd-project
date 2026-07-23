"""wafer_reading 기하 통계 임계값.

quantitative.py가 스택맵 → KG 어휘(shape/zone/angular/clock/density/continuity)로
정량화할 때 쓰는 상수. 임계는 합성/실팹 맵 실측으로 조정 대상이며, 여기 한곳에 모아둔다.

출력 어휘는 KG 스키마(docs/KG_schema_v1.4.md)의 고정 enum에 맞춘다:
  shape ∈ {ring, cluster, line, blob, global, random}
  zone  ∈ {center, mid, edge, any}
  angular_coverage ∈ {full, partial, unknown}
  density ∈ {high, medium, low, unknown}
  continuity ∈ {continuous, intermittent, discontinuous, not_applicable, unknown}
"""

from __future__ import annotations

# --- 스택맵 → 이진 마스크 ---
# StackedHeatmap.heat[i,j] = 그 위치에 die가 있던 웨이퍼들 중 불량이었던 비율(0~1).
# 그룹의 "공통 불량 위치"로 볼 임계 — 과반이 불량이면 그룹 결함으로 취급.
DEFECT_HEAT_THRESHOLD = 0.5

# --- 반경 구역 (정규화 반경 0~1, 중심=0 / 최외곽=1) ---
# geometry 작성자 제공 기준값
R_INNER = 0.35   # center: r <= R_INNER
R_EDGE = 0.80    # edge:   r >= R_EDGE   (mid = 그 사이)

# --- 각도 분포 ---
ANGULAR_BINS = 12                 # 12방위(시계) 히스토그램 (geometry 작성자 제공)
ANGULAR_FULL = 0.7                # 점유 방위 비율 >= → 전방위(full) 후보
ANGULAR_PARTIAL = 0.35            # >= → 부분(partial)
ANGULAR_CONCENTRATION_MAX = 0.35  # 평균벡터 집중도 < 이 값이어야 "균등"(full); 이상이면 방위 편중
CLOCK_MIN_CONCENTRATION = 0.3     # 대표 시각(clock) 인정에 필요한 최소 집중도

# --- 군집 --- (geometry 작성자 제공 기준값)
MIN_CLUSTER_SIZE = 3              # 이보다 작은 connected component는 노이즈 취급
NEAR_FULL_RATIO = 0.55           # defect_die_ratio >= → near-full(global)

# --- 형상 판정 ---
RING_RSTD_MAX = 0.13             # 반경 표준편차 < → 좁은 반경 대역(링 후보)
RING_RMEAN_MIN = 0.35            # 평균 반경 > → 중심에서 떨어짐(링 후보)
RING_EDGE_FRAC = 0.6             # edge 점유 >= → 링 후보(실팹 노이즈 강건)
LINE_LINEARITY_MIN = 0.92        # 최대군집 PCA 선형성 >= → line
LINE_CLUSTER_FRAC_MIN = 0.4      # + 최대군집이 전체의 이 비율 이상
CLUSTER_FRAC_MIN = 0.5           # 최대군집 비율 >= → 밀집(cluster)
SCATTER_CLUSTERS_MIN = 4         # 군집 수 >= → 산발(random)
SCATTER_CLUSTER_FRAC_MAX = 0.25  # 또는 최대군집 비율 < → 산발(random)

# --- 밀도 (defect_die_ratio 기준) ---
DENSITY_HIGH = 0.15              # >= → high
DENSITY_MEDIUM = 0.05           # >= → medium (그 미만이며 0 초과 → low)

# --- 연속성 (링 형상 한정) ---
CONTINUITY_FULL_ANGULAR = 0.8    # 방위 점유 >= 이고 군집 적으면 continuous
CONTINUITY_MAX_CLUSTERS = 2      # 연속 링으로 볼 최대 군집 수
