"""누적 히트맵 스태킹 모듈

- 같은 결함 패턴으로 분류된 웨이퍼맵 N장의 불량 die를 공통 격자에 겹쳐 1장의 히트맵으로 합성
- 산출 이미지는 VLM 판독 입력 / few-shot 예시 / 루브릭 표본 구축에 공통 사용

- WM-811K waferMap 격자 값: 0=die 없음, 1=정상 die, 2=불량 die
- 공통 격자로 nearest 리사이즈 후 누적
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

FAIL_DIE = 2
DEFAULT_GRID = 64
DEFAULT_RENDER = 512

# die는 있으나 불량이 0인 위치의 렌더 색
_DIE_BASE_RGB = (40, 40, 52)


@dataclass
class StackedHeatmap:
    """스태킹 결과: heat[i,j] = 그 위치에 die가 있는 웨이퍼들 중 불량이었던 비율(0~1)"""

    heat: np.ndarray
    die_coverage: np.ndarray  # 그 위치에 die가 존재한 웨이퍼 비율(0~1)
    n_wafers: int
    grid_size: int
    wafer_keys: list = field(default_factory=list)  # 호출측 식별자 (lot_id, wafer_id) 등

    def to_image(self, render_size: int = DEFAULT_RENDER) -> Image.Image:
        rgb = _render_rgb(self.heat, self.die_coverage)
        img = Image.fromarray(rgb, mode="RGB")
        return img.resize((render_size, render_size), Image.NEAREST)

    def to_png_bytes(self, render_size: int = DEFAULT_RENDER) -> bytes:
        buf = io.BytesIO()
        self.to_image(render_size).save(buf, format="PNG")
        return buf.getvalue()

    def to_png_base64(self, render_size: int = DEFAULT_RENDER) -> str:
        return base64.b64encode(self.to_png_bytes(render_size)).decode("ascii")


def stack_wafer_maps(
    wafer_maps: list[np.ndarray],
    wafer_keys: list | None = None,
    grid_size: int = DEFAULT_GRID,
    min_coverage: float = 0.5,
) -> StackedHeatmap:
    if not wafer_maps:
        raise ValueError("wafer_maps is empty - at least one wafer is required")
    if wafer_keys is not None and len(wafer_keys) != len(wafer_maps):
        raise ValueError("wafer_keys length mismatch with wafer_maps")

    fail_acc = np.zeros((grid_size, grid_size), dtype=np.float32)
    die_acc = np.zeros((grid_size, grid_size), dtype=np.float32)
    for wm in wafer_maps:
        arr = np.asarray(wm)
        fail_acc += _resize_nearest((arr == FAIL_DIE).astype(np.float32), grid_size)
        die_acc += _resize_nearest((arr > 0).astype(np.float32), grid_size)

    heat = np.divide(fail_acc, die_acc, out=np.zeros_like(fail_acc), where=die_acc > 0)
    heat[die_acc < min_coverage * len(wafer_maps)] = 0.0
    return StackedHeatmap(
        heat=heat,
        die_coverage=die_acc / len(wafer_maps),
        n_wafers=len(wafer_maps),
        grid_size=grid_size,
        wafer_keys=list(wafer_keys) if wafer_keys is not None else [],
    )


def _resize_nearest(mask: np.ndarray, grid_size: int) -> np.ndarray:
    img = Image.fromarray(mask, mode="F")
    return np.asarray(img.resize((grid_size, grid_size), Image.NEAREST))


def _render_rgb(heat: np.ndarray, die_coverage: np.ndarray) -> np.ndarray:
    """heat(0~1) -> hot color (black -> red -> yellow -> white). die 없는 배경은 black, 무불량 die는 dark gray"""
    x = np.clip(heat, 0.0, 1.0)
    r = np.clip(x * 3.0, 0, 1)
    g = np.clip(x * 3.0 - 1.0, 0, 1)
    b = np.clip(x * 3.0 - 2.0, 0, 1)
    rgb = (np.stack([r, g, b], axis=-1) * 255).astype(np.uint8)

    on_die = die_coverage > 0
    no_fail = on_die & (x <= 0)
    for c, base in enumerate(_DIE_BASE_RGB):
        ch = rgb[..., c]
        ch[no_fail] = base
        ch[~on_die] = 0
    return rgb
