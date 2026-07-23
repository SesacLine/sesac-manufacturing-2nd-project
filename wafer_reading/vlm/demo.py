"""E2E 데모 — WM-811K Training split에서 그룹을 하나 뽑아 판독 전 경로를 태움

    python -m wafer_reading.vlm.demo --track pty --pattern Edge-Ring --n 9
    python -m wafer_reading.vlm.demo --track open --pattern Scratch --n 5   # 최초 실행 시 모델 다운로드

pty는 .env의 OPENAI_API_KEY 필요. 출력: backend Observation + total_description JSON.
(CNN 판독까지 포함한 경로는 classifier 체크포인트 필요 — --with-cnn 참고)
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from .adapter import VLMReader
from .gen_assets import SEED, _flat


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkl", default="secsgem-mcp/datasets/raw/WM811K.pkl")
    ap.add_argument("--track", default=None, help="open|pty (default: VLM_TRACK env or open)")
    ap.add_argument("--pattern", default="Edge-Ring", choices=["Center", "Edge-Ring", "Scratch"])
    ap.add_argument("--n", type=int, default=9, help="group wafer count")
    ap.add_argument("--with-cnn", default=None, metavar="CKPT",
                    help="classifier checkpoint path - if given, CNN results are also output")
    args = ap.parse_args()

    print(f"[1/3] load WM-811K -> sample {args.pattern} group {args.n} wafers (Training split)")
    df = pd.read_pickle(args.pkl)
    df["lbl"] = df["failureType"].map(_flat)
    df["tt"] = df["trainTestLabel"].map(_flat)
    pool = df[(df["tt"] == "Training") & (df["lbl"] == args.pattern)]
    rng = np.random.default_rng(SEED + 1)  # few-shot 자산과 다른 시드 : 예시-쿼리 불교차 방지
    picked = pool.iloc[rng.choice(len(pool), size=args.n, replace=False)]
    maps = [np.asarray(m) for m in picked["waferMap"]]
    keys = list(zip(picked["lotName"].astype(str), picked["waferIndex"].astype("Int64").astype(str)))

    if args.with_cnn:
        from ..classifier.infer import WaferClassifier

        clf = WaferClassifier(args.with_cnn)
        preds = clf.classify_batch(maps)
        agree = sum(p["pattern"] == args.pattern for p in preds)
        print(f"[2/3] CNN classification: {agree}/{len(preds)} wafers are {args.pattern}")
    else:
        print("[2/3] CNN skipped (--with-cnn not specified) -> consider group label as CNN result")

    reader = VLMReader(track=args.track)
    print(f"[3/3] VLM call (track={reader.track}) ...")
    result = reader.describe_group(args.pattern, maps, wafer_keys=keys)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
