"""VLM 어댑터 — 그룹 이미지 1장을 few-shot ICL로 서술해 backend Observation을 만듦.

    - 분기 flag: "pty" = OpenAI API(기본) / "open" = Qwen3-VL-8B-Instruct(opt-in).
    - 환경변수 VLM_TRACK으로 선택.
    - open은 실행 위치가 둘이다:
        · 로컬(기본)  — 프로세스 안에 직접 로드. GPU + **사전 다운로드된** 가중치 전제로,
                        런타임 다운로드를 하지 않는다(backends/qwen_local.py).
        · 원격        — VLM_OPEN_BASE_URL을 주면 OpenAI 호환 서버(자체 호스팅 vLLM 등)를
                        호출한다. GPU 불필요 — GPU 없는 팀원도 open 트랙을 쓸 수 있다.
      배포·서빙 정본: sdoubleoj/0727 work/VLM_오픈모델_서빙_설계서_v1.0.md
    - 프롬프트 및 예시는 두 트랙 공용으로, 내용 분기 금지
"""

from .adapter import VLMReader

__all__ = ["VLMReader"]
