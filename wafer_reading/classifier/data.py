"""WM-811K 학습 데이터 전처리 모듈

- split:
    - WM-811K `trainTestLabel` 기준 train 셋 내에서 train:eval = 9:1 (클래스 층화, 시드 고정)
    - test 셋은 최종 벤치마크 + fab.db 전용이라 본 모듈에서 건들지 않음
- 누출 차단(임시)
    - 현 fab.db는 trainTestLabel 무관 전체 샘플링이라, fab.db에 등재된 (lot_id, wafer_id) 웨이퍼를 학습 및 검증에서 제외함
    - fab.db가 Test-only로 재생성되면 이 규칙은 제거됨
- 5클래스 리매핑:
    - Center/Edge-Ring/Scratch 유지
    - none -> Normal
    - Donut/Edge-Loc/Loc/Near-full/Random -> Unknown

secsgem-mcp의 preprocess.wm811k_loader는 trainTestLabel을 버리므로 여기서 직접 읽음
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

from . import CLASSES

INPUT_SIZE = 64  # 리사이즈 목표 격자 크기: 값 오염 방지를 위해 nearest 고정
_UNKNOWN_SOURCES = {"Donut", "Edge-Loc", "Loc", "Near-full", "Random"}
_CLASS_INDEX = {name: i for i, name in enumerate(CLASSES)}


def _flat_label(v) -> str:
    a = np.asarray(v, dtype=object).ravel()
    if not a.size:
        return ""
    s = str(a[0])
    return "" if s in ("0", "0.0", "nan", "None") else s


def to_5class(raw_label: str) -> str | None:
    """WM-811K 9-class label -> 5-class"""
    if not raw_label:
        return None
    if raw_label == "none":
        return "Normal"
    if raw_label in _UNKNOWN_SOURCES:
        return "Unknown"
    if raw_label in ("Center", "Edge-Ring", "Scratch"):
        return raw_label
    raise ValueError(f"unknown WM-811K label: {raw_label!r}")


def fab_db_wafer_keys(fab_db_path: str | Path) -> set[tuple[str, str]]:
    """fab.db에 등재된 (lot_id, wafer_id) -> 학습 제외 대상"""
    con = sqlite3.connect(f"file:{fab_db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT lot_id, wafer_id FROM wafer WHERE source = 'wm811k'"
        ).fetchall()
    finally:
        con.close()
    return {(str(lot), str(wid)) for lot, wid in rows}


def preprocess_map(wafer_map: np.ndarray) -> np.ndarray:
    """웨이퍼맵(H,W; 값 0/1/2) -> (3, 64, 64) float32 one-hot 채널(no-die/pass/fail)"""
    arr = np.asarray(wafer_map, dtype=np.uint8)
    img = Image.fromarray(arr, mode="L").resize((INPUT_SIZE, INPUT_SIZE), Image.NEAREST)
    resized = np.asarray(img)
    return np.stack([(resized == v).astype(np.float32) for v in (0, 1, 2)])


def build_dataset_arrays(
    pkl_path: str | Path,
    fab_db_path: str | Path | None,
    eval_ratio: float = 0.1,
    seed: int = 20260722,
) -> dict:
    """Training split 라벨 웨이퍼를 (X, y)로 변환하고 클래스 층화 9:1로 나눔

    반환: {"X_train", "y_train", "X_eval", "y_eval", "excluded_count"}
    y는 CLASSES 인덱스. X는 (N, 3, 64, 64) float32.
    """
    df = pd.read_pickle(pkl_path)
    df["raw_label"] = df["failureType"].map(_flat_label)
    df["tt"] = df["trainTestLabel"].map(_flat_label)
    pool = df[(df["tt"] == "Training") & (df["raw_label"] != "")].copy()
    pool["cls"] = pool["raw_label"].map(to_5class)

    excluded = 0
    if fab_db_path is not None:
        fab_keys = fab_db_wafer_keys(fab_db_path)
        keys = list(
            zip(pool["lotName"].astype(str), pool["waferIndex"].astype("Int64").astype(str))
        )
        mask = np.array([k not in fab_keys for k in keys])
        excluded = int((~mask).sum())
        pool = pool[mask]

    rng = np.random.default_rng(seed)
    train_idx: list[int] = []
    eval_idx: list[int] = []
    for cls in CLASSES:
        cls_pos = np.flatnonzero((pool["cls"] == cls).to_numpy())
        rng.shuffle(cls_pos)
        n_eval = max(1, int(round(len(cls_pos) * eval_ratio)))
        eval_idx.extend(cls_pos[:n_eval])
        train_idx.extend(cls_pos[n_eval:])

    maps = pool["waferMap"].to_numpy()
    labels = pool["cls"].map(_CLASS_INDEX).to_numpy()

    def _stack(indices: list[int]) -> tuple[np.ndarray, np.ndarray]:
        X = np.stack([preprocess_map(maps[i]) for i in indices])
        return X, labels[np.asarray(indices)]

    X_train, y_train = _stack(train_idx)
    X_eval, y_eval = _stack(eval_idx)
    return {
        "X_train": X_train,
        "y_train": y_train.astype(np.int64),
        "X_eval": X_eval,
        "y_eval": y_eval.astype(np.int64),
        "excluded_count": excluded,
    }
