"""API 경계 정규화 — 명세 §3 고정 vocabulary와 내부(노드) 표기 사이의 변환.

AGENT_GUIDE §1-b: enum 정규화는 API 경계에서만 한다. state.py의 Tier는 한글
("자동"/"반자동"/"근거없음")이고 hypothesis.py·critic.py가 그 값으로 분기하므로
노드 안에서는 절대 바꾸지 않는다 — 여기(FastAPI 쪽)에서만 auto/semi_auto/none으로 바꾼다.
pattern도 같은 노선: CNN/DB가 어떤 표기로 내보내든 API가 5종으로 접어 내려준다(§2.2).
"""

from __future__ import annotations

import re

PATTERNS = ("Center", "Edge-Ring", "Scratch", "Unknown", "Normal")
MAPPED_PATTERNS = ("Center", "Edge-Ring", "Scratch")

# 명세 §2.2: WM-811K 원 9종 중 비매핑 결함은 Unknown으로 단일화.
_UNMAPPED_RAW = {"edge-loc", "loc", "donut", "near-full", "nearfull", "random"}

_TIER_MAP = {
    "자동": "auto",
    "반자동": "semi_auto",
    "근거없음": "none",
    "auto": "auto",
    "semi_auto": "semi_auto",
    "none": "none",
}

# 명세 §2.4 steps[] 고정 8키 (AGENT_GUIDE §5 매핑표 기준 코드 노드와 대응)
STEPS = [
    "lot_selection",
    "cnn_classify",
    "grouping",
    "vlm_describe",
    "cause_lookup",
    "hypothesis",
    "critic",
    "response_gen",
]

# LangGraph 노드명 → steps[] 인덱스. vlm_describe(3)는 대응 노드가 없어 건너뛴다
# (AGENT_GUIDE §5: 임의 매핑 금지 — vlm.py의 웨이퍼 단위 서술은 vlm_describe가 아니다).
NODE_TO_STEP_INDEX = {
    "select_low_yield_lots": 0,
    "read_wafer_maps": 1,
    "group_by_pattern": 2,
    "fetch_graphrag_candidates": 4,
    "build_hypotheses": 5,
    "review_hypotheses": 6,
    "generate_response": 7,
}


def normalize_pattern(raw: str | None) -> str:
    """CNN/VLM/DB 원시 패턴 표기를 명세 5종으로 정규화한다."""
    if not raw:
        return "Unknown"
    if raw in PATTERNS:
        return raw
    lowered = raw.strip().lower()
    if lowered == "normal":
        return "Normal"
    if lowered == "center":
        return "Center"
    if lowered in ("edge-ring", "edgering", "edge_ring"):
        return "Edge-Ring"
    if lowered == "scratch":
        return "Scratch"
    # 비매핑 결함 고유명 + 그 외 미지 표기 전부 Unknown으로 접는다.
    return "Unknown"


def normalize_tier(raw: str) -> str:
    return _TIER_MAP.get(raw, "none")


def pattern_slug(pattern: str) -> str:
    """analysis_id의 {패턴} 조각 — 소문자·영숫자만 (Edge-Ring → edgering)."""
    return re.sub(r"[^a-z0-9]", "", pattern.lower())
