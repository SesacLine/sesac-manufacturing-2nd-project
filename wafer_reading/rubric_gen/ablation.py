"""이미지 의존성 어블레이션 — VLM이 이미지를 보고 답하는가, 라벨을 따라 답하는가 (dev 전용)

발견문제 #18 재현·회귀 측정용. **CNN 라벨과 이미지를 어긋나게 주고** 서술이 어느 쪽을 따르는지 본다.

두 실험:
  실험1 — **운영 경로 그대로**(`describe_group(label, maps)`)에 라벨과 다른 이미지를 준다.
           라벨이 프롬프트에 들어가면 서술이 라벨을 따라가고, 안 들어가면 이미지를 따라간다.
           수정 전후를 같은 호출로 비교할 수 있어 이 파일의 핵심이다.
  실험2 — 라벨 없이 이미지만 준다(대조군). 모델이 이미지 자체는 정확히 읽는지 확인 —
           원인이 전송 버그가 아니라 프롬프트의 라벨 prior임을 분리해 보여준다.

합격 기준(#18):
  - B(빈 웨이퍼 + Center 라벨): "결함 없음"을 말해야 한다. 없는 결함을 서술하면 실패.
  - C·D(라벨과 이미지 상반): 이미지를 따라야 한다.
  - A·E·F·G: 기존 정확도 유지.

실행:
    python -m wafer_reading.rubric_gen.ablation --out wafer_reading/rubric_gen/outputs
    (API 호출 7건. `--track`으로 트랙 지정, 기본은 VLM_TRACK env)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ..stacking import stack_wafer_maps
from ..vlm.adapter import VLMReader, _parse_response, build_messages

from .evaluate import load_fixed_rubrics
from .sampling import DEFAULT_PKL, load_training_df, sample_groups
from .score import score_output

# 채점 대상 루브릭 — 라벨 추종이면 "준 라벨"의 점수만 높게 나온다(이미지와 무관하게).
SCORE_AGAINST = ("Center", "Edge-Ring")
GROUP_SIZE = 12
PASS_DIE, FAIL_DIE = 1, 2

# (case, 프롬프트에 줄 라벨(None=라벨 없음), 이미지 종류)
CASES = [
    ("A_label_center__img_center", "Center", "center"),
    ("B_label_center__img_blank", "Center", "blank"),
    ("C_label_center__img_edgering", "Center", "edgering"),
    ("D_label_edgering__img_center", "Edge-Ring", "center"),
    ("E_no_label__img_center", None, "center"),
    ("F_no_label__img_edgering", None, "edgering"),
    ("G_no_label__img_blank", None, "blank"),
]


def _blank_like(maps: list[np.ndarray]) -> list[np.ndarray]:
    """같은 다이 레이아웃에 결함만 0으로 만든 웨이퍼 — '아무 일도 없는 웨이퍼'.

    합성이 아니라 실제 맵의 fail die만 pass로 바꾼 것이라, 다이 배치·웨이퍼 윤곽은 진짜다.
    """
    out = []
    for m in maps:
        blank = np.asarray(m).copy()
        blank[blank == FAIL_DIE] = PASS_DIE
        out.append(blank)
    return out


def build_maps(pkl: str) -> dict[str, list[np.ndarray]]:
    """이미지 3종(center / edgering / blank)의 원본 die_map을 **평가 풀**에서 뽑는다."""
    df = load_training_df(pkl)
    center = sample_groups(df, "Center", "eval", 1, GROUP_SIZE)[0]["maps"]
    edgering = sample_groups(df, "Edge-Ring", "eval", 1, GROUP_SIZE)[0]["maps"]
    return {"center": center, "edgering": edgering, "blank": _blank_like(center)}


def _scored(parsed: dict, rubrics: dict) -> dict:
    """루브릭 2종 채점을 붙인다 — 라벨 추종이면 '준 라벨' 쪽 점수만 높게 나온다."""
    graded = {p: score_output(parsed, rubrics[p]) for p in SCORE_AGAINST if p in rubrics}
    return {
        **parsed,
        "scores": {p: g["overall"] for p, g in graded.items()},
        "hallucinated": {p: g["hallucinated"] for p, g in graded.items()},
    }


def run_labeled(reader: VLMReader, label: str, maps: list[np.ndarray], rubrics: dict) -> dict:
    """실험1 — **운영 경로 그대로**(describe_group). 라벨과 이미지를 어긋나게 준다.

    운영 경로를 타야 "프롬프트에 라벨이 들어가는가"까지 포함해 측정된다. 수정 후에는 라벨이
    프롬프트에 아예 안 들어가므로 같은 호출이 이미지를 따라가야 한다 — 이게 이 수정의 합격 조건.
    """
    return _scored(reader.describe_group(label, maps), rubrics)


def run_unlabeled(reader: VLMReader, png_b64: str, rubrics: dict, n: int = GROUP_SIZE) -> dict:
    """실험2 — 대조군. 라벨 없이 이미지만 준다(모델이 이미지를 읽을 수 있는지 확인)."""
    messages = build_messages(f"Stacked image of {n} wafers.", png_b64)
    return _scored(_parse_response(reader._backend.generate(messages)), rubrics)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pkl", default=DEFAULT_PKL)
    ap.add_argument("--rubrics", default="wafer_reading/rubric_gen/rubrics")
    ap.add_argument("--out", default="wafer_reading/rubric_gen/outputs")
    ap.add_argument("--tag", default="", help="산출 파일명 접미사 (예: before/after)")
    ap.add_argument("--track", default=None, help="VLM 트랙 open|pty (기본: VLM_TRACK env)")
    args = ap.parse_args()

    rubrics = load_fixed_rubrics(Path(args.rubrics), list(SCORE_AGAINST))
    maps = build_maps(args.pkl)
    reader = VLMReader(track=args.track)
    print(f"track={reader.track} open_mode={reader.open_mode}")

    records = []
    for case, label, image_kind in CASES:
        rec = {"case": case, "label": label, "image_kind": image_kind}
        if label is None:  # 실험2 — 대조군(라벨 없이 이미지만)
            png = stack_wafer_maps(maps[image_kind]).to_png_base64()
            rec.update(run_unlabeled(reader, png, rubrics))
        else:  # 실험1 — 운영 경로 그대로
            rec.update(run_labeled(reader, label, maps[image_kind], rubrics))
        records.append(rec)
        s = rec["scores"]
        print(
            f"  {case:34s} label={str(label):10s} image={image_kind:9s} "
            f"Center={s.get('Center')} Edge-Ring={s.get('Edge-Ring')}"
        )
        print(f"      → {rec['total_description'][:110]}")

    suffix = f"_{args.tag}" if args.tag else ""
    out = Path(args.out) / f"ablation_image_dependence{suffix}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8"
    )
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
