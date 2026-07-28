"""루브릭 생성 (dev 전용): VLM output → LLM 변환 → 인스턴스 루브릭

- 루브릭은 LLM이 VLM output에서 생성한다.
- 생성 LLM은 pty 트랙 모델을 재사용한다.
- 표본 = 패턴당 VLM output 5건(Training split held-out — sampling.py의 rubric 풀).

파이프라인:
    WM-811K Training(rubric 풀) → 그룹 스태킹 → VLMReader.describe_group → 변환 LLM
    → 인스턴스 루브릭 rubrics/raw/{pattern}_{i}.json (+ VLM output은 outputs/*.jsonl 로 캐시)

CLI:
    python -m wafer_reading.rubric_gen.generate --patterns Center Edge-Ring Scratch --samples 5
    python -m wafer_reading.rubric_gen.generate --from-outputs .../vlm_outputs.jsonl   # VLM 재호출 없이
"""

from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path

from ..vlm.adapter import VLMReader, _parse_response
from ..vlm.prompts import ASSETS_DIR, FEWSHOT_EXAMPLES
from .models import RUBRIC_GEN_MODEL, assert_distinct
from .prompts import (
    CONVERSION_QUERY_TEMPLATE,
    CONVERSION_SYSTEM_PROMPT,
    UNLABELED_SINGLE_QUERY,
    UNLABELED_STACKED_QUERY,
    UNLABELED_SYSTEM_PROMPT,
)
from .sampling import DEFAULT_PKL, load_training_df, sample_groups
from .schema import PATTERNS, RubricSchemaError, validate_instance_rubric

RUBRICS_DIR = Path(__file__).parent / "rubrics"
OUTPUTS_DIR = Path(__file__).parent / "outputs"
MAX_RETRIES = 2  # 최초 1회 + 재시도 2회 (VLM 어댑터와 동일 정책)

DEFAULT_GROUP_SIZE = {"Center": 12, "Edge-Ring": 9, "Scratch": 5}


class RubricGenError(RuntimeError):
    """재시도 소진 후에도 스키마를 지키는 루브릭을 얻지 못한 경우"""


def text_messages(system: str, user: str) -> list[dict]:
    """트랙 중립 텍스트 메시지(이미지 없음) — 백엔드가 자기 포맷으로 변환한다."""
    return [
        {"role": "system", "content": [{"type": "text", "text": system}]},
        {"role": "user", "content": [{"type": "text", "text": user}]},
    ]


def parse_rubric(text: str) -> dict:
    """LLM 텍스트 → 인스턴스 루브릭 dict (코드펜스 허용, 스키마 검사)."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise RubricSchemaError(f"JSON object not found: {text[:200]!r}")
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise RubricSchemaError(f"JSON parsing failed: {e}") from e
    return validate_instance_rubric(obj)


class RubricGenerator:
    """VLM output 1건 → 인스턴스 루브릭 1건.

    기본 모델은 `models.RUBRIC_GEN_MODEL` — 서술 VLM과 반드시 다른 모델
    """

    RUBRIC_SEED = 20260726  # 최초 루브릭 생성일

    def __init__(self, backend=None, model: str = RUBRIC_GEN_MODEL, timeout_s: float = 120.0):
        self.model = model
        if backend is not None:  # 테스트용 주입
            self._backend = backend
        else:
            from ..vlm.backends.openai_api import OpenAIBackend

            self._backend = OpenAIBackend(
                model=model, timeout_s=timeout_s, seed=self.RUBRIC_SEED)

    def convert(self, vlm_output: dict) -> dict:
        query = CONVERSION_QUERY_TEMPLATE.format(
            pattern=vlm_output.get("pattern_candidate", ""),
            location_text=vlm_output.get("location_text", ""),
            morphology_text=vlm_output.get("morphology_text", ""),
            total_description=vlm_output.get("total_description", ""),
        )
        messages = text_messages(CONVERSION_SYSTEM_PROMPT, query)
        last_err: Exception | None = None
        for _ in range(1 + MAX_RETRIES):
            try:
                return parse_rubric(self._backend.generate(messages))
            except (RubricSchemaError, TimeoutError, ConnectionError, OSError) as e:
                last_err = e
        raise RubricGenError(f"rubric generation failed({vlm_output.get('pattern_candidate')}): {last_err}") from last_err


def build_unlabeled_messages(query_text: str, query_png_b64: str) -> list[dict]:
    """few-shot 이미지·정답 JSON은 그대로 쓰되 유저 텍스트에서 CNN 라벨을 제거한다.

    예시의 응답 JSON에는 pattern_candidate가 남아 있어 "이미지에서 패턴을 추론하라"를
    가르치는 앵커가 된다(라벨을 주입하는 게 아니라 추론을 시범 보이는 것임).
    """
    messages: list[dict] = [
        {"role": "system", "content": [{"type": "text", "text": UNLABELED_SYSTEM_PROMPT}]}
    ]
    for ex in FEWSHOT_EXAMPLES:
        m = re.search(r"Stacked image of (\d+) wafers", ex["user_text"])
        neutral = UNLABELED_STACKED_QUERY.format(n=m.group(1)) if m else UNLABELED_SINGLE_QUERY
        png = (ASSETS_DIR / ex["asset"]).read_bytes()
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "image_png_base64", "data": base64.b64encode(png).decode("ascii")},
                    {"type": "text", "text": neutral},
                ],
            }
        )
        messages.append(
            {
                "role": "assistant",
                "content": [{"type": "text", "text": json.dumps(ex["response"], ensure_ascii=False)}],
            }
        )
    messages.append(
        {
            "role": "user",
            "content": [
                {"type": "image_png_base64", "data": query_png_b64},
                {"type": "text", "text": query_text},
            ],
        }
    )
    return messages


def describe_unlabeled(reader: VLMReader, pattern: str, maps: list, wafer_keys: list) -> dict:
    """라벨 없이 그룹 이미지를 서술한다 — 이미지 렌더 규칙(Scratch 단일)만 재사용."""
    image_mode, png_b64, n_shown = reader._render_image(pattern, maps, wafer_keys)
    query = (
        UNLABELED_SINGLE_QUERY if image_mode == "single"
        else UNLABELED_STACKED_QUERY.format(n=n_shown)
    )
    parsed = _parse_response(reader._backend.generate(build_unlabeled_messages(query, png_b64)))
    return {**parsed, "vlm_track": reader.track, "n_wafers": len(maps), "image_mode": image_mode}


def _agrees(inferred: str, expected: str) -> bool:
    norm = lambda s: str(s).strip().lower().replace("-", "").replace(" ", "")  # noqa: E731
    return norm(inferred) == norm(expected)


def produce_vlm_outputs(
    patterns: list[str],
    samples: int,
    pkl: str,
    track: str | None,
    group_size: dict | None = None,
    extra_groups: int = 3,
) -> tuple[list[dict], list[dict]]:
    """루브릭 표본용 VLM output 생성(실호출, **라벨 없이**) — rubric 풀에서만 뽑는다.

    모델이 이미지에서 추론한 패턴이 표본의 실제 패턴과 다르면 그 표본은 버림.
    (판독을 틀린 서술로 기준을 만들면 안 된다). 탈락분을 메우려 `extra_groups`만큼 더 뽑는다.
    반환: (채택 output, 탈락 기록)
    """
    sizes = group_size or DEFAULT_GROUP_SIZE
    df = load_training_df(pkl)
    reader = VLMReader(track=track)
    outputs, dropped = [], []
    for pattern in patterns:
        groups = sample_groups(df, pattern, "rubric", samples + extra_groups, sizes.get(pattern, 9))
        kept = 0
        for g in groups:
            if kept >= samples:
                break
            print(f"  [vlm] {g['group_id']} ({len(g['maps'])} wafers, 라벨 미제공) ...")
            out = describe_unlabeled(reader, pattern, g["maps"], g["wafer_keys"])
            record = {**out, "group_id": g["group_id"], "pool": "rubric", "expected_pattern": pattern}
            if not _agrees(out.get("pattern_candidate", ""), pattern):
                print(f"        [drop] 추론={out.get('pattern_candidate')!r} ≠ 실제={pattern}")
                dropped.append(record)
                continue
            # 루브릭 변환·병합은 실제 패턴 기준으로 묶는다(추론값과 일치하므로 값은 같다)
            outputs.append({**record, "pattern_candidate": pattern})
            kept += 1
        if kept < samples:
            print(f"  [warn] {pattern}: 표본 {kept}/{samples}건만 확보(일치 실패) — extra_groups 상향 검토")
    return outputs, dropped


def _slug(pattern: str) -> str:
    return pattern.lower().replace("-", "")


def main() -> None:
    ap = argparse.ArgumentParser(description="VLM output → 인스턴스 루브릭 생성 (dev 전용)")
    ap.add_argument("--pkl", default=DEFAULT_PKL)
    ap.add_argument("--patterns", nargs="*", default=list(PATTERNS))
    ap.add_argument("--samples", type=int, default=5, help="패턴당 VLM output 건수")
    ap.add_argument("--track", default=None, help="VLM 트랙 open|pty (기본: VLM_TRACK env)")
    ap.add_argument("--from-outputs", default=None, help="VLM 재호출 없이 캐시된 jsonl 사용")
    ap.add_argument("--out-dir", default=str(RUBRICS_DIR / "raw"))
    ap.add_argument("--outputs-dir", default=str(OUTPUTS_DIR))
    args = ap.parse_args()

    models = assert_distinct(args.track or "pty", judge_used=False)  # 역할 분리 강제
    print(f"[모델] 서술={models['description_vlm']} / 변환={models['rubric_generator']}")

    if args.from_outputs:
        outputs = [json.loads(line) for line in Path(args.from_outputs).read_text(encoding="utf-8").splitlines() if line.strip()]
        outputs = [o for o in outputs if o.get("pattern_candidate") in args.patterns]
        print(f"[1/2] VLM output {len(outputs)}건 로드 (재호출 없음): {args.from_outputs}")
    else:
        print(f"[1/2] VLM 실호출(라벨 미제공) — {args.patterns} × {args.samples}건")
        outputs, dropped = produce_vlm_outputs(args.patterns, args.samples, args.pkl, args.track)
        outputs_dir = Path(args.outputs_dir)
        outputs_dir.mkdir(parents=True, exist_ok=True)
        path = outputs_dir / "rubric_vlm_outputs.jsonl"
        path.write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in outputs), encoding="utf-8")
        print(f"      캐시 저장: {path} (판독 불일치 탈락 {len(dropped)}건)")
        if dropped:
            (outputs_dir / "rubric_dropped.jsonl").write_text(
                "\n".join(json.dumps(o, ensure_ascii=False) for o in dropped), encoding="utf-8"
            )

    print(f"[2/2] 루브릭 변환 LLM {len(outputs)}콜 — {models['rubric_generator']}")
    generator = RubricGenerator()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    counters: dict[str, int] = {}
    for out in outputs:
        pattern = out.get("pattern_candidate", "")
        i = counters.get(pattern, 0)
        counters[pattern] = i + 1
        rubric = generator.convert(out)
        path = out_dir / f"{_slug(pattern)}_{i:02d}.json"
        path.write_text(json.dumps(rubric, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [ok] {path}")

    print("다음 단계: python -m wafer_reading.rubric_gen.merge")


if __name__ == "__main__":
    main()
