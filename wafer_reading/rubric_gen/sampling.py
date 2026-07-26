"""평가 표본 추출 — WM-811K Training split을 루브릭용/평가용으로 **불교차 분할**

- fab.db는 Test split 유래라 Training split을 쓰면 운영 데이터와 교차하지 않는다(설계서 v2.0 §2).
- 루브릭을 만든 표본으로 다시 채점하면 자기충족이 되므로, 같은 시드의 고정 순열을 반으로 갈라
  앞쪽 절반 = 루브릭 풀 / 뒤쪽 절반 = 평가 풀로 **구조적으로** 분리한다(시드만 다르게 하는
  방식은 겹칠 수 있다).
- ⚠️ few-shot 예시 자산(`vlm/gen_assets.py`)은 선택된 웨이퍼 키를 기록하지 않아 여기서 제외할
  수 없다(발견문제 로그 #11). 예시 3장과의 우연한 중복 가능성은 남는다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SAMPLING_SEED = 20260726
POOLS = ("rubric", "eval")
DEFAULT_PKL = "secsgem-mcp/datasets/raw/WM811K.pkl"


def _flat(v) -> str:
    a = np.asarray(v, dtype=object).ravel()
    return str(a[0]) if a.size else ""


def load_training_df(pkl_path: str | Path = DEFAULT_PKL) -> pd.DataFrame:
    """WM-811K pkl → Training split만 남긴 DataFrame(lbl 컬럼 부착)."""
    df = pd.read_pickle(pkl_path)
    df["lbl"] = df["failureType"].map(_flat)
    df["tt"] = df["trainTestLabel"].map(_flat)
    return df[df["tt"] == "Training"]


def split_pool(df: pd.DataFrame, pattern: str, pool: str) -> pd.DataFrame:
    """패턴 풀을 고정 순열로 섞어 rubric/eval 절반으로 자른다(불교차 보장)."""
    if pool not in POOLS:
        raise ValueError(f"unknown pool: {pool!r} ({'|'.join(POOLS)})")
    sub = df[df["lbl"] == pattern]
    order = np.random.default_rng(SAMPLING_SEED).permutation(len(sub))
    half = len(order) // 2
    idx = order[:half] if pool == "rubric" else order[half:]
    return sub.iloc[idx]


def sample_groups(
    df: pd.DataFrame, pattern: str, pool: str, n_groups: int, group_size: int
) -> list[dict]:
    """그룹 n개 추출 — 그룹끼리도 웨이퍼가 겹치지 않도록 연속 청크로 자른다.

    반환: [{"group_id", "maps"(np.ndarray 리스트), "wafer_keys"[(lotName, waferIndex)]}]
    """
    picked = split_pool(df, pattern, pool)
    need = n_groups * group_size
    if len(picked) < need:
        raise ValueError(f"{pattern}/{pool} pool too small: {len(picked)} < {need}")

    groups = []
    for g in range(n_groups):
        chunk = picked.iloc[g * group_size : (g + 1) * group_size]
        groups.append(
            {
                "group_id": f"{pattern}-{pool}-{g:02d}",
                "maps": [np.asarray(m) for m in chunk["waferMap"]],
                "wafer_keys": list(
                    zip(
                        chunk["lotName"].astype(str),
                        chunk["waferIndex"].astype("Int64").astype(str),
                    )
                ),
            }
        )
    return groups
