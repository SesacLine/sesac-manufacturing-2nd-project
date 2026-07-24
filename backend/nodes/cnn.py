"""① CNN 결함 패턴 판정 — 웨이퍼 1장당 1건, 5클래스(Center/Edge-Ring/Scratch/Unknown/Normal).

ResNet-18 실연동(wafer_reading.classifier): 체크포인트가 있으면 die_map을 실판독하고,
없으면(CI·미학습 환경) 기존 스켈레톤 하드코딩("Center")으로 폴백해 파이프라인이 끊기지
않게 한다 — vlm_describe/quantitative의 폴백 정책과 동일한 태도.

체크포인트 경로: 환경변수 CNN_CKPT (기본 wafer_reading/classifier/checkpoints/resnet18_5cls.pt).
분류기는 모듈 레벨 싱글턴 — 로드가 무거워 프로세스당 1회만 (MCPClient와 같은 이유).
"""

from __future__ import annotations

import io
import os
import sqlite3

import numpy as np

from ..state import RCAState

_DEFAULT_CKPT = "wafer_reading/classifier/checkpoints/resnet18_5cls.pt"
# 폴백(체크포인트 없음) 전용 — Walking Skeleton 시절 임시값을 유지해 무모델 환경에서도 돈다.
_FALLBACK_PATTERN = "Center"

_classifier = None
_classifier_failed = False  # 로드 실패를 기억해 웨이퍼마다 재시도하지 않는다


def _get_classifier():
    global _classifier, _classifier_failed
    if _classifier is None and not _classifier_failed:
        ckpt = os.environ.get("CNN_CKPT", _DEFAULT_CKPT)
        if not os.path.exists(ckpt):
            _classifier_failed = True
            return None
        try:
            from wafer_reading.classifier.infer import WaferClassifier

            _classifier = WaferClassifier(ckpt)
        except Exception:  # noqa: BLE001 — torch 미설치/체크포인트 손상 → 폴백
            _classifier_failed = True
    return _classifier


def read_wafer_maps(state: RCAState) -> dict:
    """target_lot_ids의 웨이퍼 die_map을 ResNet으로 판정해 cnn_results를 채운다."""
    lot_ids = state["target_lot_ids"]
    if not lot_ids:
        return {"cnn_results": []}

    con = sqlite3.connect(os.environ["FAB_DB"])
    con.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(lot_ids))
    rows = con.execute(
        f"SELECT lot_id, wafer_id, die_map FROM wafer WHERE lot_id IN ({placeholders})", lot_ids
    ).fetchall()
    con.close()

    clf = _get_classifier()
    keys, die_maps, no_map_keys = [], [], []
    for row in rows:
        if clf is not None and row["die_map"] is not None:
            keys.append((row["lot_id"], row["wafer_id"]))
            die_maps.append(np.load(io.BytesIO(row["die_map"]), allow_pickle=False))
        else:
            no_map_keys.append((row["lot_id"], row["wafer_id"]))

    cnn_results = []
    if die_maps:
        for (lot_id, wafer_id), pred in zip(keys, clf.classify_batch(die_maps)):
            cnn_results.append(_result(lot_id, wafer_id, pred["pattern"], pred["confidence"]))
    # die_map 없는 웨이퍼 또는 무모델 환경 → 폴백 패턴
    for lot_id, wafer_id in no_map_keys:
        cnn_results.append(_result(lot_id, wafer_id, _FALLBACK_PATTERN, 0.5))
    return {"cnn_results": cnn_results}


def _result(lot_id: str, wafer_id: str, pattern: str, confidence: float):
    # 소비자(grouper/batch_runner)는 pattern만 쓰고 confidence=0.5로 폴백 여부를 드러냄.
    return {
        "lot_id": lot_id,
        "wafer_id": wafer_id,
        "pattern": pattern,
        "confidence": confidence,
    }
