# WAEFER VLM 서빙 이미지 — 독자 모델(파인튜닝 가정) 오프라인 패키징
#
# 가중치를 이미지에 포함(bake)한다. 근거:
#   - 실제 팹은 폐쇄망(air-gap) — 런타임 다운로드 불가 전제
#   - wafer_reading/vlm/backends/qwen_local.py 계약과 동일 원칙(local_files_only=True,
#     "배포 시 이미지/볼륨에 미리 굽는다" — 팀 서빙 설계서 v1.0 참조)
#
# 빌드 전 준비(가중치 ~17GB):
#   uv run hf download Qwen/Qwen3-VL-8B-Instruct --local-dir models/waefer-vlm
# 빌드:
#   docker build -t waefer-vlm:0.1 .
# 실행(GPU 호스트 전용 — VRAM 24GB+ 권장):
#   docker run -d --gpus all -p 8001:8001 --name waefer-vlm waefer-vlm:0.1
# 내용물 검증(GPU 불필요 — 이미지 안에 가중치가 실재하는지):
#   docker run --rm --entrypoint ls waefer-vlm:0.1 -la /models/waefer-vlm

FROM vllm/vllm-openai:latest

COPY models/waefer-vlm /models/waefer-vlm

# 베이스 이미지의 ENTRYPOINT(`vllm serve`)를 그대로 쓰고 인자만 준다.
# ⚠️ `vllm serve`는 모델을 --model 플래그가 아니라 **위치 인자**로 받는다(0727 검증에서 발견).
# --served-model-name을 repo id로 고정해 클라이언트 기본값(VLM_OPEN_MODEL)과 일치시킨다
# → 백엔드 .env에서 VLM_OPEN_SERVED_MODEL을 따로 맞출 필요가 없다.
CMD ["/models/waefer-vlm", \
     "--served-model-name", "Qwen/Qwen3-VL-8B-Instruct", \
     "--port", "8001", \
     "--max-model-len", "8192", \
     "--dtype", "bfloat16"]
