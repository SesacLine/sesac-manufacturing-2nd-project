"""few-shot 예시 이미지 자산 생성 (dev-time, 1회 실행 후 커밋)

- WM-811K Training split에서 고정 시드로 합성: fab.db와 교차점 없음
- [주의] 이미지-정답 JSON은 쌍으로 고정(prompts.FEWSHOT_EXAMPLES): 시드를 바꿔 재생성하면 예시 서술이 그 이미지와 맞는지 재검토해야 함

실행: python -m wafer_reading.vlm.gen_assets --pkl secsgem-mcp/datasets/raw/WM811K.pkl
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from ..stacking import stack_wafer_maps
from .prompts import ASSETS_DIR

SEED = 20260722
FAIL_DIE = 2


def _flat(v):
    a = np.asarray(v, dtype=object).ravel()
    return str(a[0]) if a.size else ""


def main(pkl_path: str) -> None:
    df = pd.read_pickle(pkl_path)
    df["lbl"] = df["failureType"].map(_flat)
    df["tt"] = df["trainTestLabel"].map(_flat)
    train = df[df["tt"] == "Training"]
    rng = np.random.default_rng(SEED)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    jobs = [("Center", 12, "center_stack12.png"), ("Edge-Ring", 9, "edgering_stack9.png")]
    for pattern, n, fname in jobs:
        pool = train[train["lbl"] == pattern]
        picked = pool.iloc[rng.choice(len(pool), size=n, replace=False)]
        hm = stack_wafer_maps([np.asarray(m) for m in picked["waferMap"]])
        (ASSETS_DIR / fname).write_bytes(hm.to_png_bytes())
        print(f"{fname}: {pattern} {n}장 스태킹")

    # Scratch: 단일 이미지 — 같은 시드 5장 중 결함 die 최다 웨이퍼(5장은 임의 선정)
    pool = train[train["lbl"] == "Scratch"]
    picked = pool.iloc[rng.choice(len(pool), size=5, replace=False)]
    maps = [np.asarray(m) for m in picked["waferMap"]]
    best = int(np.argmax([(m == FAIL_DIE).sum() for m in maps]))
    hm = stack_wafer_maps([maps[best]])
    (ASSETS_DIR / "scratch_single.png").write_bytes(hm.to_png_bytes())
    print("scratch_single.png: Scratch single image (selected die with most defects)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkl", default="secsgem-mcp/datasets/raw/WM811K.pkl")
    main(ap.parse_args().pkl)
