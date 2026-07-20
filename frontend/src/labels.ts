/** 시맨틱 키 → 한국어 표시 라벨. 서버는 키만 주고 라벨은 프론트 소유(§2.1·§2.2·§2.4).
 *  매핑에 없는 키는 raw id를 그대로 표시한다(열린 문자열 fallback — §2.4 "절대 하지 말 것"). */

import type {
  AnalysisStatus,
  BatchStatus,
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
};

export const BATCH_STATUS_LABELS: Record<BatchStatus, string> = {
  running: "진행 중",
  completed: "완료",
  failed: "실패",
};

export const VERDICT_LABELS: Record<Verdict, string> = {
  accepted: "✔ 채택",
  rejected: "✖ 기각",
  insufficient: "△ 근거부족",
};

export const TIER_LABELS: Record<Tier, string> = {
  auto: "[자동]",
  semi_auto: "[반자동]",
  none: "[근거없음]",
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
