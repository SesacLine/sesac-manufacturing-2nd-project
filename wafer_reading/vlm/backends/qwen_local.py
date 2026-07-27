"""open 트랙 — Qwen3-VL-8B-Instruct 로컬 추론 백엔드

- 모델은 프로세스당 1회만 로드: 인스턴스 재사용 필수
- greedy 디코딩(do_sample=False) = temperature 0 상당. JSON schema 강제는 불가
- **가중치는 사전 다운로드가 전제다 — 런타임에 받지 않는다**(`local_files_only=True`).
  캐시에 없으면 즉시 실패하고 준비 명령을 안내한다. 배포 시 이미지/볼륨에 미리 굽고
  `HF_HOME`으로 위치를 지정한다(`sdoubleoj/0727 work/VLM_오픈모델_서빙_설계서_v1.0.md`).
- 로드 시 patch_embed 가속 패치를 적용한다(발견문제 #24) — 아래 _apply_fast_patchify 참고
"""

from __future__ import annotations

import base64
import io
import os

MODEL_ID = os.environ.get("VLM_OPEN_MODEL", "Qwen/Qwen3-VL-8B-Instruct")
MAX_NEW_TOKENS = 512
# 4B 모델은 GPU 1장에 통째로 올라간다. "auto"로 두면 accelerate가 여러 장에 흩어 놓아
# 층마다 device 간 전송이 끼므로(#24 실측 39.6s vs 37.9s) 기본을 한 장으로 고정한다.
DEVICE_MAP = os.environ.get("VLM_OPEN_DEVICE_MAP", "cuda:0")


class QwenLocalBackend:
    def __init__(self, model_id: str = MODEL_ID, device_map: str | None = None):
        try:
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor
        except ImportError as e:
            raise ImportError(
                "open track requires transformers/accelerate: uv add transformers accelerate"
            ) from e
        if device_map is None:
            device_map = DEVICE_MAP if torch.cuda.is_available() else "auto"
        try:
            self._processor = AutoProcessor.from_pretrained(model_id, local_files_only=True)
            self._model = AutoModelForImageTextToText.from_pretrained(
                model_id, dtype=torch.bfloat16, device_map=device_map, local_files_only=True
            )
        except OSError as e:  # 캐시 미스 — 런타임 다운로드는 하지 않는다
            raise RuntimeError(
                f"open track weights not found locally: {model_id}\n"
                f"  준비: hf download {model_id}   (HF_HOME으로 위치 지정 가능)\n"
                f"  GPU/가중치 없는 환경은 VLM_TRACK=pty(기본)를 쓸 것."
            ) from e
        self._model.eval()
        self.fast_patchify = _apply_fast_patchify(self._model)

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


def _linear_patchify(conv):
    """`kernel_size == stride`인 Conv3d를 등가 행렬곱 forward로 바꾼다.

    커널과 stride가 같으면 윈도가 겹치지 않으므로 이 컨볼루션은 "패치를 평탄화해 가중치와
    곱한다"와 완전히 같은 연산이다 — 가중치 (out, in, T, P, P)를 (out, in*T*P*P)로 펴서
    쓰면 결과가 일치한다(bf16 반올림 차이만 남는다).
    """
    import torch

    weight = conv.weight.detach().reshape(conv.weight.shape[0], -1)
    bias = None if conv.bias is None else conv.bias.detach()

    def forward(hidden_states):
        flat = hidden_states.reshape(-1, weight.shape[1]).to(weight.dtype)
        return torch.nn.functional.linear(flat, weight, bias)

    return forward


def _apply_fast_patchify(model) -> bool:
    """Qwen3-VL `patch_embed`의 bf16 Conv3d 우회 (발견문제 #24). 적용 여부를 돌려준다.

    `nn.Conv3d(3 -> 1152, kernel=stride=(2,16,16))`가 bf16에서 cuDNN 커널을 못 잡고 폴백해,
    패치 4096개(이미지 4장)에 **38초**가 걸린다 — 같은 forward의 transformer 블록 24개가
    합쳐서 25ms인 것과 비교하면 이 한 줄이 호출 시간의 89%다. 어텐션 구현·GPU 장수와는
    무관하며(eager≡sdpa, 1장≡4장) `cudnn.benchmark`로도 안 풀린다. 등가 행렬곱은 0.1ms.

    transformers 내부 구조(`model.visual.patch_embed.proj`)에 의존하는 우회이므로, 구조가
    바뀌면 조용히 틀리는 대신 **패치를 포기하고 원래 경로로 돌아간다**: 형상 전제를 확인하고
    작은 입력으로 원본과 수치를 대조해 통과할 때만 forward를 교체한다.
    `VLM_OPEN_FAST_PATCHIFY=0`으로 끌 수 있다(원인 재확인·A/B용).
    """
    if os.environ.get("VLM_OPEN_FAST_PATCHIFY", "1").lower() in ("0", "false", "no"):
        return False

    import math

    import torch

    try:
        patch_embed = model.model.visual.patch_embed
        conv = patch_embed.proj
    except AttributeError:  # 구조 변경 — 원래 경로 유지
        return False
    if not isinstance(conv, torch.nn.Conv3d) or tuple(conv.kernel_size) != tuple(conv.stride):
        return False

    fast = _linear_patchify(conv)
    probe = torch.randn(
        8,
        conv.in_channels * math.prod(conv.kernel_size),
        device=conv.weight.device,
        dtype=conv.weight.dtype,
    )
    try:
        with torch.no_grad():
            expected, actual = patch_embed(probe), fast(probe)
    except Exception:  # noqa: BLE001 — 대조 자체가 실패하면 우회를 포기한다
        return False
    if expected.shape != actual.shape:
        return False
    # bf16 누산 순서 차이만 허용(실측 최대 절대오차 1.56e-02) — 구조가 어긋나면 훨씬 크게 벌어진다
    if (expected - actual).abs().max() > 0.05 * expected.abs().max() + 1e-2:
        return False

    patch_embed.forward = fast
    return True


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
