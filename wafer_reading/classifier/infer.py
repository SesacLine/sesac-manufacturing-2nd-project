"""판독 추론 : 런타임에서 backend "CNN 개별 판독" 노드가 쓰는 인터페이스

체크포인트는 모듈 레벨에서 1회만 로드해 재사용함
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from torchvision.models import resnet18

from . import CLASSES
from .data import preprocess_map


class WaferClassifier:
    """ResNet-18 5-class classifier: wafer map array(0/1/2 grid) -> {pattern, confidence}"""

    def __init__(self, checkpoint_path: str | Path, device: str | None = None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        ckpt = torch.load(checkpoint_path, map_location=self.device, weights_only=True)
        if ckpt["classes"] != CLASSES:
            raise ValueError(f"checkpoint class mismatch: {ckpt['classes']}")
        self.model = resnet18(weights=None, num_classes=len(CLASSES)).to(self.device)
        self.model.load_state_dict(ckpt["state_dict"])
        self.model.eval()

    @torch.no_grad()
    def classify(self, wafer_map: np.ndarray) -> dict:
        x = torch.from_numpy(preprocess_map(wafer_map)).unsqueeze(0).to(self.device)
        probs = torch.softmax(self.model(x), dim=1)[0]
        idx = int(probs.argmax())
        return {"pattern": CLASSES[idx], "confidence": round(float(probs[idx]), 4)}

    @torch.no_grad()
    def classify_batch(self, wafer_maps: list[np.ndarray], batch_size: int = 512) -> list[dict]:
        results: list[dict] = []
        for i in range(0, len(wafer_maps), batch_size):
            x = torch.from_numpy(
                np.stack([preprocess_map(m) for m in wafer_maps[i : i + batch_size]])
            ).to(self.device)
            probs = torch.softmax(self.model(x), dim=1)
            for row in probs:
                idx = int(row.argmax())
                results.append(
                    {"pattern": CLASSES[idx], "confidence": round(float(row[idx]), 4)}
                )
        return results
