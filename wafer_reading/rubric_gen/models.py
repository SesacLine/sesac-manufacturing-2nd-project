"""역할별 모델 배정 — **서술 / 루브릭 변환 / 판정은 서로 다른 모델이어야 한다**

- 평가 대상 VLM이 루브릭까지 만들면 **자기 어휘가 정답**이 된다(실측: 라벨 없이 정확히 읽은
  서술이 오히려 낮은 점수).
- 판정자가 평가 대상과 같으면 self-preference bias가 겹친다[Zheng2023].
- WaferSAGE도 teacher(Gemini) / 루브릭 변환(DeepSeek) / 판정(GPT-5-mini)을 분리한다.

**제약**: 변환·판정은 OpenAI API만 쓴다(자체 결정 — 추가 벤더 키 없음). 대신 **세대를 갈라**
독립성을 확보한다: 서술 5.4 / 변환 5.5 / 판정 5.2 (07-27 배정).

전부 env로 오버라이드 가능하되, 셋 중 둘이 같은 세대가 되면 `ModelSeparationError`로 즉시 실패.
"""

from __future__ import annotations

import os
import re

# 서술(평가 대상)은 판독 런타임 계약이라 여기서 바꾸지 않는다 — 값만 읽어 분리 검사에 쓴다.
from ..vlm.backends.openai_api import MODEL as VLM_PTY_MODEL

RUBRIC_GEN_MODEL = os.environ.get("RUBRIC_GEN_MODEL", "gpt-5.5-2026-04-23")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "gpt-5.2-2025-12-11")

# open 트랙 서술 모델(로컬) — 백엔드 상수를 그대로 읽는다(모델을 바꿔도 리포트 meta가 따라옴).
# import 시 torch/transformers를 끌어오지 않도록 상수만 참조한다.
from ..vlm.backends.qwen_local import MODEL_ID as QWEN_LOCAL_MODEL  # noqa: E402

_DATE_SUFFIX = re.compile(r"-\d{4}-\d{2}-\d{2}$")
_SIZE_SUFFIX = re.compile(r"-(mini|nano|pro)$")


class ModelSeparationError(RuntimeError):
    """세 역할 중 둘 이상이 독립적이지 않을 경우"""


def base_model(model_id: str) -> str:
    """동일성 정규화 — 별칭과 스냅샷 핀 제거

    `gpt-5.5`와 `gpt-5.5-2026-04-23`은 별칭↔스냅샷 관계라 문자 그대로 같은 모델임.
    """
    return _DATE_SUFFIX.sub("", str(model_id).strip().lower())


def model_family(model_id: str) -> str:
    """독립성 판정용 — 동일성에 더해 같은 세대의 크기 변형까지 제거"""
    return _SIZE_SUFFIX.sub("", base_model(model_id))


def vlm_model(track: str) -> str:
    return QWEN_LOCAL_MODEL if track == "open" else VLM_PTY_MODEL


def role_models(track: str = "pty") -> dict[str, str]:
    """리포트 meta에 기록할 역할별 모델(추적성 — 어떤 조합으로 낸 수치인지 남음)"""
    return {
        "description_vlm": vlm_model(track),
        "rubric_generator": RUBRIC_GEN_MODEL,
        "judge": JUDGE_MODEL,
    }


def assert_distinct(track: str = "pty", *, judge_used: bool = True) -> dict[str, str]:
    """3역할이 서로 독립적인지 검사하고 배정 돌림. 파이프라인 진입점에서 부를 것.

    판정 기준은 동일성(`base_model`)이 아니라 독립성(`model_family`)
    """
    models = role_models(track)
    roles = list(models) if judge_used else ["description_vlm", "rubric_generator"]
    seen: dict[str, str] = {}
    for role in roles:
        key = model_family(models[role])
        if key in seen:
            same_id = base_model(models[role]) == base_model(models[seen[key]])
            why = "같은 모델" if same_id else f"같은 세대의 크기 변형(계열 {key}) — 독립성 부족"
            raise ModelSeparationError(
                f"역할 분리 위반 — {seen[key]}와 {role}이 {why}({models[seen[key]]} vs {models[role]}). "
                f"RUBRIC_GEN_MODEL / JUDGE_MODEL env로 다른 세대의 모델을 지정할 것. 현재 배정: {models}"
            )
        seen[key] = role
    return models
