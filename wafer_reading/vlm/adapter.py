"""VLM 어댑터 — 그룹 웨이퍼맵 -> 이미지 렌더 -> VLM 자연어 서술

    - 구조화 필드(shape/zone/signature/angular/clock/density/continuity/defect_die_ratio)는 전부 quantitative.compute_group_stats가 산출
    - 이 어댑터의 VLM은 자연어 텍스트만 생성(location_text/morphology_text/total_description)
    - 이미지 분기: Center/Edge-Ring/Unknown = 그룹 스태킹 1장, Scratch = 스태킹 없이 단일 이미지
    - 단일 이미지 선정 규칙: 그룹에서 결함 die 수가 가장 많은 웨이퍼(신호 강도 최대)
    - 재시도/타임아웃: 요청 타임아웃 120s, 파싱/호출 오류 통합 재시도 2회
    - 최종 실패 시 VLMCallError: 호출측(backend observe 노드)이 그룹을 자연어 없는 관측으로 유지할지 결정 필요
"""

from __future__ import annotations

import json
import os
import re

import numpy as np

from ..stacking import stack_wafer_maps
from .prompts import (
    ASSETS_DIR,
    FEWSHOT_EXAMPLES,
    RESPONSE_FIELDS,
    SINGLE_QUERY_TEXT,
    STACKED_QUERY_TEXT,
    SYSTEM_PROMPT,
)

DEFAULT_TIMEOUT_S = 120.0
MAX_RETRIES = 2  # 최초 1회 + 재시도 2회

FAIL_DIE = 2


class VLMCallError(RuntimeError):
    """재시도 소진 후에도 유효한 VLM 응답을 얻지 못할 경우"""


def _open_remote_url() -> str:
    """open 트랙 원격 엔드포인트. 빈 문자열이면 로컬 모드."""
    return os.environ.get("VLM_OPEN_BASE_URL", "").strip()


def _open_backend(timeout_s: float):
    """open 트랙 백엔드 선택 — 트랙 의미("오픈웨이트 모델")는 유지하고 실행 위치만 나눈다.

    `VLM_OPEN_BASE_URL` 설정 → OpenAI 호환 서버(자체 호스팅 vLLM 등)를 호출한다. **GPU 불필요**
    이므로 GPU 없는 팀원·CPU 인스턴스도 open 트랙을 그대로 쓸 수 있다(발견문제 #25).
    미설정 → 종전대로 프로세스 안에 직접 로드한다(GPU + 사전 다운로드된 가중치 필요).

    서버가 알리는 모델명이 repo id와 다르면(`vllm serve --served-model-name`)
    `VLM_OPEN_SERVED_MODEL`로 맞춘다. 기본은 `VLM_OPEN_MODEL`과 같은 값이라 보통 손댈 필요 없다.
    """
    base_url = _open_remote_url()
    if not base_url:
        from .backends.qwen_local import QwenLocalBackend

        return QwenLocalBackend()

    from .backends.openai_api import OpenAIBackend
    from .backends.qwen_local import MODEL_ID  # 상수만 참조 — torch를 끌어오지 않는다

    return OpenAIBackend(
        model=os.environ.get("VLM_OPEN_SERVED_MODEL", MODEL_ID),
        timeout_s=timeout_s,
        base_url=base_url,
        api_key=os.environ.get("VLM_OPEN_API_KEY"),
    )


class VLMReader:
    """flag(open/pty) 택1 백엔드로 그룹 이미지를 서술. 프롬프트는 트랙 공용으로 사용.

    `open`은 실행 위치가 둘이다 — `open_mode` 속성으로 확인한다:
    `"local"`(프로세스 내 로드) / `"remote"`(OpenAI 호환 서버). 산출물이 경로에 따라 문장
    수준에서 달라질 수 있으므로 평가 수치를 낼 때는 한쪽으로 고정할 것.
    """

    def __init__(self, track: str | None = None, backend=None, timeout_s: float = DEFAULT_TIMEOUT_S):
        # 기본은 pty(OpenAI API) — GPU 없는 팀원·CI가 기본값으로 동작해야 하기 때문이다.
        # open(로컬 오픈웨이트)은 GPU와 사전 다운로드된 가중치를 요구하므로 명시적 opt-in이다.
        self.track = track or os.environ.get("VLM_TRACK", "pty")
        self.timeout_s = timeout_s
        self.open_mode = (
            ("remote" if _open_remote_url() else "local") if self.track == "open" else None
        )
        if backend is not None:  # 테스트용
            self._backend = backend
        elif self.track == "pty":
            from .backends.openai_api import OpenAIBackend

            self._backend = OpenAIBackend(timeout_s=timeout_s)
        elif self.track == "open":
            self._backend = _open_backend(timeout_s)
        else:
            raise ValueError(f"unknown VLM_TRACK: {self.track!r} (open|pty)")

    def describe_group(
        self, pattern: str, wafer_maps: list[np.ndarray], wafer_keys: list | None = None
    ) -> dict:
        """그룹 1건의 자연어 서술:
        location_text / morphology_text / total_description  <- 소비측이 Observation에 얹는 값
        vlm_track / n_wafers / image_mode
        (구조화 필드는 전부 quantitative.compute_group_stats 소관)
        """
        image_mode, png_b64, n_shown = self._render_image(pattern, wafer_maps, wafer_keys)
        if image_mode == "single":
            query_text = SINGLE_QUERY_TEXT.format(pattern=pattern)
        else:
            query_text = STACKED_QUERY_TEXT.format(pattern=pattern, n=n_shown)

        parsed = self._call_with_retry(build_messages(query_text, png_b64), pattern)
        return {
            **parsed,  # location/morphology/total_description + pattern_candidate 에코
            "pattern_candidate": pattern,  # CNN 라벨 강제 유지
            "vlm_track": self.track,
            "n_wafers": len(wafer_maps),
            "image_mode": image_mode,
        }

    def _render_image(self, pattern, wafer_maps, wafer_keys):
        if pattern == "Scratch":
            idx = int(np.argmax([(np.asarray(m) == FAIL_DIE).sum() for m in wafer_maps]))
            keys = [wafer_keys[idx]] if wafer_keys else None
            hm = stack_wafer_maps([wafer_maps[idx]], wafer_keys=keys)
            return "single", hm.to_png_base64(), 1
        hm = stack_wafer_maps(wafer_maps, wafer_keys=wafer_keys)
        return "stacked", hm.to_png_base64(), len(wafer_maps)

    def _call_with_retry(self, messages: list[dict], pattern: str) -> dict:
        last_err: Exception | None = None
        for _ in range(1 + MAX_RETRIES):
            try:
                text = self._backend.generate(messages)
                return _parse_response(text)
            except Exception as e:  # noqa: BLE001 — 백엔드가 뭘 던지든(인증 실패·RateLimitError·
                # 5xx 등 OpenAI/로컬 백엔드 고유 예외 포함) 재시도 소진 후 VLMCallError로 단일화한다.
                # 좁은 예외 목록(VLMParseError/TimeoutError/ConnectionError/OSError)만 잡던 옛
                # 구현은 인증·요금제 오류가 그대로 새나가게 뒀다 — observe_groups(③)는 배치
                # 그래프 노드라 그룹별 격리(④~⑦ 서브그래프 전용) 밖이라, 그룹 하나의 API 실패가
                # 배치 전체를 status=failed로 끌고 내려가는 사고로 이어졌다(2026-07-27 발견).
                last_err = e
        raise VLMCallError(f"VLM call failed({pattern}, track={self.track}): {last_err}") from last_err


class VLMParseError(ValueError):
    """응답이 JSON 계약을 어길 경우"""


def build_messages(query_text: str, query_png_b64: str) -> list[dict]:
    """트랙 중립 메시지 목록
    - content 블록: {"type":"text"|"image_png_base64", ...}
    - 각 백엔드가 자기 포맷(OpenAI image_url / Qwen chat template)으로 변환
    - 이미지 순서 및 텍스트는 트랙 동일(내용 분기 금지)
    """
    messages: list[dict] = [{"role": "system", "content": [{"type": "text", "text": SYSTEM_PROMPT}]}]
    for ex in FEWSHOT_EXAMPLES:
        png = (ASSETS_DIR / ex["asset"]).read_bytes()
        import base64

        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "image_png_base64", "data": base64.b64encode(png).decode("ascii")},
                    {"type": "text", "text": ex["user_text"]},
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


def _parse_response(text: str) -> dict:
    """모델 텍스트 -> 텍스트 4필드 dict. 코드펜스 허용, 필드 검사(스키마 준수 여부만)"""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise VLMParseError(f"JSON object not found: {text[:200]!r}")
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise VLMParseError(f"JSON parsing failed: {e}") from e
    missing = [f for f in RESPONSE_FIELDS if f not in obj or not isinstance(obj[f], str)]
    if missing:
        raise VLMParseError(f"field missing/type error: {missing}")
    return {f: obj[f] for f in RESPONSE_FIELDS}
