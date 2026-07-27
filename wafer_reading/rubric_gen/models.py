"""역할별 모델 배정 — **서술 / 루브릭 변환 / 판정은 서로 다른 모델이어야 한다**

- 평가 대상 VLM이 루브릭까지 만들면 **자기 어휘가 정답**이 된다(실측: 라벨 없이 정확히 읽은
  서술이 오히려 낮은 점수).
- 판정자가 평가 대상과 같으면 self-preference bias가 겹친다[Zheng2023].
- WaferSAGE도 teacher(Gemini) / 루브릭 변환(DeepSeek) / 판정(GPT-5-mini)을 분리한다.

**제약**: 변환·판정은 OpenAI API만 쓴다(자체 결정 — 추가 벤더 키 없음). 대신 **세대를 갈라**
독립성을 확보한다: 서술 5.4-mini / 변환 5.5 / 판정 5.2.

전부 env로 오버라이드 가능하되, 셋 중 둘이 같아지면 `ModelSeparationError`로 즉시 실패한다
(조용히 같은 모델로 도는 것이 가장 위험 — 편향이 수치에 섞인 채로 남음).
"""

from __future__ import annotations

import os
import re

# 서술(평가 대상)은 판독 런타임 계약이라 여기서 바꾸지 않는다 — 값만 읽어 분리 검사에 쓴다.
from ..vlm.backends.openai_api import MODEL as VLM_PTY_MODEL

RUBRIC_GEN_MODEL = os.environ.get("RUBRIC_GEN_MODEL", "gpt-5.5-2026-04-23")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "gpt-5.2-2025-12-11")

QWEN_LOCAL_MODEL = "Qwen/Qwen3-VL-4B-Instruct"  # open 트랙 서술 모델(로컬)

_DATE_SUFFIX = re.compile(r"-\d{4}-\d{2}-\d{2}$")


class ModelSeparationError(RuntimeError):
    """세 역할 중 둘 이상이 같은 모델일 경우"""


def base_model(model_id: str) -> str:
    """날짜 핀만 다른 같은 모델은 **같은 모델**로 본다(gpt-5.5 == gpt-5.5-2026-04-23)."""
    return _DATE_SUFFIX.sub("", str(model_id).strip().lower())


def vlm_model(track: str) -> str:
    return QWEN_LOCAL_MODEL if track == "open" else VLM_PTY_MODEL


def role_models(track: str = "pty") -> dict[str, str]:
    """리포트 meta에 기록할 역할별 모델(추적성 — 어떤 조합으로 낸 수치인지 남는다)."""
    return {
        "description_vlm": vlm_model(track),
        "rubric_generator": RUBRIC_GEN_MODEL,
        "judge": JUDGE_MODEL,
    }


def assert_distinct(track: str = "pty", *, judge_used: bool = True) -> dict[str, str]:
    """3역할 모델이 서로 다른지 검사하고 배정을 돌려준다. 파이프라인 진입점에서 부를 것."""
    models = role_models(track)
    roles = list(models) if judge_used else ["description_vlm", "rubric_generator"]
    seen: dict[str, str] = {}
    for role in roles:
        key = base_model(models[role])
        if key in seen:
            raise ModelSeparationError(
                f"역할 분리 위반 — {seen[key]}와 {role}이 같은 모델({models[role]}). "
                f"RUBRIC_GEN_MODEL / JUDGE_MODEL env로 다른 모델을 지정할 것. 현재 배정: {models}"
            )
        seen[key] = role
    return models
