/** 시맨틱 키 → 한국어 표시 라벨. 서버는 키만 주고 라벨은 프론트 소유(§2.1·§2.2·§2.4).
 *  매핑에 없는 키는 raw id를 그대로 표시한다(열린 문자열 fallback — §2.4 "절대 하지 말 것"). */

import type {
  ActionType,
  AnalysisStatus,
  BatchStatus,
  Confidence,
  Pattern,
  SeriesName,
  Stage,
  Tier,
  UnavailableReason,
  Verdict,
} from "./api/types";

export const SERIES_LABELS: Record<SeriesName, string> = {
  low_yield_eq: "저수율 장비",
  line_avg: "라인 평균",
};

/** §2.4 steps[] 8키 ↔ 한국어 라벨 */
export const STEP_LABELS: Record<string, string> = {
  lot_selection: "저수율 로트 선별",
  cnn_classify: "CNN 분류",
  grouping: "자동 그룹화",
  vlm_describe: "VLM 서술",
  cause_lookup: "원인 후보 조회",
  hypothesis: "가설·증거 수집",
  critic: "검증",
  response_gen: "응답 생성",
};

/** §2.4 logs[].tool — MCP 8종 + 노드명. 없는 키는 raw 그대로. */
export const TOOL_LABELS: Record<string, string> = {
  get_wafer_map: "웨이퍼맵 조회",
  get_lot_history: "로트 이력 조회",
  run_commonality_analysis: "공통 장비 분석",
  get_normal_lot_ratio: "정상 로트 대조",
  query_telemetry: "텔레메트리 조회",
  get_alarm_history: "알람 이력 조회",
  get_maintenance_history: "정비 이력 조회",
  detect_change_points: "변화점 탐지",
  get_lot_timeline: "로트 타임라인",
  critic: "검증 노드",
  pipeline: "파이프라인",
};

export const STATUS_LABELS: Record<AnalysisStatus, string> = {
  reviewed: "검토완료",
  insufficient: "판단불가",
  unmapped: "미매핑",
  novel: "신규 패턴", // v1.1 — 미확인 신규 패턴(OSR), 격리·재판독 대상
};

/** 대기열 "유력 원인 후보" 셀 — reviewed 외 상태는 top_cause가 null이라 판단불가 사유로 대체.
 *  열린 lookup(Partial) — 신규 status가 타입에 추가돼도 빌드는 유지, 기본 "판단 불가"로 폴백. */
export const QUEUE_CAUSE_FALLBACK: Partial<Record<AnalysisStatus, string>> = {
  unmapped: "(a) 매핑 없음",
  novel: "(b) 신규 패턴·OSR",
  insufficient: "(c) 근거 부족·NFF",
};

/** 수율영향 색 등급 — −3%p 이하=고, −2%p 이하=중, 그 외=저. 프론트 표시 규칙(§3 파생,
 *  백엔드 severity 필드 아님). null(구 저장분)은 저로 표시. */
export function impactClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return "imp-lo";
  return v <= -3 ? "imp-hi" : v <= -2 ? "imp-md" : "imp-lo";
}

export const BATCH_STATUS_LABELS: Record<BatchStatus, string> = {
  running: "진행 중",
  completed: "완료",
  failed: "실패",
};

export const VERDICT_LABELS: Record<Verdict, string> = {
  accepted: "✔ 채택",
  rejected: "✖ 기각",
  judge_unknown: "△ 미판정",
};

export const TIER_LABELS: Record<Tier, string> = {
  auto: "[자동]",
  semi_auto: "[반자동]",
  none: "[근거없음]",
};

/** R1 확신 수준(불확실 표시). "확정"은 없음 — 단정하지 않는 것이 이 신호의 목적. */
export const CONFIDENCE_LABELS: Record<Confidence, string> = {
  medium: "잠정 지지",
  low: "불확실",
};

/** v1.1 권장 조치 type 라벨 — OCAP 취지의 3+1 분류(와이어프레임 v8) */
export const ACTION_TYPE_LABELS: Record<ActionType, string> = {
  containment: "① 격리 — 지금 확산 차단 (Containment)",
  corrective: "② 시정 — 원인 제거 (Corrective)",
  preventive: "③ 예방 — 재발 방지 (Preventive)",
  investigation: "추가 조사 (Investigation)",
};

export const REASON_LABELS: Record<UnavailableReason, string> = {
  not_collected_for_tier: "미수집 — 이 후보에서는 해당 도구를 호출하지 않았습니다",
  none_tier: "해당 없음 — 근거없음 등급(문헌 서술만)",
  no_data_found: "데이터 없음 — 도구는 호출했으나 해당 구간에 데이터가 없습니다",
};

/** §3.2 형상 gloss (비계약 — 프론트 소유 상수표) */
const PATTERN_GLOSS: Record<Pattern, string> = {
  Center: "중심부 집중 불량",
  "Edge-Ring": "가장자리 고리형 불량",
  Scratch: "선형 긁힘 불량",
  Unknown: "미지/새로운 결함 패턴",
  Normal: "결함 없음(정상)",
};

/** 차트 공정 단계 색 (도넛/Pareto/원인칩 공통) — 시각 규약(§2.9): 색 = 공정 단계.
 *  매핑에 없는 stage/null은 회색 fallback(CHART_NEUTRAL). */
export const STAGE_COLOR: Record<Stage, string> = {
  LITHO: "#8a56c2",
  ETCH: "#2a78d6",
  DEPO: "#1baf7a",
  CMP: "#eda100",
  CLEAN: "#4a3aa7",
  EDS: "#c2568a",
};
export const CHART_NEUTRAL = "#9aa0a7";
export function stageColor(stage: Stage | null | undefined): string {
  return stage ? (STAGE_COLOR[stage] ?? CHART_NEUTRAL) : CHART_NEUTRAL;
}

/** §3.2 공정 gloss */
const STAGE_GLOSS: Record<Stage, string> = {
  LITHO: "LITHO 공정 연관 추정",
  ETCH: "ETCH 공정 연관 추정",
  DEPO: "DEPO 공정 연관 추정",
  CMP: "CMP 공정 연관 추정",
  CLEAN: "CLEAN 공정 연관 추정",
  EDS: "EDS 공정 연관 추정",
};

/** §3.2 summary_line 조립 — description이 null일 때의 결정적 fallback.
 *  {형상 gloss(pattern)} — {공정 gloss(hypotheses[0].stage)} */
export function summaryLine(
  pattern: Pattern,
  status: AnalysisStatus,
  topStage: Stage | null | undefined,
): string {
  const shape = PATTERN_GLOSS[pattern] ?? pattern;
  let proc: string;
  if (status === "unmapped") proc = "원인 매핑 없음";
  else if (status === "insufficient") proc = "판단 불가";
  else if (topStage) proc = STAGE_GLOSS[topStage] ?? topStage;
  else proc = "공정 미상";
  return `${shape} — ${proc}`;
}
