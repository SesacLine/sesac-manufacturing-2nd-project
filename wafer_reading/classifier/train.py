"""ResNet-18 학습 스크립트

실행:
    python -m wafer_reading.classifier.train \
        --pkl secsgem-mcp/datasets/raw/WM811K.pkl \
        --fab-db secsgem-mcp/datasets/fab.db \
        --out wafer_reading/classifier/checkpoints/resnet18_5cls.pt

설계 근거
- ResNet-18 (경량, 3채널 원핫 입력 64×64, from scratch)
- 클래스 불균형: WeightedRandomSampler(역빈도) + 가중 CrossEntropy 병행
  (Training 셋 실측: Normal 36,730 vs Scratch 500 — 73:1)
- 증강: flip/90° 회전만 — WM-811K 9종 패턴 전부 라벨 보존 변환. tensor 연산이라 보간 불필요.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset, WeightedRandomSampler
from torchvision.models import resnet18

from . import CLASSES
from .data import build_dataset_arrays


def _augment(x: torch.Tensor) -> torch.Tensor:
    """배치 단위 flip/90°회전: 전 클래스 라벨 보존(회전 및 반전 불변/공변 패턴만 존재)"""
    if torch.rand(()) < 0.5:
        x = torch.flip(x, dims=[-1])
    if torch.rand(()) < 0.5:
        x = torch.flip(x, dims=[-2])
    k = int(torch.randint(0, 4, ()))
    if k:
        x = torch.rot90(x, k, dims=[-2, -1])
    return x


def train(pkl: str, fab_db: str | None, out: str, epochs: int = 12, batch_size: int = 256) -> dict:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[1/4] data loading (device={device}) ...", flush=True)
    data = build_dataset_arrays(pkl, fab_db)
    X_train = torch.from_numpy(data["X_train"])
    y_train = torch.from_numpy(data["y_train"])
    X_eval = torch.from_numpy(data["X_eval"]).to(device)
    y_eval = torch.from_numpy(data["y_eval"])
    counts = np.bincount(data["y_train"], minlength=len(CLASSES))
    print(f"  train={len(y_train)} eval={len(y_eval)} fab.db excluded={data['excluded_count']}")
    print(f"  class distribution(train): {dict(zip(CLASSES, counts.tolist()))}", flush=True)

    # 역빈도 샘플링 + 가중 손실
    class_w = counts.sum() / np.maximum(counts, 1)
    sample_w = torch.from_numpy((class_w / class_w.sum())[data["y_train"]]).double()
    sampler = WeightedRandomSampler(sample_w, num_samples=len(y_train), replacement=True)
    loader = DataLoader(
        TensorDataset(X_train, y_train), batch_size=batch_size, sampler=sampler, drop_last=True
    )

    model = resnet18(weights=None, num_classes=len(CLASSES)).to(device)
    criterion = nn.CrossEntropyLoss(
        weight=torch.from_numpy((class_w / class_w.mean()).astype(np.float32)).to(device)
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    print("[2/4] training ...", flush=True)
    for epoch in range(epochs):
        model.train()
        t0, total, correct, loss_sum = time.time(), 0, 0, 0.0
        for xb, yb in loader:
            xb, yb = _augment(xb).to(device), yb.to(device)
            optimizer.zero_grad()
            logits = model(xb)
            loss = criterion(logits, yb)
            loss.backward()
            optimizer.step()
            loss_sum += float(loss) * len(yb)
            correct += int((logits.argmax(1) == yb).sum())
            total += len(yb)
        scheduler.step()
        print(
            f"  epoch {epoch + 1:2d}/{epochs}  loss={loss_sum / total:.4f} "
            f"acc={correct / total:.4f}  ({time.time() - t0:.1f}s)",
            flush=True,
        )

    print("[3/4] validation ...", flush=True)
    model.eval()
    preds = []
    with torch.no_grad():
        for i in range(0, len(X_eval), 1024):
            preds.append(model(X_eval[i : i + 1024]).argmax(1).cpu())
    y_pred = torch.cat(preds).numpy()
    y_true = y_eval.numpy()

    report = {}
    for idx, cls in enumerate(CLASSES):
        tp = int(((y_pred == idx) & (y_true == idx)).sum())
        fp = int(((y_pred == idx) & (y_true != idx)).sum())
        fn = int(((y_pred != idx) & (y_true == idx)).sum())
        report[cls] = {
            "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
            "recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
            "support": int((y_true == idx).sum()),
        }
    report["overall_accuracy"] = round(float((y_pred == y_true).mean()), 4)
    print(json.dumps(report, ensure_ascii=False, indent=1), flush=True)

    print("[4/4] saving ...", flush=True)
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {"state_dict": model.state_dict(), "classes": CLASSES, "eval_report": report}, out_path
    )
    print(f"saved: {out_path}", flush=True)
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkl", required=True)
    ap.add_argument("--fab-db", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=12)
    args = ap.parse_args()
    train(args.pkl, args.fab_db, args.out, epochs=args.epochs)
