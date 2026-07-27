"""qwen_local의 patch_embed 가속 패치 테스트 (발견문제 #24): GPU/모델 다운로드 없이 돎.

`Qwen3VLVisionPatchEmbed`와 같은 형상의 Conv3d 모듈을 합성해, 등가 행렬곱이 원본과 같은 값을
내는지와 전제가 깨질 때 패치를 포기하는지를 본다. 실제 모델 로드는 이 테스트 범위 밖.
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from wafer_reading.vlm.backends.qwen_local import (  # noqa: E402
    _apply_fast_patchify,
    _linear_patchify,
)

# Qwen3-VL 비전 타워의 실제 형상(축소판): Conv3d(3 -> EMB, kernel=stride=(2,16,16))
C, T, P, EMB = 3, 2, 16, 8
PATCH_DIM = C * T * P * P


class _PatchEmbed(torch.nn.Module):
    """transformers의 Qwen3VLVisionPatchEmbed.forward와 같은 계산."""

    def __init__(self, kernel=(T, P, P), stride=(T, P, P)):
        super().__init__()
        self.proj = torch.nn.Conv3d(C, EMB, kernel_size=list(kernel), stride=list(stride), bias=True)

    def forward(self, hidden_states):
        x = hidden_states.view(-1, C, T, P, P).to(self.proj.weight.dtype)
        return self.proj(x).view(-1, EMB)


class _FakeModel:
    """`model.model.visual.patch_embed` 경로만 흉내낸 껍데기."""

    def __init__(self, patch_embed):
        visual = type("_V", (), {"patch_embed": patch_embed})()
        inner = type("_M", (), {"visual": visual})()
        self.model = inner


def _probe(n: int = 8) -> torch.Tensor:
    torch.manual_seed(0)
    return torch.randn(n, PATCH_DIM)


def test_linear_patchify_matches_conv3d():
    pe = _PatchEmbed().eval()
    x = _probe()
    with torch.no_grad():
        expected = pe(x)
        actual = _linear_patchify(pe.proj)(x)
    assert actual.shape == expected.shape
    assert torch.allclose(actual, expected, atol=1e-4)


def test_apply_fast_patchify_replaces_forward_and_preserves_output():
    pe = _PatchEmbed().eval()
    model = _FakeModel(pe)
    x = _probe()
    with torch.no_grad():
        before = pe(x)

    assert _apply_fast_patchify(model) is True

    with torch.no_grad():
        after = pe(x)
    assert torch.allclose(after, before, atol=1e-4)


def test_apply_fast_patchify_skips_when_kernel_differs_from_stride():
    """윈도가 겹치면 행렬곱 등가가 성립하지 않으므로 패치하지 않아야 한다."""
    pe = _PatchEmbed(kernel=(T, P, P), stride=(T, P // 2, P // 2)).eval()
    original_forward = pe.forward

    assert _apply_fast_patchify(_FakeModel(pe)) is False
    assert pe.forward == original_forward


def test_apply_fast_patchify_skips_on_unexpected_structure():
    model = type("_NoVisual", (), {"model": object()})()
    assert _apply_fast_patchify(model) is False


def test_apply_fast_patchify_can_be_disabled(monkeypatch):
    monkeypatch.setenv("VLM_OPEN_FAST_PATCHIFY", "0")
    pe = _PatchEmbed().eval()
    original_forward = pe.forward

    assert _apply_fast_patchify(_FakeModel(pe)) is False
    assert pe.forward == original_forward
