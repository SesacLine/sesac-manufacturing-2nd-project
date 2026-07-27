"""라벨 prior 차단 회귀 테스트 (발견문제 #18 / 이슈 #100) — API·GPU 없이 돎.

CNN 라벨이 프롬프트로 새어 들어가면 모델이 이미지 대신 라벨을 따라 서술한다(실측: 결함 0인
웨이퍼에 "Center" 라벨을 주자 없는 결함을 상세히 지어냄). 그래서 **라벨이 프롬프트에 없다**는
사실 자체를 계약으로 고정한다 — 프롬프트 문구를 되돌리면 여기서 깨진다.

실제 서술 품질은 API 호출이 필요해 여기서 볼 수 없다 —
`python -m wafer_reading.rubric_gen.ablation` 참고(어블레이션 7콜).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from wafer_reading.vlm.adapter import VLMReader, build_messages
from wafer_reading.vlm.prompts import (
    FEWSHOT_EXAMPLES,
    SINGLE_QUERY_TEXT,
    STACKED_QUERY_TEXT,
    SYSTEM_PROMPT,
)

PATTERNS = ("Center", "Edge-Ring", "Scratch")
VLM_SAYS = {
    "pattern_candidate": "Edge-Ring",  # 모델이 이미지에서 읽은 값 (CNN 라벨과 다르게 둔다)
    "location_text": "failing dies around the wafer edge.",
    "morphology_text": "a continuous high-density band.",
    "total_description": "a continuous ring at the periphery.",
}


class FakeBackend:
    """호출 시 받은 messages를 기록해 두는 백엔드."""

    def __init__(self, response: dict):
        self.response = response
        self.messages = None

    def generate(self, messages):
        self.messages = messages
        return json.dumps(self.response)


def _map(size: int = 30) -> np.ndarray:
    y, x = np.mgrid[:size, :size]
    r = np.hypot((y - size / 2 + 0.5) / (size / 2), (x - size / 2 + 0.5) / (size / 2))
    arr = np.zeros((size, size), dtype=np.uint8)
    arr[r < 1.0] = 1
    arr[r < 0.3] = 2
    return arr


def _all_text(messages: list[dict]) -> str:
    return " ".join(
        b["text"] for m in messages for b in m["content"] if b["type"] == "text"
    )


# --- 프롬프트에 라벨이 없다 (문구 자체를 고정) ---


def test_query_templates_have_no_label_placeholder():
    """쿼리 템플릿에 패턴 자리표시자가 있으면 라벨이 프롬프트로 들어갈 통로가 생긴다."""
    assert "{pattern}" not in STACKED_QUERY_TEXT
    assert "{pattern}" not in SINGLE_QUERY_TEXT


@pytest.mark.parametrize(
    "text", [SYSTEM_PROMPT, STACKED_QUERY_TEXT, SINGLE_QUERY_TEXT], ids=["system", "stacked", "single"]
)
def test_prompts_do_not_mention_cnn_label(text):
    lowered = text.lower()
    assert "cnn label" not in lowered
    assert "echo the given" not in lowered


def test_fewshot_user_texts_carry_no_label():
    """few-shot이 '라벨→서술' 매핑을 가르치면 안 된다 — 가르쳐야 할 건 '이미지→서술'이다."""
    for ex in FEWSHOT_EXAMPLES:
        assert "cnn label" not in ex["user_text"].lower()
        for pattern in PATTERNS:
            assert pattern.lower() not in ex["user_text"].lower()


@pytest.mark.parametrize("pattern", PATTERNS)
def test_query_text_carries_no_label(pattern):
    """마지막 user 턴(이번 이미지에 대한 질의)에 패턴명이 없어야 한다.

    시스템 프롬프트에는 `pattern_candidate`가 가질 수 있는 값 목록이 있지만, 그건 **매 호출
    동일한 정적 어휘**라 이번 이미지가 무엇인지는 알려주지 않는다. 라벨 누출은 호출마다
    달라지는 질의 텍스트에서 일어난다.
    """
    backend = FakeBackend(VLM_SAYS)
    VLMReader(track="pty", backend=backend).describe_group(pattern, [_map() for _ in range(3)])
    query = _all_text([backend.messages[-1]])
    assert pattern.lower() not in query.lower()


def test_prompt_is_identical_regardless_of_cnn_label():
    """같은 이미지라면 CNN 라벨이 뭐든 프롬프트가 **완전히 동일**해야 한다.

    라벨이 프롬프트에 어떤 형태로든 영향을 주면 여기서 깨진다 — #18의 핵심 불변식이다.
    (Scratch는 라벨로 이미지 분기를 바꾸는 게 설계라 제외 — stacked 경로끼리 비교한다.)
    """
    maps = [_map() for _ in range(3)]
    texts = []
    for pattern in ("Center", "Edge-Ring"):
        backend = FakeBackend(VLM_SAYS)
        VLMReader(track="pty", backend=backend).describe_group(pattern, maps)
        texts.append(_all_text([m for m in backend.messages if m["role"] in ("system", "user")]))
    assert texts[0] == texts[1]


# --- 판독 불일치 신호 ---


def test_cnn_label_wins_contract_but_vlm_guess_is_preserved():
    """pattern_candidate는 계약상 CNN 라벨이고, 모델의 독립 판독은 따로 남는다."""
    reader = VLMReader(track="pty", backend=FakeBackend(VLM_SAYS))
    out = reader.describe_group("Center", [_map() for _ in range(3)])

    assert out["pattern_candidate"] == "Center"  # state.Observation 계약
    assert out["vlm_pattern_guess"] == "Edge-Ring"  # 이미지에서 읽은 값 — CNN과 불일치


def test_vlm_guess_matches_when_cnn_and_image_agree():
    reader = VLMReader(track="pty", backend=FakeBackend(VLM_SAYS | {"pattern_candidate": "Center"}))
    out = reader.describe_group("Center", [_map() for _ in range(3)])
    assert out["pattern_candidate"] == out["vlm_pattern_guess"] == "Center"
