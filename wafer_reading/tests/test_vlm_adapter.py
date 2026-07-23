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


def test_parse_rejects_missing_field():
    partial = {k: v for k, v in VALID.items() if k != "total_description"}
    with pytest.raises(VLMParseError):
        _parse_response(json.dumps(partial))


def test_parse_accepts_code_fenced_json():
    fenced = "```json\n" + json.dumps(VALID) + "\n```"
    assert _parse_response(fenced)["total_description"] == VALID["total_description"]
