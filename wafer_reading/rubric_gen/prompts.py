"""루브릭 생성·판정 프롬프트 (평가 전용 — 런타임 판독 경로에서는 쓰지 않는다)

- 판정 프롬프트: 듀얼 평가 ① 루브릭 없는 LLM-as-Judge ② 루브릭을 채점 기준으로 명시.
  둘 다 temperature 0 · JSON 강제로 호출(judge.py).
"""

from __future__ import annotations

# ---------------------------------------------------------------- 라벨 없는 서술(루브릭 표본용)

# 발견문제 #18: 쿼리에 CNN 라벨을 주면 VLM이 **이미지가 아니라 라벨을 따라** 서술한다
# (결함 0인 웨이퍼에 Center 라벨 → 없는 결함을 상세 서술). 그 서술로 만든 루브릭은
# "패턴이 어떻게 생겼나"가 아니라 "라벨을 들었을 때 모델이 뭐라고 쓰나"를 정답으로 굳힌다.
# → **루브릭 표본은 라벨 없이** 뽑는다(실측 E·F·G에서 라벨을 빼면 이미지를 정확히 읽음).
# 런타임 판독 프롬프트(`vlm/prompts.py`)는 계약이라 건드리지 않는다 — 여기는 평가 전용 사본.

UNLABELED_SYSTEM_PROMPT = """\
You are a semiconductor wafer defect analysis expert. Analyze the provided
wafer map image and describe:

1. Spatial Distribution: Where are the defects located? (center, edge,
   specific regions, clock positions)
2. Morphology: What do the defects look like? (patterns, shapes, density,
   texture)

Provide a concise technical description focusing only on spatial and
morphological characteristics. Do not include root cause analysis.
Describe strictly what is visible in the image. If the wafer shows no defect
pattern, say so explicitly instead of inventing one.

Respond with ONLY a valid JSON object:
{
  "pattern_candidate": "<the defect pattern you infer from the image: Center | Edge-Ring | Scratch | Unknown | Normal>",
  "location_text": "<answer to 1, 2-3 sentences>",
  "morphology_text": "<answer to 2, 2-3 sentences>",
  "total_description": "<1-2 sentence summary combining both>"
}
"""

UNLABELED_STACKED_QUERY = "Stacked wafer map image of {n} wafers."
UNLABELED_SINGLE_QUERY = "Single wafer map image."

# ---------------------------------------------------------------- 루브릭 변환(생성)

CONVERSION_SYSTEM_PROMPT = """\
You are a semiconductor wafer defect analysis expert. Your task is to
convert the provided wafer map analysis into a structured evaluation rubric.

The rubric should capture:
1. Spatial Distribution: Exact zones, clock positions, coordinates mentioned
2. Morphology: Pattern types, density descriptions, geometric structures

For each dimension, provide:
- Must-hit keywords: Terms that MUST appear in a correct answer
- Must-avoid keywords: Terms that indicate hallucination if present

Respond with ONLY a valid JSON object:
{
  "defect_types": "defect type present",
  "spatial_rubric": {
    "zone": "affected zones description",
    "distribution": "distribution pattern description",
    "clock_position": "clock positions mentioned",
    "coordinates_hint": "coordinate references",
    "spatial_avoid": ["terms that should NOT appear"]
  },
  "morphology_rubric": {
    "pattern_type": "pattern descriptions",
    "density": "density descriptions",
    "geometric_structure": "geometric terms",
    "texture_description": "texture terms",
    "morphology_avoid": ["terms that should NOT appear"]
  },
  "summary": "brief description of overall defect pattern"
}
"""

CONVERSION_QUERY_TEMPLATE = """\
Defect pattern: {pattern}

Wafer map analysis to convert:
- Spatial distribution: {location_text}
- Morphology: {morphology_text}
- Summary: {total_description}
"""

# ---------------------------------------------------------------- LLM-as-Judge

JUDGE_SYSTEM_PROMPT = """\
You are evaluating a wafer map defect description produced by a vision-language model.
Score the description on three axes, each an integer from 1 to 5:

- spatial: is the described defect location (zone, radial trend, clock position) accurate
  and specific for the given defect pattern?
- morphology: is the described shape, density, continuity and texture accurate
  and specific for the given defect pattern?
- faithfulness: is the description free of claims that are not supported by the
  defect pattern (hallucinated locations, shapes, or root-cause speculation)?
  5 = no unsupported claim, 1 = mostly unsupported.

Respond with ONLY a valid JSON object:
{
  "spatial": <1-5>,
  "morphology": <1-5>,
  "faithfulness": <1-5>,
  "rationale": "<one or two sentences>"
}
"""

JUDGE_QUERY_TEMPLATE = """\
Defect pattern (CNN label): {pattern}

Description under evaluation:
- Spatial distribution: {location_text}
- Morphology: {morphology_text}
- Summary: {total_description}
"""

# 루브릭 유도 판정(②) — 고정 루브릭을 채점 기준으로 프롬프트에 명시한다.
JUDGE_RUBRIC_BLOCK = """\

Use the following fixed rubric for pattern "{pattern}" as the grading criteria.
Terms are phrases, compare by meaning (paraphrase counts as a hit).

Spatial — must appear: {spatial_hit}
Spatial — must NOT appear: {spatial_avoid}
Morphology — must appear: {morphology_hit}
Morphology — must NOT appear: {morphology_avoid}
"""
