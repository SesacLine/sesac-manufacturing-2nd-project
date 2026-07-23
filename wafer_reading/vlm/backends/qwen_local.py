"""open 트랙 — Qwen3-VL-4B-Instruct 로컬 추론 백엔드

- 모델은 프로세스당 1회만 로드: 인스턴스 재사용 필수
- greedy 디코딩(do_sample=False) = temperature 0 상당. JSON schema 강제는 불가
- 최초 실행 시 HuggingFace에서 모델 자동 다운로드
"""

from __future__ import annotations

import base64
import io
import os

MODEL_ID = os.environ.get("VLM_OPEN_MODEL", "Qwen/Qwen3-VL-4B-Instruct")
MAX_NEW_TOKENS = 512


class QwenLocalBackend:
    def __init__(self, model_id: str = MODEL_ID, device_map: str = "auto"):
        try:
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor
        except ImportError as e:
            raise ImportError(
                "open track requires transformers/accelerate: uv add transformers accelerate"
            ) from e
        self._processor = AutoProcessor.from_pretrained(model_id)
        self._model = AutoModelForImageTextToText.from_pretrained(
            model_id, dtype=torch.bfloat16, device_map=device_map
        )
        self._model.eval()

    def generate(self, messages: list[dict]) -> str:
        import torch

        inputs = self._processor.apply_chat_template(
            [_to_qwen(m) for m in messages],
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        ).to(self._model.device)
        with torch.no_grad():
            out = self._model.generate(**inputs, do_sample=False, max_new_tokens=MAX_NEW_TOKENS)
        new_tokens = out[:, inputs["input_ids"].shape[1] :]
        return self._processor.batch_decode(new_tokens, skip_special_tokens=True)[0]


def _to_qwen(message: dict) -> dict:
    from PIL import Image

    content = []
    for block in message["content"]:
        if block["type"] == "text":
            content.append({"type": "text", "text": block["text"]})
        elif block["type"] == "image_png_base64":
            img = Image.open(io.BytesIO(base64.b64decode(block["data"]))).convert("RGB")
            content.append({"type": "image", "image": img})
        else:
            raise ValueError(f"unknown block type: {block['type']}")
    return {"role": message["role"], "content": content}
