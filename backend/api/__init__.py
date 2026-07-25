"""API 라우터 조립 — 계약 라우트 10종(정본 docs/API_명세서_v2.0.md §3.1 표).

main.py는 앱 조립(CORS·prefix·라우터 등록)만 하고, 엔드포인트는 전부 이 하위 모듈에 산다
(AGENT_GUIDE §1-b 라우터 분리 지침).
"""

from fastapi import APIRouter

from . import analyses, batches, charts, lots, yield_summary

api_router = APIRouter()
api_router.include_router(yield_summary.router)
api_router.include_router(analyses.router)
api_router.include_router(batches.router)
api_router.include_router(lots.router)
api_router.include_router(charts.router)
