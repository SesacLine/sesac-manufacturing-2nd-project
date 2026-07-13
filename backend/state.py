"""RCAState — LangGraph 파이프라인 전체가 공유하는 상태.

필드 정의는 산출물_데이터모델설계.md §3/§3.0(Semiconductor/personalspace/0708 work/)이 정본이다.
GraphRAG 후보(candidates) 필드 구조는 kg_rca schema v2.3(SesacLine_SemiRCA/kg_rca/schema_v2.md)의
hypotheses.json 출력을 그대로 따른다 — cause/failure_mode 문자열은 fab.db와 join key가 아니다.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

Tier = Literal["자동", "반자동", "근거없음"]
EvidenceLabel = Literal["Parameter", "Maintenance", "Recipe", "None"]
Route = Literal["step", "direct", "signature"]


class VLMResult(TypedDict):
    """① VLM 노드 출력. 웨이퍼 1장당 1건."""

    lot_id: str
    wafer_id: str
    pattern: str
    spatial: str
    description: str
    severity: str
    confidence: float
    ambiguity: bool


class Group(TypedDict):
    """② Grouper 노드 출력."""

    group_id: str
    pattern: str
    lot_ids: list[str]
    status: str


class GraphRAGCandidate(TypedDict):
    """③ GraphRAG 노드가 kg_rca 순회 결과에서 그대로 옮겨 담는 후보 1건.

    필드는 kg_rca/outputs/hypotheses.json의 path/verification/score를 평탄화한 것.
    """

    cause: str
    failure_mode: str | None
    step: str | None
    signature: NotRequired[str | None]
    route: Route
    tier: Tier
    evidence_label: EvidenceLabel
    evidence: str | None
    fab_table: str | None
    direction: NotRequired[Literal["high", "low"] | None]
    occurrence_prior: NotRequired[str | None]
    confidence: float
    sentence: str


class GraphRAGResult(TypedDict):
    pattern: str
    candidates: list[GraphRAGCandidate]


class EvidenceEntry(TypedDict):
    """④ Hypothesis 노드가 candidate 하나마다 채우는 evidence.

    구조화된 값(Critic이 실제로 비교)과 표시용 문자열(⑥ 응답생성 전용)을 분리한다.
    산출물_데이터모델설계.md §3.1 참고.
    """

    commonality_ratio: float | None
    drift_detected: bool | None
    maintenance_hit: bool | None
    maintenance_ts: str | None
    recipe_match: bool | None
    alarm_hit: bool | None
    normal_ratio: float | None
    telemetry_summary: NotRequired[str]
    maintenance_summary: NotRequired[str]


class Hypothesis(TypedDict):
    """④ Hypothesis 노드 출력. GraphRAGCandidate 1건 + 수집한 증거."""

    cause: str
    tier: Tier
    equipment: str | None
    evidence: EvidenceEntry
    next_actions: NotRequired[list[str]]


class CriticResult(TypedDict):
    """⑤ Critic 노드 출력."""

    status: Literal["accepted", "insufficient_evidence"]
    accepted: list[Hypothesis]
    rejected: list[dict]


class FinalResponse(TypedDict):
    """⑥ 응답생성 노드 출력."""

    group_id: str
    pattern: str
    hypotheses: list[Hypothesis]
    rejected: list[dict]
    summary: str


class RCAState(TypedDict):
    """파이프라인 ⓪~⑥ 전체가 공유하는 상태 (LangGraph StateGraph의 state 타입)."""

    cursor_date: str
    target_lot_ids: list[str]
    vlm_results: list[VLMResult]
    groups: list[Group]
    graphrag_candidates: dict[str, GraphRAGResult]
    hypotheses: dict[str, list[Hypothesis]]
    critic_result: dict[str, CriticResult]
    final_response: dict[str, FinalResponse]
