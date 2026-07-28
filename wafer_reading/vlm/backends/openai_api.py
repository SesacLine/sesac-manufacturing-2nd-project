"""OpenAI 호환 HTTP 백엔드 — pty 트랙(OpenAI 클라우드) + open 트랙 원격 모드 공용

- 모델: gpt-5.4-mini-2026-03-17. temperature 0, JSON 응답 강제
- OPENAI_API_KEY는 .env(루트)에서 로드
- `base_url`/`api_key`를 주면 **OpenAI 호환 서버**(자체 호스팅 vLLM 등)를 부른다 —
  open 트랙 원격 모드가 이 경로를 쓴다(`adapter.VLMReader`). 환경변수(`OPENAI_BASE_URL`)로
  돌리지 않고 **인자로 명시 주입**하는 이유: 환경변수는 같은 프로세스의 pty 트랙 호출과
  ⑦ 응답생성 LLM까지 통째로 리다이렉트해버린다.
"""

from __future__ import annotations

import os

# VLM 서술(pty) 모델
MODEL = os.environ.get("VLM_PTY_MODEL", "gpt-5.4-2026-03-05")


class OpenAIBackend:
    """temperature는 기본 0(재현성). 모델이 0을 거부하면 한 번만 생략하고 재시도한다.

    `gpt-5.5-2026-04-23`은 temperature 기본값(1)만 허용해 400을 낸다
    (`gpt-5.4-mini`·`gpt-5.2`는 0 지원). 평가용 상위 모델을 쓰려면 이 폴백이 필요하다 —
    대신 그 모델의 산출물은 비결정적이므로 산출물 자체를 커밋해 고정함.
    """

    def __init__(
        self,
        model: str = MODEL,
        timeout_s: float = 120.0,
        temperature: float | None = 0,
        base_url: str | None = None,
        api_key: str | None = None,
        seed: int | None = None,
    ):
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()
        # 자체 호스팅 서버는 키 검사를 안 켤 수 있는데, SDK는 키가 없으면 생성 자체를 거부한다.
        # base_url을 줬는데 키가 없으면 자리표시자를 넣는다(클라우드 경로에는 영향 없음).
        kwargs = {"timeout": timeout_s}
        if base_url:
            kwargs["base_url"] = base_url
            kwargs["api_key"] = api_key or "EMPTY"
        elif api_key:
            kwargs["api_key"] = api_key
        self._client = OpenAI(**kwargs)
        self._model = model
        self._temperature = temperature
        self._seed = seed

    def generate(self, messages: list[dict]) -> str:
        payload = [_to_openai(m) for m in messages]
        try:
            return self._create(payload)
        except Exception as e:
            if self._temperature is None or "temperature" not in str(e):
                raise
            print(f"[warn] {self._model}: temperature={self._temperature} 미지원 → 모델 기본값으로 재시도")
            self._temperature = None
            return self._create(payload)

    def _create(self, payload: list[dict]) -> str:
        kwargs = {} if self._temperature is None else {"temperature": self._temperature}
        if self._seed is not None:
            kwargs["seed"] = self._seed
        resp = self._client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            messages=payload,
            **kwargs,
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
