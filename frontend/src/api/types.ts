/** API 계약 타입 — 정본 docs/API_명세서_v1.0.md. 키는 snake_case 그대로 쓴다(§1). */

export type Pattern = "Center" | "Edge-Ring" | "Scratch" | "Unknown" | "Normal";
export type AnalysisStatus = "reviewed" | "insufficient" | "unmapped";
export type BatchStatus = "running" | "completed" | "failed";
export type LogStatus = "done" | "running" | "error";
export type Tier = "auto" | "semi_auto" | "none";
export type Verdict = "accepted" | "rejected" | "insufficient";
export type Stage = "LITHO" | "ETCH" | "DEPO" | "CMP" | "CLEAN" | "EDS";
export type SeriesName = "low_yield_eq" | "line_avg";
export type UnavailableReason = "not_collected_for_tier" | "none_tier" | "no_data_found";

/** §1.1 — 422만 배열, 그 외 4xx/5xx는 문자열 */
export interface ValidationErrorItem {
  loc: (string | number)[];
  msg: string;
  type: string;
}
export type ErrorDetail = string | ValidationErrorItem[];

/** §2.1 */
export interface YieldSummary {
  series: { name: SeriesName; points: (number | null)[] }[];
}

/** §2.2 */
export interface AnalysisSummary {
  analysis_id: string;
  pattern: Pattern;
  lot_count: number;
  top_cause: string | null;
  status: AnalysisStatus;
}
export interface AnalysisList {
  count: number;
  items: AnalysisSummary[];
}

/** §2.3 */
export interface BatchAccepted {
  batch_id: string;
  status: "running";
}

/** §2.4 — 세 status 공통 7키 superset */
export interface BatchLogEntry {
  time: string; // HH:MM:SS (§1 ISO 규약의 명시적 예외)
  tool: string; // 열린 문자열 — 매핑에 없으면 raw id 그대로 표시
  message: string;
  status: LogStatus;
}
export interface Batch {
  batch_id: string;
  status: BatchStatus;
  current_step: number; // steps[]의 0-based 인덱스
  steps: string[]; // 고정 8키
  logs: BatchLogEntry[];
  result_ids: string[] | null;
  error: string | null;
}

/** §2.5 */
export interface Citation {
  id: number;
  text: string;
}
export interface Hypothesis {
  hypothesis_id: string;
  cause: string; // 열린 문자열
  stage: Stage | null;
  tier: Tier;
  verdict: Verdict;
  verdict_reason: string | null;
  narrative: string;
  next_actions: string[];
  citations: Citation[];
}
export interface Analysis {
  analysis_id: string;
  pattern: Pattern;
  description: string | null; // null이면 summary_line fallback (§3.2)
  status: AnalysisStatus;
  reason: string | null;
  lot_count: number;
  lot_ids: string[];
  hypotheses: Hypothesis[]; // 받은 순서 신뢰 — index 0이 대표(§2.5 정렬 불변식)
}

/** §2.6 */
export interface Wafer {
  wafer_id: string;
  defect_pattern: Pattern;
  die_map_url: string; // Base URL 없는 경로 — 프론트가 Base URL과 결합
}
export interface LotWafers {
  lot_id: string;
  wafer_count: number;
  defect_count: number;
  normal_count: number;
  wafers: Wafer[]; // wafer_id 정수 오름차순 — 재정렬 금지
}

/** §2.7 */
export interface CommonalityRow {
  equipment_id: string;
  chamber_id: string | null;
  matched_lots: number;
  total_lots: number;
  ratio: number; // 0~1 — 표시 % 변환은 프론트 몫
  note: string | null;
}
export interface CommonalitySection {
  available: boolean;
  reason?: UnavailableReason;
  rows: CommonalityRow[];
  normal_ratio: { value: number; caption: string } | null;
}
export interface TelemetrySection {
  available: boolean;
  reason?: UnavailableReason;
  series: { ts: string; value: number }[];
  param?: string;
  unit?: string;
  normal_range?: [number, number] | null;
  drift_detected?: boolean | null;
  t0?: string | null;
  caption?: string | null;
}
export interface EventRow {
  ts: string;
  type: "maintenance" | "alarm";
  equipment_id: string;
  kind?: "PM" | "BM";
  code?: string;
  detail: string;
}
export interface EventsSection {
  available: boolean;
  reason?: UnavailableReason;
  rows: EventRow[];
}
export interface Evidence {
  analysis_id: string;
  hypothesis_id: string;
  cause: string;
  stage: Stage | null;
  tier: Tier;
  verdict: Verdict;
  verdict_reason: string | null;
  suspect: { equipment_id: string; chamber_id: string | null } | null;
  sections: {
    commonality: CommonalitySection;
    telemetry: TelemetrySection;
    events: EventsSection;
  };
  unverified: { ref: string; reason: string }[];
  next_actions: string[];
  citations: Citation[];
  note: string | null;
}
