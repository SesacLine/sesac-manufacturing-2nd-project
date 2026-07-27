"""VLM 어댑터 단위 테스트: 데이터/GPU/API 키 없이 돎(fake backend 주입)

- pytest -q wafer_reading/tests  (CI의 -m "not data"에서도 그대로 통과해야 함)
- 계약: VLM 출력 = 텍스트 4필드(pattern_candidate/location_text/morphology_text/total_description).
- 구조화 필드는 quantitative.compute_group_stats 소관이라 어댑터 테스트 범위 밖
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from wafer_reading.vlm.adapter import VLMCallError, VLMParseError, VLMReader, _parse_response

VALID = {
    "pattern_candidate": "Edge-Ring",
    "location_text": "failing dies around the wafer edge.",
    "morphology_text": "a continuous high-density band.",
    "total_description": "a continuous ring at the periphery.",
}


def _ring_map(size: int = 30) -> np.ndarray:
    """가장자리 링 형태의 합성 웨이퍼맵 (0=no die, 1=pass, 2=fail)."""
    y, x = np.mgrid[:size, :size]
    r = np.hypot((y - size / 2 + 0.5) / (size / 2), (x - size / 2 + 0.5) / (size / 2))
    arr = np.zeros((size, size), dtype=np.uint8)
    arr[r < 1.0] = 1
    arr[(r >= 0.8) & (r < 1.0)] = 2
    return arr


class FakeBackend:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def generate(self, messages):
        self.calls += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_describe_group_returns_texts_and_metadata():
    reader = VLMReader(track="pty", backend=FakeBackend([json.dumps(VALID)]))
    result = reader.describe_group("Edge-Ring", [_ring_map() for _ in range(4)])

    assert result["location_text"] == VALID["location_text"]
    assert result["morphology_text"] == VALID["morphology_text"]
    assert result["total_description"] == VALID["total_description"]
    assert result["pattern_candidate"] == "Edge-Ring"  # CNN 라벨 강제 유지
    assert result["image_mode"] == "stacked"
    assert result["vlm_track"] == "pty"
    assert "observation" not in result and "angular_coverage" not in result


def test_scratch_uses_single_image_branch():
    reader = VLMReader(
        track="pty", backend=FakeBackend([json.dumps(VALID | {"pattern_candidate": "Scratch"})])
    )
    result = reader.describe_group("Scratch", [_ring_map() for _ in range(3)])
    assert result["image_mode"] == "single"
    assert result["n_wafers"] == 3  # 메타데이터는 그룹 전체 기준 유지(임시)


def test_retry_then_success_on_bad_json():
    backend = FakeBackend(["not json at all", json.dumps(VALID)])
    reader = VLMReader(track="pty", backend=backend)
    result = reader.describe_group("Center", [_ring_map()])
    assert backend.calls == 2
    assert result["location_text"] == VALID["location_text"]


def test_exhausted_retries_raise():
    backend = FakeBackend(["bad", "bad", "bad"])
    reader = VLMReader(track="pty", backend=backend)
    with pytest.raises(VLMCallError):
        reader.describe_group("Center", [_ring_map()])
    assert backend.calls == 3  # 1 + 재시도 2


def test_non_parse_backend_error_still_raises_vlm_call_error():
    """2026-07-27 회귀 — 인증 실패·RateLimitError 등 백엔드 고유 예외(VLMParseError/
    TimeoutError/ConnectionError/OSError가 아닌 것)도 재시도 소진 후 VLMCallError로
    단일화돼야 한다. 좁은 except 목록 시절엔 이런 예외가 그대로 새서, 배치 그래프 노드
    (observe_groups)가 그룹별 격리 없이 배치 전체를 죽이는 사고로 이어졌다."""
    backend = FakeBackend([RuntimeError("401 Unauthorized"), RuntimeError("401 Unauthorized"),
                           RuntimeError("401 Unauthorized")])
    reader = VLMReader(track="pty", backend=backend)
    with pytest.raises(VLMCallError):
        reader.describe_group("Center", [_ring_map()])
    assert backend.calls == 3  # 좁은 except였다면 1회 만에 RuntimeError가 그대로 새나갔을 것


def test_parse_rejects_missing_field():
    partial = {k: v for k, v in VALID.items() if k != "total_description"}
    with pytest.raises(VLMParseError):
        _parse_response(json.dumps(partial))


def test_parse_accepts_code_fenced_json():
    fenced = "```json\n" + json.dumps(VALID) + "\n```"
    assert _parse_response(fenced)["total_description"] == VALID["total_description"]


# --- 트랙 선택 (기본 pty / open의 local·remote 두 모드) — 모델 로드·네트워크 없이 확인 ---


def test_default_track_is_pty(monkeypatch):
    """GPU 없는 팀원·CI가 기본값으로 동작해야 하므로 open은 opt-in이다."""
    monkeypatch.delenv("VLM_TRACK", raising=False)
    reader = VLMReader(backend=FakeBackend([]))
    assert reader.track == "pty"
    assert reader.open_mode is None


def test_open_track_is_local_without_base_url(monkeypatch):
    monkeypatch.delenv("VLM_OPEN_BASE_URL", raising=False)
    assert VLMReader(track="open", backend=FakeBackend([])).open_mode == "local"


def test_open_track_is_remote_with_base_url(monkeypatch):
    monkeypatch.setenv("VLM_OPEN_BASE_URL", "http://gpu-host:8001/v1")
    assert VLMReader(track="open", backend=FakeBackend([])).open_mode == "remote"


def test_open_remote_backend_targets_endpoint_and_open_model(monkeypatch):
    """원격 모드는 OpenAI 호환 백엔드를 쓰되 **open 모델명**으로 부른다(pty 모델이 아니라)."""
    from wafer_reading.vlm.adapter import _open_backend
    from wafer_reading.vlm.backends.openai_api import OpenAIBackend
    from wafer_reading.vlm.backends.qwen_local import MODEL_ID

    monkeypatch.setenv("VLM_OPEN_BASE_URL", "http://gpu-host:8001/v1")
    monkeypatch.setenv("VLM_OPEN_API_KEY", "token-123")
    monkeypatch.delenv("VLM_OPEN_SERVED_MODEL", raising=False)

    backend = _open_backend(timeout_s=1.0)
    assert isinstance(backend, OpenAIBackend)
    assert backend._model == MODEL_ID
    assert str(backend._client.base_url).rstrip("/") == "http://gpu-host:8001/v1"


def test_open_remote_backend_honors_served_model_override(monkeypatch):
    from wafer_reading.vlm.adapter import _open_backend

    monkeypatch.setenv("VLM_OPEN_BASE_URL", "http://gpu-host:8001/v1")
    monkeypatch.setenv("VLM_OPEN_SERVED_MODEL", "qwen3-vl-8b")
    assert _open_backend(timeout_s=1.0)._model == "qwen3-vl-8b"
