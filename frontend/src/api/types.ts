/** API 계약 타입 — 정본 docs/API_명세서_v2.0.md. 키는 snake_case 그대로 쓴다(§1). */

export type Pattern = "Center" | "Edge-Ring" | "Scratch" | "Unknown" | "Normal";
/** v1.1: novel = CNN Unknown(미지 패턴, OSR) — 구 unmapped에서 분리(판단불가 세분류 (b))
 *  normal_reading(#69) = 저수율인데 판독상 정상 — 그룹 서브그래프를 타지 않고 batch_runner가
 *  직접 만든 카드라 가설·근거가 없다(§2.5 evidence는 404). */
export type AnalysisStatus =
  | "reviewed"
  | "insufficient"
  | "unmapped"
  | "novel"
  | "normal_reading";
export type BatchStatus = "running" | "completed" | "failed";
export type LogStatus = "done" | "running" | "error";
export type Tier = "auto" | "semi_auto" | "none";
export type Verdict = "accepted" | "rejected" | "judge_unknown";
/** R1 확신 수준 — "high"(확정)는 없다. RCA 스코프는 "가설+근거"까지(§2.5 확장). */
export type Confidence = "medium" | "low";
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

/** §2.2 (v1.1: confidence·yield_impact 추가 — 대기열 확신 수준·수율영향 컬럼) */
export interface AnalysisSummary {
  analysis_id: string;
  /** 이 분석을 만든 배치 id — 대시보드가 "로그 확인" 링크를 거는 데 쓴다. */
  batch_id: string;
  pattern: Pattern;
  lot_count: number;
  top_cause: string | null;
  status: AnalysisStatus;
  confidence: Confidence; // 구 저장분은 서버가 "low" 폴백
  yield_impact: number | null; // %p (음수 = 라인 평균을 끌어내림). 구 저장분 null
  /** 분석 실행일(YYYY-MM-DD) — 그 분석을 만든 배치의 시작일. 결함 발생일이 아니다.
   *  배치 row가 없는 구 저장분은 null → 대기열에서 "—"로 표시. */
  analyzed_date: string | null;
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

/** §2.3 부속 — 서버가 인식하는 '오늘'과 이번 클릭의 대상 구간(화면1 배지·버튼 문구) */
export interface BatchToday {
  today: string; // YYYY-MM-DD, 커서에서 파생 — 배치 1회당 하루 전진
  target_from: string | null; // fab.db 없으면 null
  target_to: string | null;
  done: boolean; // true면 그 날짜 배치가 이미 완료(POST /batches는 409)
  batch_id: string | null; // done일 때 그 배치 id
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
  cluster_id?: string | null; // R2 원인군 묶기 — 같은 값 = fab 증거 동일한 원인군. 없으면 단독
  is_primary?: boolean; // R2 cause 대표 행
}
/** v1.1 권장 조치 — type 키는 서버 enum, 한국어 라벨은 ACTION_TYPE_LABELS(프론트 소유) */
export type ActionType = "containment" | "corrective" | "preventive" | "investigation";
export interface RecommendedAction {
  type: ActionType;
  hold: boolean; // true = 로트 Hold·격리 성격의 즉시 조치
  text: string;
}

export interface Analysis {
  analysis_id: string;
  pattern: Pattern;
  description: string | null; // null이면 summary_line fallback (§3.2)
  status: AnalysisStatus;
  reason: string | null;
  confidence: Confidence; // R1 확신 수준(불확실 표시) — 구 저장분 대비 서버가 "low" 폴백
  yield_impact: number | null; // v1.1 그룹 수율영향 %p (Nullable)
  actions: RecommendedAction[]; // v1.1 권장 조치 (구 저장분 [])
  lot_count: number;
  lot_ids: string[];
  hypotheses: Hypothesis[]; // 받은 순서 신뢰 — index 0이 대표(§2.5 정렬 불변식)
}

/** §2.8 v1.1 — 일별 수율 + 분석 이벤트 오버레이 */
export interface YieldDay {
  date: string;
  yield: number; // 0~100, 소수 1자리
}
export interface YieldEvent {
  date: string; // defect_date (데이터축 EDS 최종일)
  analysis_id: string;
  pattern: Pattern;
  status: AnalysisStatus;
  cause: string | null;
  equipment: string | null;
  stage: Stage | null;
  tier: Tier | null;
  confidence: Confidence;
}
export interface YieldDaily {
  days: YieldDay[];
  events: YieldEvent[];
}

/** §2.9 v1.1 — 장비 구성(도넛)·패턴 Pareto·패턴별 채택 원인 집계 */
export interface CauseStats {
  equipment: { equipment_id: string; stage: Stage | null; count: number }[];
  causes: { pattern: Pattern; cause: string; stage: Stage | null; tier: Tier | null; count: number }[];
  patterns: { pattern: Pattern; wafer_count: number; mapped: boolean }[];
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
