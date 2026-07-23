"""pty 트랙 — OpenAI API 백엔드

- 모델: gpt-5.4-mini-2026-03-17. temperature 0, JSON 응답 강제
- OPENAI_API_KEY는 .env(루트)에서 로드
"""

from __future__ import annotations

import os

MODEL = os.environ.get("VLM_PTY_MODEL", "gpt-5.4-mini-2026-03-17")


class OpenAIBackend:
    def __init__(self, model: str = MODEL, timeout_s: float = 120.0):
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()
        self._client = OpenAI(timeout=timeout_s)
        self._model = model

    def generate(self, messages: list[dict]) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[_to_openai(m) for m in messages],
        )
        return resp.choices[0].message.content or ""


def _to_openai(message: dict) -> dict:
    content = []
    for block in message["content"]:
        if block["type"] == "text":
            content.append({"type": "text", "text": block["text"]})
        elif block["type"] == "image_png_base64":
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{block['data']}"}}
            )
        else:
            raise ValueError(f"unknown block type: {block['type']}")
    if message["role"] in ("system", "assistant") and len(content) == 1:
        return {"role": message["role"], "content": content[0]["text"]}
    return {"role": message["role"], "content": content}
