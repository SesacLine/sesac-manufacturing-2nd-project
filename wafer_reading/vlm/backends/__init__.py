"""VLM 백엔드 — 트랙 중립 메시지(adapter.build_messages 산출)를 각 API 포맷으로 변환·호출.

계약: generate(messages) -> str (모델의 원시 텍스트 응답). 파싱·재시도는 어댑터 공통층 몫.
"""
