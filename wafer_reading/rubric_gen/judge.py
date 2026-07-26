"""LLM-as-Judge — 듀얼 평가의 판정자

두 모드를 모두 지원한다:
- `plain`  : ① VLM output 텍스트만 보고 판정(루브릭 없음)
- `rubric` : ② 고정 루브릭을 채점 기준으로 프롬프트에 명시하고 판정

축 3종(1~5 정수): spatial / morphology / faithfulness(환각 없음). temperature 0 · JSON 강제.
결정적 지표(score.py)와 **병행** 보고한다 — 판정자 편향 때문에 단독 근거로 쓰지 않는다[Zheng2023].
"""

from __future__ import annotations

import json
import re

from .generate import text_messages
from .models import JUDGE_MODEL
from .prompts import JUDGE_QUERY_TEMPLATE, JUDGE_RUBRIC_BLOCK, JUDGE_SYSTEM_PROMPT
from .schema import phrases_of

AXES = ("spatial", "morphology", "faithfulness")
MAX_RETRIES = 2
JUDGE_MODES = ("plain", "rubric")


class JudgeParseError(ValueError):
    """판정 응답이 JSON 계약을 어길 경우"""


class JudgeCallError(RuntimeError):
    """재시도 소진 후에도 유효한 판정을 얻지 못한 경우"""


def parse_judgement(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise JudgeParseError(f"JSON object not found: {text[:200]!r}")
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise JudgeParseError(f"JSON parsing failed: {e}") from e

    scores = {}
    for axis in AXES:
        value = obj.get(axis)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise JudgeParseError(f"{axis} must be a number: {value!r}")
        if not 1 <= value <= 5:
            raise JudgeParseError(f"{axis} out of range 1-5: {value}")
        scores[axis] = int(round(value))
    scores["rationale"] = str(obj.get("rationale", ""))
    return scores


def build_judge_prompt(vlm_output: dict, fixed_rubric: dict | None, mode: str) -> tuple[str, str]:
    if mode not in JUDGE_MODES:
        raise ValueError(f"unknown judge mode: {mode!r} ({'|'.join(JUDGE_MODES)})")
    system = JUDGE_SYSTEM_PROMPT
    if mode == "rubric":
        if fixed_rubric is None:
            raise ValueError("rubric mode requires a fixed rubric")
        system += JUDGE_RUBRIC_BLOCK.format(
            pattern=fixed_rubric.get("pattern", ""),
            spatial_hit=", ".join(phrases_of(fixed_rubric, "spatial", "must_hit")) or "(none)",
            spatial_avoid=", ".join(phrases_of(fixed_rubric, "spatial", "must_avoid")) or "(none)",
            morphology_hit=", ".join(phrases_of(fixed_rubric, "morphology", "must_hit")) or "(none)",
            morphology_avoid=", ".join(phrases_of(fixed_rubric, "morphology", "must_avoid")) or "(none)",
        )
    query = JUDGE_QUERY_TEMPLATE.format(
        pattern=vlm_output.get("pattern_candidate", ""),
        location_text=vlm_output.get("location_text", ""),
        morphology_text=vlm_output.get("morphology_text", ""),
        total_description=vlm_output.get("total_description", ""),
    )
    return system, query


class LLMJudge:
    """기본 모델은 `models.JUDGE_MODEL` — **서술 VLM·루브릭 생성 모델과 모두 다른 모델**.

    같은 모델이 자기 출력을 채점하면 self-preference bias가 생긴다[Zheng2023].
    """

    def __init__(self, backend=None, model: str = JUDGE_MODEL, timeout_s: float = 120.0):
        self.model = model
        if backend is not None:  # 테스트용 주입
            self._backend = backend
        else:
            from ..vlm.backends.openai_api import OpenAIBackend

            self._backend = OpenAIBackend(model=model, timeout_s=timeout_s)

    def judge(self, vlm_output: dict, fixed_rubric: dict | None = None, mode: str = "rubric") -> dict:
        system, query = build_judge_prompt(vlm_output, fixed_rubric, mode)
        messages = text_messages(system, query)
        last_err: Exception | None = None
        for _ in range(1 + MAX_RETRIES):
            try:
                result = parse_judgement(self._backend.generate(messages))
                result["judge_mode"] = mode
                result["judge_mean"] = round(sum(result[a] for a in AXES) / len(AXES), 4)
                return result
            except (JudgeParseError, TimeoutError, ConnectionError, OSError) as e:
                last_err = e
        raise JudgeCallError(f"judge failed(mode={mode}): {last_err}") from last_err
