"""FastAPI 진입점 — 앱 조립만 한다(CORS·prefix·라우터 등록·저장소 초기화).

엔드포인트는 전부 backend/api/ 하위 모듈에 있다(계약 라우트 10종, 정본 docs/API_명세서_v2.0.md
§3.1 표). 배치형 트리거 1개가 전부다 — 자유 질의/실시간 스트리밍 없음.

구 엔드포인트(POST /batch/run · GET /batch/results)는 2026-07-20 계약 라우트로 대체됐다:
    POST /batch/run    → POST /api/v1/batches (비동기 접수, §2.3)
    GET  /batch/results → GET /api/v1/analyses (§2.2)
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import seed, store
from .api import api_router

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """기동 시 데모 시딩(SEED_UNTIL)을 백그라운드로 띄운다 — 설정이 없으면 아무 일도 안 한다.

    시연은 "이미 며칠치가 쌓인 화면에서 오늘치를 눌러 누적"하는 흐름인데, 새로 올린 서버엔
    그 이전 내역이 없다. 사람이 배치를 여러 번 눌러 만들던 준비를 서버가 대신한다(backend/seed.py).
    기동을 막지 않으므로 헬스체크·프론트는 즉시 뜨고, 대기열이 실시간으로 채워진다.
    """
    task = seed.launch_if_configured()
    yield
    if task is not None and not task.done():
        # 종료 신호를 받으면 진행 중이던 배치만 정리한다 — 다음 기동이 끊긴 지점부터 재개한다.
        task.cancel()


app = FastAPI(title="SesacLine SemiRCA", lifespan=lifespan)

# §1 CORS: 개발 오리진(Vite) 허용, 메서드 GET/POST — 서버 미들웨어가 담당(프록시 미사용).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

store.init_db()

app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
