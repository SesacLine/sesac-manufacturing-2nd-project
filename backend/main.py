"""FastAPI 진입점 — 앱 조립만 한다(CORS·prefix·라우터 등록·저장소 초기화).

엔드포인트는 전부 backend/api/ 하위 모듈에 있다(계약 라우트 8종, 정본 docs/API_명세서_v1.0.md
§3.1 표). 배치형 트리거 1개가 전부다 — 자유 질의/실시간 스트리밍 없음.

구 엔드포인트(POST /batch/run · GET /batch/results)는 2026-07-20 계약 라우트로 대체됐다:
    POST /batch/run    → POST /api/v1/batches (비동기 접수, §2.3)
    GET  /batch/results → GET /api/v1/analyses (§2.2)
"""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import store
from .api import api_router

load_dotenv()

app = FastAPI(title="SesacLine SemiRCA")

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
