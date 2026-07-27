"""ResNet-18 학습 스크립트

실행:
    python -m wafer_reading.classifier.train \
        --pkl secsgem-mcp/datasets/raw/WM811K.pkl \
        --fab-db secsgem-mcp/datasets/fab.db \
        --out wafer_reading/classifier/checkpoints/resnet18_5cls.pt

설계 근거
- ResNet-18 (경량, 3채널 원핫 입력 64×64, from scratch)
- 증강: flip/90° 회전만 — WM-811K 9종 패턴 전부 라벨 보존 변환. tensor 연산이라 보간 불필요.
- 클래스 불균형(Training 셋 실측: Normal 36,730 vs Scratch 500 — 73:1): `--balance` 참고.

⚠️ **가중 CrossEntropy를 다시 넣지 말 것.** 73:1 불균형에서 클래스 가중 손실은 소수 클래스의
그래디언트만 73배로 키워 결정 경계를 밀어버린다 — recall은 높고 precision이 무너진다.
4종 비교 실측(같은 시드, 같은 평가셋)에서 Scratch precision이 갈렸다:
    가중 손실 있음  both 0.434 / loss 0.436
    가중 손실 없음  sampler 0.904 / sqrt 0.918
샘플러 유무와는 무관하다. 표본을 더 자주 보여주는(샘플러) 쪽이 그래디언트를 키우는 쪽보다
안정적이다. 이 발견 이전의 기본값은 `both`였고 배포 체크포인트가 그 산물이다(precision 0.49).
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


BALANCE_STRATEGIES = ("sampler", "loss", "sqrt", "both")
DEFAULT_BALANCE = "sampler"
DEFAULT_SEED = 20260727


def _make_loader_and_criterion(
    X_train, y_train, y_np, counts, balance: str, batch_size: int, device: str
):
    """불균형 보정 전략 하나만 사용

    sampler: 역빈도 오버샘플링 + 평범한 손실  (기본)
    loss   : 평범한 셔플 + 역빈도 가중 손실
    sqrt   : 완화된 오버샘플링(1/√freq) + 평범한 손실 — 소수 클래스 반복 노출을 줄임
    both   : 둘 다 — 과보정(비교 실험 재현용으로만 남김)
    """
    if balance not in BALANCE_STRATEGIES:
        raise ValueError(f"unknown balance: {balance!r} ({'|'.join(BALANCE_STRATEGIES)})")

    inv_freq = counts.sum() / np.maximum(counts, 1)
    dataset = TensorDataset(X_train, y_train)

    if balance == "loss":
        loader = DataLoader(dataset, batch_size=batch_size, shuffle=True, drop_last=True)
    else:
        per_class = np.sqrt(inv_freq) if balance == "sqrt" else inv_freq
        sample_w = torch.from_numpy((per_class / per_class.sum())[y_np]).double()
        sampler = WeightedRandomSampler(sample_w, num_samples=len(y_train), replacement=True)
        loader = DataLoader(dataset, batch_size=batch_size, sampler=sampler, drop_last=True)

    if balance in ("loss", "both"):
        w = torch.from_numpy((inv_freq / inv_freq.mean()).astype(np.float32)).to(device)
        criterion = nn.CrossEntropyLoss(weight=w)
    else:
        criterion = nn.CrossEntropyLoss()
    return loader, criterion


def train(
    pkl: str,
    fab_db: str | None,
    out: str,
    epochs: int = 12,
    batch_size: int = 256,
    balance: str = DEFAULT_BALANCE,
    seed: int = DEFAULT_SEED,
) -> dict:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    # 시드 고정
    torch.manual_seed(seed)
    if device == "cuda":
        torch.cuda.manual_seed_all(seed)
    print(f"[1/4] data loading (device={device}, balance={balance}, seed={seed}) ...", flush=True)
    data = build_dataset_arrays(pkl, fab_db)
    X_train = torch.from_numpy(data["X_train"])
    y_train = torch.from_numpy(data["y_train"])
    X_eval = torch.from_numpy(data["X_eval"]).to(device)
    y_eval = torch.from_numpy(data["y_eval"])
    counts = np.bincount(data["y_train"], minlength=len(CLASSES))
    print(f"  train={len(y_train)} eval={len(y_eval)} fab.db excluded={data['excluded_count']}")
    print(f"  class distribution(train): {dict(zip(CLASSES, counts.tolist()))}", flush=True)

    loader, criterion = _make_loader_and_criterion(
        X_train, y_train, data["y_train"], counts, balance, batch_size, device
    )

    model = resnet18(weights=None, num_classes=len(CLASSES)).to(device)
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
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        report[cls] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            # 과보정은 "recall만 높고 precision이 무너지는" 형태로 나타나므로 F1이 있어야
            # 약점 클래스가 한눈에 보인다(precision/recall만으로는 놓치기 쉽다).
            "f1": round(2 * precision * recall / (precision + recall), 4)
            if precision + recall
            else 0.0,
            "support": int((y_true == idx).sum()),
        }
    report["overall_accuracy"] = round(float((y_pred == y_true).mean()), 4)
    # Normal이 전체의 2/3라 전체 정확도는 소수 클래스 붕괴를 가린다 — macro F1을 같이 남긴다.
    report["macro_f1"] = round(float(np.mean([report[c]["f1"] for c in CLASSES])), 4)
    report["config"] = {"balance": balance, "seed": seed, "epochs": epochs}
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
    ap.add_argument(
        "--balance",
        default=DEFAULT_BALANCE,
        choices=BALANCE_STRATEGIES,
        help="클래스 불균형 보정 (기본 sampler). loss/both는 precision이 무너진다 — 비교 실험용",
    )
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = ap.parse_args()
    train(
        args.pkl,
        args.fab_db,
        args.out,
        epochs=args.epochs,
        balance=args.balance,
        seed=args.seed,
    )
