"""VLM 프롬프트 — 시스템 프롬프트 / few-shot 예시 / 쿼리 템플릿 (open/pty 공용)

    - 예시 텍스트: "웨이퍼맵 결함 판독 관련_v0.1" 문서 확인
    - 예시 이미지: gen_assets.py가 WM-811K Training split에서 합성해 assets/에 저장
    - Scratch: 스태킹 없이 단일 웨이퍼 이미지를 씀
"""

from __future__ import annotations

from pathlib import Path

ASSETS_DIR = Path(__file__).parent / "assets"

# DENSITY_ENUM = {"high", "medium", "low", "unknown"}
# CONTINUITY_ENUM = {"continuous", "intermittent", "discontinuous", "not_applicable", "unknown"}

SYSTEM_PROMPT = """\
You are a semiconductor wafer defect analysis expert. Analyze the provided
wafer map image and describe:

1. Spatial Distribution: Where are the defects located? (center, edge,
   specific regions, clock positions)
2. Morphology: What do the defects look like? (patterns, shapes, density,
   texture)

Describe ONLY what is actually visible in this image. If the image shows no
defect concentration — a clean or uniform wafer — say so plainly instead of
describing a pattern that is not there.

Provide a concise technical description focusing only on spatial and
morphological characteristics. Do not include root cause analysis.

Respond with ONLY a valid JSON object:
{
  "pattern_candidate": "<the pattern you observe: Center | Edge-Ring | Scratch | Normal | Unknown>",
  "location_text": "<answer to 1, 2-3 sentences>",
  "morphology_text": "<answer to 2, 2-3 sentences>",
  "total_description": "<1-2 sentence summary combining both>"
}
"""

# ⚠️ 쿼리에 CNN 라벨을 넣지 말 것 (발견문제 #18, 이슈 #100).
# 라벨을 주면 모델이 이미지 대신 라벨을 따라 서술한다 — 결함이 0인 웨이퍼에 "Center 라벨"을
# 주자 밀도·반경 감쇠·대칭성까지 지어냈고(순수 환각), 라벨과 이미지가 상반될 때도 라벨을
# 따랐다(실측). 라벨을 빼면 같은 모델이 이미지를 정확히 읽는다.
# 서술은 KG 의미 진입의 메인 쿼리이기도 해서(live_kg_client), 환각이 원인 후보까지 오염시킨다.
STACKED_QUERY_TEXT = "Stacked image of {n} wafers."
SINGLE_QUERY_TEXT = "Single wafer map image."

# few-shot 예시 3턴 — asset 파일명 / 유저 텍스트 / 정답 JSON의 고정 쌍
# user_text에 라벨이 없어야 함 — 예시가 가르치는 건 '라벨→서술'이 아니라 '이미지→서술'이다.
# response의 pattern_candidate는 그 예시 이미지에서 읽히는 값이다.
# 이미지-JSON은 쌍으로 고정: gen_assets.py 시드를 바꿔 이미지를 재생성하면 서술 재검토 필수
FEWSHOT_EXAMPLES = [
    {
        "asset": "center_stack12.png",
        "user_text": STACKED_QUERY_TEXT.format(n=12),
        "response": {
            "pattern_candidate": "Center",
            "location_text": "The defect distribution shows a clear radial dependency, with the highest density at the center and a sharp decrease moving outward. It is localized and not random across the wafer.",
            "morphology_text": "The defect appears as a solid, high-saturation amorphous blob without a specific geometric shape or orientation. It is a dense point-cloud that has coalesced into a singular macro-defect.",
            "total_description": "A localized, high-density amorphous blob of failing dies concentrated at the wafer center, with density decreasing sharply outward."
        },
    },
    {
        "asset": "edgering_stack9.png",
        "user_text": STACKED_QUERY_TEXT.format(n=9),
        "response": {
            "pattern_candidate": "Edge-Ring",
            "location_text": "The defect shows a circumferential concentration, meaning it forms a continuous ring. It is relatively uniform across all clock positions (0° to 360°), though there is some localized intensification near the notch area at 6 o'clock.",
            "morphology_text": "The pattern is a high-density, continuous band that appears saturated at the edge, creating a sharp contrast against the clean interior. The transition from the healthy area to the defective edge is abrupt, not gradual.",
            "total_description": "A continuous, high-density circumferential band of failing dies along the wafer periphery, sharply contrasted against a clean interior."
        },
    },
    {
        # Scratch는 단일 이미지 분기(07-23 확정) — 예시도 단일 웨이퍼 이미지로 정합시킨다.
        "asset": "scratch_single.png",
        "user_text": SINGLE_QUERY_TEXT,
        "response": {
            "pattern_candidate": "Scratch",
            "location_text": "The defect distribution is spatially correlated across multiple adjacent die fields along a linear trajectory.",
            "morphology_text": "The defect pattern is a continuous, high-density filamentary string of failing dies with a jagged, micro-linear morphology.",
            "total_description": "A continuous filamentary string of failing dies tracing a jagged linear trajectory across adjacent die fields."
        },
    },
]

RESPONSE_FIELDS = (
    "pattern_candidate",
    "location_text",
    "morphology_text",
    "total_description"
)
