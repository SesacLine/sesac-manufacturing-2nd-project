"""루브릭 스키마 — 인스턴스 루브릭(LLM 산출) / 고정 루브릭(패턴별 병합본)

설계 정본: `sdoubleoj/0723 work/wafermap_detection_design_v2.0.md` §6 (WaferSAGE 형식).
- `defect_types`는 **단일 값 문자열**(= pattern_candidate). 원 논문의 리스트와 의도적으로 다름 —
  우리는 CNN 단일 분류 후 그룹화라 구조적으로 패턴이 하나다.
- `root_cause_rubric`은 제외(원인 추론은 KG 몫 — 판독은 공간/형태 2축만).

용어:
- **인스턴스 루브릭**: VLM output 1건을 LLM이 루브릭으로 변환한 것(표본, 재현 불가 어휘 포함).
- **고정 루브릭**: 패턴당 표본 N건을 병합해 만든 평가 기준(merge.py). 채점은 이것만 사용.
"""

from __future__ import annotations

import re

PATTERNS = ("Center", "Edge-Ring", "Scratch")

# 인스턴스 루브릭 축(=LLM이 채우는 키). avoid 키는 dimension별로 이름이 다르다(WaferSAGE 원형 유지).
SPATIAL_KEYS = ("zone", "distribution", "clock_position", "coordinates_hint")
MORPHOLOGY_KEYS = ("pattern_type", "density", "geometric_structure", "texture_description")
DIMENSIONS = {
    "spatial": {"block": "spatial_rubric", "hit_keys": SPATIAL_KEYS, "avoid_key": "spatial_avoid"},
    "morphology": {
        "block": "morphology_rubric",
        "hit_keys": MORPHOLOGY_KEYS,
        "avoid_key": "morphology_avoid",
    },
}

# 인스턴스 특이 축(검수 발견 ③) — 표본마다 값이 달라 고정 루브릭 must-hit에 넣으면 오탐이 된다.
# support 게이트로도 대부분 걸러지지만, 축 자체를 명시해 두고 merge에서 별도 취급한다.
INSTANCE_SPECIFIC_KEYS = ("clock_position", "coordinates_hint")

RUBRIC_SCHEMA_VERSION = "wafer-rubric-v1"


class RubricSchemaError(ValueError):
    """인스턴스 루브릭이 스키마 계약을 어길 경우"""


def normalize_text(text: str) -> str:
    """채점용 정규화 — **길이 보존**(오프셋이 원문과 1:1로 유지돼야 span 마스킹이 가능).

    소문자화 + 영숫자 외 문자를 공백으로 치환. 하이픈이 공백이 되므로
    "high-density"와 "high density"가 같은 구로 매칭된다.
    """
    return re.sub(r"[^a-z0-9]", " ", text.lower())


def normalize_phrase(phrase: str) -> str:
    """구(phrase) 정규화 — 토큰 단위로 잘라 공백 1개로 재조립(길이 보존 안 함)."""
    return " ".join(normalize_text(str(phrase)).split())


# LLM 자유서술 정리용 — 변환 모델이 축 값을 어떤 형식으로 주든 "구 목록"만 남긴다.
# 실측(gpt-5.5): "Must-hit keywords: central region, middle, center of wafer. A correct answer
# should state that defects are concentrated in the central zone." → 접두사 + 목록 + 산문 꼬리.
_META_PREFIX = re.compile(r"^\s*(?:must[-\s]?(?:hit|avoid)\s*)?(?:keywords?|terms?)\s*[:\-]\s*", re.I)
_FILLERS = {"none", "none specified", "not applicable", "not specified", "unknown", "n a", "na"}
_NEGATION_STARTS = {"no", "not", "without", "non", "neither", "nor", "never"}
# 문장 조각 판별 — 루브릭 키워드는 명사구다("dense central cluster"), 절이 아니다("the field is compact").
_CLAUSE_STARTS = {"the", "a", "an", "it", "this", "that", "there", "they"}
_CLAUSE_VERBS = {"is", "are", "was", "were", "be", "should", "must", "shows", "show", "appears", "appear", "has", "have"}
MAX_PHRASE_TOKENS = 6  # 루브릭 키워드는 구다 — 문장은 기준으로 쓰지 않는다


def split_phrases(value) -> list[str]:
    """LLM이 준 축 값을 구 리스트로 분해.

    LLM은 축을 문자열("Center, Edge, Mid-radius")로도, 리스트로도, 산문 섞인 형식으로도 준다.
    ① 메타 접두사("Must-hit keywords:") 제거 ② 첫 문장 이후 산문 꼬리 절단
    ③ 쉼표/세미콜론/슬래시/and로 분해 ④ 채움말·부정으로 시작하는 구·문장 길이 초과분 제외.
    빈 구·중복은 제거(입력 순서 유지).
    """
    items = value if isinstance(value, list) else [value]
    out: list[str] = []
    for item in items:
        if item is None:
            continue
        text = _META_PREFIX.sub("", str(item))
        text = re.split(r"\.\s|\.$", text)[0]  # 키워드 목록 뒤에 붙는 설명 문장 절단
        for part in re.split(r"[,;/]|\band\b", text):
            norm = normalize_phrase(part)
            if not norm or norm in _FILLERS or norm in out:
                continue
            tokens = norm.split()
            if len(tokens) > MAX_PHRASE_TOKENS or tokens[0] in _NEGATION_STARTS:
                continue  # 문장형 값과 부정형 요구("no dominant ring")는 기준이 될 수 없다
            if tokens[0] in _CLAUSE_STARTS or any(v in _CLAUSE_VERBS for v in tokens):
                continue  # 절 조각("the field is compact")도 키워드가 아니다
            out.append(norm)
    return out


def validate_instance_rubric(obj: dict) -> dict:
    """LLM 산출 인스턴스 루브릭의 스키마 검사 — 통과 시 그대로 반환.

    검사 범위는 "스키마 준수 여부"뿐이다(내용 품질 판단 아님). VLM 어댑터의
    `_parse_response`와 같은 철학: 계약 위반만 잡고 의미는 뒤 단계가 본다.
    """
    if not isinstance(obj, dict):
        raise RubricSchemaError(f"rubric must be an object: {type(obj).__name__}")

    defect = obj.get("defect_types")
    if not isinstance(defect, str) or not defect.strip():
        raise RubricSchemaError(f"defect_types must be a non-empty string: {defect!r}")

    for dim in DIMENSIONS.values():
        block = obj.get(dim["block"])
        if not isinstance(block, dict):
            raise RubricSchemaError(f"{dim['block']} block missing/type error")
        missing = [k for k in dim["hit_keys"] if k not in block]
        if missing:
            raise RubricSchemaError(f"{dim['block']} key missing: {missing}")
        avoid = block.get(dim["avoid_key"])
        if not isinstance(avoid, list):
            raise RubricSchemaError(f"{dim['avoid_key']} must be a list: {type(avoid).__name__}")

    if not isinstance(obj.get("summary"), str):
        raise RubricSchemaError("summary must be a string")
    return obj


def empty_fixed_rubric(pattern: str) -> dict:
    """고정 루브릭 골격 — merge.py가 채운다."""
    return {
        "schema_version": RUBRIC_SCHEMA_VERSION,
        "pattern": pattern,
        "n_samples": 0,
        "min_support": 0,
        "dimensions": {
            name: {"must_hit": [], "must_avoid": []} for name in DIMENSIONS
        },
        "dropped": {"low_support": [], "conflict_resolved": [], "instance_specific": []},
        "meta": {},
    }


def phrases_of(fixed_rubric: dict, dimension: str, kind: str) -> list[str]:
    """고정 루브릭에서 구 문자열만 뽑는다(kind: must_hit | must_avoid)."""
    entries = fixed_rubric.get("dimensions", {}).get(dimension, {}).get(kind, [])
    return [e["phrase"] if isinstance(e, dict) else str(e) for e in entries]
