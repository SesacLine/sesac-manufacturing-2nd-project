"""RCAState — LangGraph 파이프라인 전체가 공유하는 상태.

필드 정의는 산출물_데이터모델설계.md §3/§3.0(Semiconductor/personalspace/0708 work/)이 정본이다.
GraphRAG 후보(candidates) 필드 구조는 kg_rca schema v2.5(docs/KG_schema_v1.3.md,
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


class Observation(TypedDict):
    """③ 관측 — 그룹(스택맵) 단위 1건. KG 조회(get_candidates)의 관측 입력.

    CNN 라벨 + VLM 자연어(스택 이미지 판독) + die-matrix(스택맵 통계)를 합친 것.
    웨이퍼별 판독을 합치는 집계 과정은 **없다** — VLM/die-matrix가 같은 CNN 라벨 웨이퍼들의
    die_map을 오버레이한 스택맵에 1회 적용되므로 애초에 그룹 단위로 생산된다.
    location_text/morphology_text(자연어)는 의미 진입(임베딩)에, angular 등(구조화)은 판별자에 쓰인다.
    """

    pattern_candidate: str                       # CNN 라벨 (3종 or "Unknown"). = Group["pattern"]
    location_text: str                           # VLM 자연어 (공간 분포)
    morphology_text: str                         # VLM 자연어 (형상)
    angular_coverage: NotRequired[str]           # die-matrix: full|partial|unknown
    clock_positions: NotRequired[list[int]]      # die-matrix: 1~12 (partial일 때만)
    density: NotRequired[str]                    # high|medium|low|unknown
    continuity: NotRequired[str]                 # continuous|intermittent|discontinuous|not_applicable|unknown
    defect_die_ratio: NotRequired[float]         # die-matrix 정량값
    description: NotRequired[str]                # location+morphology 대체용 단일 서술(폴백)
    signature: NotRequired[str | None]           # 규칙 정규화가 shape@zone을 직접 줄 때만(선택)


class Group(TypedDict):
    """② Grouper 노드 출력."""

    group_id: str
    pattern: str
    lot_ids: list[str]
    status: str
    # ③ VLM+die-matrix(스택맵)가 채우는 그룹 단위 관측 1건. 미배선 시 없음/None.
    # nodes/graphrag.py가 group.get("observation")으로 읽어 get_candidates에 넘긴다.
    observation: NotRequired[Observation | None]


class Citation(TypedDict):
    """문헌 인용 1건 — API 명세 §2.5/§2.7 citations[] 원소와 동일 스키마."""

    id: int
    text: str


class GraphRAGCandidate(TypedDict):
    """③ GraphRAG 노드가 kg_rca 순회 결과에서 그대로 옮겨 담는 후보 1건.

    필드는 kg_rca/outputs/hypotheses.json의 path/verification/score를 평탄화한 것.
    kg_rca 07-13 갱신으로 `route`/`score.confidence`는 출력에서 빠졌다(대신 `scenario_hint`,
    `score.evidence_docs`/`evidence_chunks`) — 경로 종류(공정경유/형상경유/문헌직결)가 필요하면
    signature/step의 null 패턴으로 판별한다(kg_rca/KG_output_명세.md 참고).
    citations는 provenance.chunk_ids의 문서명에서 KGClient가 유도한다(API 명세 §2.5 citations[]).
    """

    cause: str
    failure_mode: str | None
    step: str | None
    signature: NotRequired[str | None]
    # 형상 경유(FORMS_IN) 후보의 모폴로지 — hypotheses.json path.morphology를 그대로 옮긴 것.
    # {density, continuity, angular_coverage, clock_positions}. shape@zone은 하드 매칭 키이고
    # 이 값들은 VLM 관측과 소프트 매칭하는 랭킹 신호다(설계 B). 형상 경유가 아니면 None.
    # TODO(④ graphrag 노드): 관측 모폴로지와 비교해 후보 랭킹 가점을 적용 — 아직 미구현.
    morphology: NotRequired[dict | None]
    scenario_hint: NotRequired[ScenarioHint | None]
    tier: Tier
    evidence_label: EvidenceLabel
    evidence: str | None
    fab_table: str | None
    direction: NotRequired[Literal["high", "low"] | None]
    occurrence_prior: NotRequired[str | None]
    rank: NotRequired[int | None]
    evidence_docs: NotRequired[int | None]
    evidence_chunks: NotRequired[int | None]
    unverifiable_signals: NotRequired[list[str] | None]
    sentence: str
    citations: NotRequired[list[Citation]]


class GraphRAGResult(TypedDict):
    pattern: str
    candidates: list[GraphRAGCandidate]


class EvidenceEntry(TypedDict):
    """④ Hypothesis 노드가 candidate 하나마다 채우는 evidence.

    구조화된 값(Critic이 실제로 비교)과 표시용 문자열(⑥ 응답생성 전용)을 분리한다.
    산출물_데이터모델설계.md §3.1 참고.

    2026-07-20 확장(API 명세 §2.7 "배치 실행 시 리치 보존 → 조회만" 원칙):
    요약값(bool/float)에 더해 근거 모달 3섹션이 그대로 쓸 원본 rows/series를 함께 보존한다.
    *_collected 플래그는 §2.7 available/reason 분기의 근거다(tier로 추정하지 않는다).
    """

    commonality_ratio: float | None
    drift_detected: bool | None
    maintenance_hit: bool | None
    maintenance_ts: str | None
    recipe_match: bool | None
    alarm_hit: bool | None
    defect_ts: str | None
    normal_ratio: float | None
    telemetry_summary: NotRequired[str]
    maintenance_summary: NotRequired[str]
    # --- §2.7 리치 보존 필드 ---
    commonality_rows: NotRequired[list[dict]]      # {equipment_id, chamber_id, matched_lots, total_lots, ratio, note}
    telemetry_collected: NotRequired[bool]         # query_telemetry 실호출 여부
    telemetry_param: NotRequired[str | None]
    telemetry_series: NotRequired[list[dict]]      # {ts, value}
    telemetry_normal_range: NotRequired[list[float] | None]
    events_collected: NotRequired[bool]            # get_maintenance_history 실호출 여부
    events_rows: NotRequired[list[dict]]           # {ts, type, equipment_id, kind?, code?, detail}


class Hypothesis(TypedDict):
    """④ Hypothesis 노드 출력. GraphRAGCandidate 1건 + 수집한 증거."""

    cause: str
    tier: Tier
    stage: str | None                        # candidate.step(KG ProcessStep 6종 또는 None) — API §2.5 stage
    equipment: str | None
    evidence: EvidenceEntry
    citations: NotRequired[list[Citation]]   # candidate.citations 그대로 옮김 — API §2.5/§2.7
    next_actions: NotRequired[list[str]]
    sentence: str                            # GraphRAGCandidate.sentence 그대로 옮김(근거)
    rationale: NotRequired[str]              # 에이전트가 쓴 판단 근거 (investigate_group 붙으면 채움)
    # verdict: ⑤가 reject_token으로 판정 → ⑥(response.py)이 verdict로 매핑(hypo_critic_py.md §13-1 C2).
    # 내부 3버킷 adopt/reject/judge_unknown = 프론트 accepted/rejected/insufficient.
    # judge_unknown = 근거없음(P5) + 반자동 미조사(SEMI_AUTO). ④는 이 필드를 직접 안 채운다.
    verdict: NotRequired[str]
    investigated: NotRequired[bool]          # investigate_group이 실제 조사(도구호출/unit판정 상속)했으면 True, 미조사 False → judge_unknown


class CriticResult(TypedDict):
    """⑤ Critic 노드 출력."""

    status: Literal["accepted", "insufficient_evidence"]
    accepted: list[Hypothesis]
    rejected: list[dict]


class FinalResponse(TypedDict):
    """⑥ 응답생성 노드 출력.

    2026-07-20 개편: hypotheses가 채택+비채택 전체를 "대표 accepted = index 0" 순서로
    담는다(각 원소에 hypothesis_id/verdict/verdict_reason 포함, API 명세 §2.5 정렬 불변식).
    status/reason/lot_ids/lot_count는 §2.2·§2.5 응답 조립의 원천이다.
    """

    group_id: str
    pattern: str
    status: Literal["reviewed", "insufficient", "unmapped"]
    reason: str | None
    lot_ids: list[str]
    lot_count: int
    hypotheses: list[dict]
    summary: str


class RCAState(TypedDict):
    """파이프라인 ⓪~⑥ 전체가 공유하는 상태 (LangGraph StateGraph의 state 타입).

    cursor_date/cursor_end — ⓪의 누적 스코프(직전 배치 이후 ~ 데이터축 최신일, API 명세
    §2.3). cursor_date "이후"(exclusive) cursor_end "까지"(inclusive) 구간을 처리한다.
    """

    cursor_date: str
    cursor_end: str
    target_lot_ids: list[str]
    vlm_results: list[VLMResult]
    groups: list[Group]
    graphrag_candidates: dict[str, GraphRAGResult]
    hypotheses: dict[str, list[Hypothesis]]
    critic_result: dict[str, CriticResult]
    final_response: dict[str, FinalResponse]
