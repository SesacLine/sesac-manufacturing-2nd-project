"""인스턴스 루브릭 N건 → 패턴 고정 루브릭 1건 병합

- 여러 건에서 반복 등장하는 키워드만 must-hit으로 병합

- **① must-hit ∩ must-avoid 충돌**(Scratch "continuous", Center "granular", Edge-Ring "sharp"):
  같은 구가 양쪽에 있으면 **must-avoid에서 뺀다**. must-hit은 실제 관측 서술에서 반복 등장한
  실증 근거이고 avoid는 LLM이 추정한 목록이라, 충돌 시 실측을 남기는 쪽이 오탐이 적다.
  뺀 내역은 `dropped.conflict_resolved`에 남겨 추적 가능하게 한다.
- **③ 인스턴스 특이 must-hit**("lower-right quadrant" vs "lower-left quadrant"):
  support 게이트(기본 표본 과반)로 거른다. 추가로 clock_position/coordinates_hint 축은
  표본마다 값이 달라 고정 루브릭에 들어가면 안 되므로, support를 넘겨도 must-hit에서 제외하고
  `dropped.instance_specific`에 보관한다(참고용 — 채점에는 안 쓴다).

CLI:
    python -m wafer_reading.rubric_gen.merge --raw-dir wafer_reading/rubric_gen/rubrics/raw
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .schema import (
    DIMENSIONS,
    INSTANCE_SPECIFIC_KEYS,
    PATTERNS,
    RUBRIC_SCHEMA_VERSION,
    empty_fixed_rubric,
    split_phrases,
    validate_instance_rubric,
)

RUBRICS_DIR = Path(__file__).parent / "rubrics"
DEFAULT_SUPPORT_RATIO = 0.6  # 표본 5건 기준 3건 이상에서 나온 구만 고정 루브릭에 편입


def _collect(instances: list[dict], dimension: str) -> tuple[dict, dict, dict]:
    """축별 구 → (support 카운트, 구별 출처 축, avoid support 카운트)."""
    spec = DIMENSIONS[dimension]
    hit_support: Counter[str] = Counter()
    hit_axis: dict[str, set[str]] = defaultdict(set)
    avoid_support: Counter[str] = Counter()

    for inst in instances:
        block = inst[spec["block"]]
        seen: set[str] = set()  # 한 표본이 같은 구를 여러 축에 써도 support는 1
        for key in spec["hit_keys"]:
            for phrase in split_phrases(block.get(key)):
                hit_axis[phrase].add(key)
                seen.add(phrase)
        hit_support.update(seen)
        avoid_support.update(set(split_phrases(block.get(spec["avoid_key"]))))
    return hit_support, hit_axis, avoid_support


def merge_rubrics(
    instances: list[dict],
    pattern: str,
    min_support: int | None = None,
) -> dict:
    """인스턴스 루브릭 리스트 → 고정 루브릭 dict."""
    if not instances:
        raise ValueError("instances is empty - at least one instance rubric is required")
    for inst in instances:
        validate_instance_rubric(inst)

    n = len(instances)
    threshold = min_support if min_support is not None else max(2, round(DEFAULT_SUPPORT_RATIO * n))
    fixed = empty_fixed_rubric(pattern)
    fixed["n_samples"] = n
    fixed["min_support"] = threshold

    for dimension in DIMENSIONS:
        hit_support, hit_axis, avoid_support = _collect(instances, dimension)

        kept_hits: list[dict] = []
        for phrase, support in hit_support.most_common():
            axes = sorted(hit_axis[phrase])
            entry = {"phrase": phrase, "support": support, "axes": axes}
            if support < threshold:
                fixed["dropped"]["low_support"].append({**entry, "dimension": dimension})
            elif all(a in INSTANCE_SPECIFIC_KEYS for a in axes):
                fixed["dropped"]["instance_specific"].append({**entry, "dimension": dimension})
            else:
                kept_hits.append(entry)

        kept_hit_phrases = {e["phrase"] for e in kept_hits}
        kept_avoids: list[dict] = []
        for phrase, support in avoid_support.most_common():
            entry = {"phrase": phrase, "support": support}
            if support < threshold:
                fixed["dropped"]["low_support"].append(
                    {**entry, "dimension": dimension, "kind": "must_avoid"}
                )
            elif phrase in kept_hit_phrases:  # ① 충돌 — avoid에서 제거
                fixed["dropped"]["conflict_resolved"].append({**entry, "dimension": dimension})
            else:
                kept_avoids.append(entry)

        fixed["dimensions"][dimension] = {"must_hit": kept_hits, "must_avoid": kept_avoids}

    fixed["meta"] = {
        "schema_version": RUBRIC_SCHEMA_VERSION,
        "support_ratio": round(threshold / n, 3),
        # must-hit이 하나도 안 남은 축 — 그 축은 채점 불가(score.py가 n/a로 낸다).
        # 표본 어휘가 수렴하지 않았다는 신호이므로 표본 증량이나 min_support 하향을 검토할 것.
        "unscorable_dimensions": [k for k, v in fixed["dimensions"].items() if not v["must_hit"]],
        "source_defect_types": sorted({str(i.get("defect_types")) for i in instances}),
        "summaries": [i.get("summary", "") for i in instances],
    }
    return fixed


def load_instances(raw_dir: Path, pattern: str) -> list[dict]:
    """rubrics/raw/{pattern}_*.json 로드 (파일명 정렬 = 표본 순서)."""
    slug = pattern.lower().replace("-", "")
    files = sorted(raw_dir.glob(f"{slug}_*.json"))
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def main() -> None:
    ap = argparse.ArgumentParser(description="인스턴스 루브릭 → 패턴 고정 루브릭 병합")
    ap.add_argument("--raw-dir", default=str(RUBRICS_DIR / "raw"))
    ap.add_argument("--out-dir", default=str(RUBRICS_DIR))
    ap.add_argument("--patterns", nargs="*", default=list(PATTERNS))
    ap.add_argument("--min-support", type=int, default=None, help="기본: 표본의 60%% (최소 2)")
    args = ap.parse_args()

    raw_dir, out_dir = Path(args.raw_dir), Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for pattern in args.patterns:
        instances = load_instances(raw_dir, pattern)
        if not instances:
            print(f"[skip] {pattern}: no instance rubric in {raw_dir}")
            continue
        fixed = merge_rubrics(instances, pattern, args.min_support)
        path = out_dir / f"{pattern}.json"
        path.write_text(json.dumps(fixed, ensure_ascii=False, indent=2), encoding="utf-8")
        n_hit = sum(len(d["must_hit"]) for d in fixed["dimensions"].values())
        n_avoid = sum(len(d["must_avoid"]) for d in fixed["dimensions"].values())
        print(
            f"[ok] {path} (samples={fixed['n_samples']} min_support={fixed['min_support']} "
            f"must_hit={n_hit} must_avoid={n_avoid} "
            f"conflict_resolved={len(fixed['dropped']['conflict_resolved'])})"
        )
        if fixed["meta"]["unscorable_dimensions"]:
            print(
                f"     ⚠️ must-hit 0개 축 {fixed['meta']['unscorable_dimensions']} — 채점 불가(n/a)로 나간다. "
                f"표본 증량 또는 --min-support 하향 검토"
            )


if __name__ == "__main__":
    main()
