"""공통 응답 스키마"""
from pydantic import BaseModel, Field
from typing import Any

SCOPE_NOTE = "전공정~wafer test 단계 데이터. 패키징 이후 이력 없음."

class Coverage(BaseModel):
    time_range_queried: str | None = None
    time_range_available: str | None = None
    missing: list[str] = Field(default_factory=list)

class Meta(BaseModel):
    source: str = "synthetic (SECS/GEM simulator v1, dataset seed 20260101)"
    coverage: Coverage = Field(default_factory=Coverage)
    scope_note: str = SCOPE_NOTE

class ToolResponse(BaseModel):
    data: Any
    meta: Meta = Field(default_factory=Meta)

def respond(data, *, queried=None, available=None, missing=None) -> dict:
    return ToolResponse(
        data=data,
        meta=Meta(coverage=Coverage(
            time_range_queried=queried, time_range_available=available,
            missing=missing or [])),
    ).model_dump()