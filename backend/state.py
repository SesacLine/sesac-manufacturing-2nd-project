"""RCAState — LangGraph 파이프라인 전체가 공유하는 상태.

필드 정의는 산출물_데이터모델설계.md §3/§3.0(Semiconductor/personalspace/0708 work/)이 정본이다.
GraphRAG 후보(candidates) 필드 구조는 kg_rca schema v2.4(SesacLine_SemiRCA/docs/KG_schema_v1.2.md,
출력 필드 상세는 kg_rca/KG_output_명세.md)의 hypotheses.json 출력을 그대로 따른다 —
cause/failure_mode 문자열은 fab.db와 join key가 아니다.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

Tier = Literal["자동", "반자동", "근거없음"]
EvidenceLabel = Literal["Parameter", "Maintenance", "Recipe", "None"]
# MCP 검증 체인 라우팅 힌트(kg_rca 07-13 갱신). Parameter->A3, Recipe->A5,
# Maintenance->consumable 여부로 A6/A2, 근거없음->None. hypothesis.py는 아직 tier/evidence_label
# 분기만 쓰고 scenario_hint는 안 읽는다 — Maintenance A2/A6 세분화가 필요해지면 참고할 것.
ScenarioHint = Literal["A2", "A3", "A5", "A6"]


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
    kg_rca 07-13 갱신으로 `route`/`score.confidence`는 출력에서 빠졌다(대신 `scenario_hint`,
    `score.evidence_docs`/`evidence_chunks`) — 경로 종류(공정경유/형상경유/문헌직결)가 필요하면
    signature/step의 null 패턴으로 판별한다(kg_rca/KG_output_명세.md 참고).
    """

    cause: str
    failure_mode: str | None
    step: str | None
    signature: NotRequired[str | None]
    scenario_hint: NotRequired[ScenarioHint | None]
    tier: Tier
    evidence_label: EvidenceLabel
    evidence: str | None
    fab_table: str | None
    direction: NotRequired[Literal["high", "low"] | None]
    occurrence_prior: NotRequired[str | None]
    unverifiable_signals: NotRequired[list[str] | None]
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
