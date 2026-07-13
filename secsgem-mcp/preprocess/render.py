import numpy as np, io, base64
from PIL import Image

_PALETTE = {0: (30, 30, 40), 1: (70, 170, 90), 2: (220, 70, 70)}  # 배경/통과/불량
OUT_SIZE = (256, 256)

def render_wafer_png(die_map: np.ndarray) -> tuple[bytes, tuple[int, int]]:
    """0/1/2 die map -> PNG bytes. 원본 해상도도 함께 반환(메타용)."""
    arr = np.asarray(die_map, dtype=np.uint8)
    orig_hw = arr.shape
    rgb = np.zeros((*arr.shape, 3), dtype=np.uint8)
    for v, c in _PALETTE.items():
        rgb[arr == v] = c
    img = Image.fromarray(rgb, "RGB").resize(OUT_SIZE, Image.NEAREST)  # 보간 금지
    buf = io.BytesIO(); img.save(buf, "PNG")
    return buf.getvalue(), (orig_hw[1], orig_hw[0])

def to_base64_png(die_map: np.ndarray) -> tuple[str, tuple[int, int]]:
    png, orig = render_wafer_png(die_map)
    return base64.b64encode(png).decode(), orig