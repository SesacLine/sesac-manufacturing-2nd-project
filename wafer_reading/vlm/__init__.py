"""VLM 어댑터 — 그룹 이미지 1장을 few-shot ICL로 서술해 backend Observation을 만듦.

    - 분기 flag: "open" = Qwen3-VL-4B-Instruct 로컬 / "pty" = OpenAI API. 기본 "open".
    - 환경변수 VLM_TRACK으로 선택
    - 프롬프트 및 예시는 두 트랙 공용으로, 내용 분기 금지
"""

from .adapter import VLMReader

__all__ = ["VLMReader"]
