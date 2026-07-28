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

/** §2.4 steps[] 8키 ↔ 한국어 라벨.
 *  모델 이름(CNN·VLM)이 아니라 **그 단계가 하는 일**로 쓴다 — 화면을 보는 사람은 어떤 모델이
 *  도는지가 아니라 지금 무슨 작업이 진행 중인지를 알고 싶어 한다. */
export const STEP_LABELS: Record<string, string> = {
  lot_selection: "저수율 로트 선별",
  cnn_classify: "결함 패턴 판독",
  grouping: "패턴별 자동 그룹화",
  vlm_describe: "결함 형상 서술",
  cause_lookup: "원인 후보 조회",
  hypothesis: "증거 수집·대조",
  critic: "근거 검증",
  response_gen: "결과 정리",
};

/** §2.4 logs[].tool — 설비 데이터 조회 도구 8종 + 노드명. 없는 키는 raw 그대로. */
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

/** 상태 라벨 — 와이어프레임 v9 문구. 화면3 헤더처럼 "이 카드가 무엇인지"를 말해야 하는
 *  자리에서는 4종을 구분해 쓴다(대기열 배지는 아래 QUEUE_STATUS_PILL이 2종으로 접는다). */
export const STATUS_LABELS: Record<AnalysisStatus, string> = {
  reviewed: "✓ 검토 완료",
  insufficient: "⚠ 판단 불가",
  unmapped: "⚠ 판단 불가 — 매핑 없음",
  novel: "⚠ 판단 불가 — 신규 패턴",
  normal_reading: "판독상 정상", // #69 — 저수율이지만 웨이퍼맵은 정상, 조치 대상 아님
};

/** 대기열 상태 배지 — v9는 상태 열을 **"조치가 필요한가"** 로만 쓴다(✓ 검토 완료 / ⚠ 판단 불가).
 *  왜 4종을 2종으로 접나: 판단불가의 **세부 사유는 바로 옆 "유력 원인 후보" 열이 (a)/(b)/(c)로
 *  이미 말해준다. 배지까지 4종이면 한 행에서 같은 정보를 두 번 읽게 된다.
 *  cls는 v9의 status-pill 변형 — ok=무채색(조용히), na=주의색(조치 필요), mute=대상 아님. */
export const QUEUE_STATUS_PILL: Record<AnalysisStatus, { text: string; cls: string }> = {
  reviewed: { text: "✓ 검토 완료", cls: "ok" },
  insufficient: { text: "⚠ 판단 불가", cls: "na" },
  unmapped: { text: "⚠ 판단 불가", cls: "na" },
  novel: { text: "⚠ 판단 불가", cls: "na" },
  normal_reading: { text: "판독상 정상", cls: "mute" },
};

/** 대기열 "유력 원인 후보" 셀 — reviewed 외 상태는 top_cause가 null이라 사유 문구로 대체.
 *
 *  ⚠️ 문구는 **엔지니어가 읽는 말**로만 쓴다. 예전 값 `(a) 매핑 없음` / `(b) 신규 패턴·OSR` /
 *  `(c) 근거 부족·NFF`는 우리 내부 분류표(a/b/c)와 약어(OSR=open-set recognition,
 *  NFF=no fault found)를 그대로 노출한 것이라 화면에서는 뜻이 안 통했다. 지금은 각 칸이
 *  **"그래서 지금 뭘 해야 하나"** 를 스스로 말하게 한다 — 내부 분류 이름은 코드 키(status)에만 남긴다.
 *
 *  열린 lookup(Partial) — 신규 status가 타입에 추가돼도 빌드는 유지, 기본 "원인 미확정"으로 폴백. */
export const QUEUE_CAUSE_FALLBACK: Partial<Record<AnalysisStatus, string>> = {
  unmapped: "등록된 원인 정보 없음 — 판독 결과만 제공",
  novel: "처음 보는 결함 형태 — 전문가 재판독 필요",
  insufficient: "근거 부족 — 원인 확정 못 함",
  normal_reading: "결함 패턴 없음 — 수율 원인 별도 확인",
};

/** 원인(cause) 한국어 gloss — §3.2 계열의 **프론트 소유 표시값**(비계약).
 *
 *  cause는 KG가 문헌에서 자유 추출한 **열린 문자열**이라 서버 enum이 아니다(지금 산출물 기준
 *  검증 가능 등급만 166종, 재빌드마다 바뀐다). 그래서 전수 번역은 애초에 불가능하고,
 *  **실제로 채택돼 화면에 뜨는 것**을 중심으로 덮되 나머지는 아래 causeLabel()이 읽을 수 있는
 *  형태로 낮춰 준다. 키를 못 찾는 건 버그가 아니라 설계된 경로다.
 *
 *  번역 원칙: 장비·공정 약어(CMP·ETCH·RF·MFC·슬러리)는 현장 표기 그대로 두고 서술만 한국어로.
 *  원문 id는 화면에서 tooltip으로 계속 보이게 한다(KG·평가 대조 시 원문이 있어야 추적된다). */
export const CAUSE_LABELS: Record<string, string> = {
  // CMP
  center_polishing_too_fast: "중심부 연마 과다(CMP)",
  center_polishing_too_slow: "중심부 연마 부족(CMP)",
  inadequate_or_uneven_cmp: "CMP 연마 불균일",
  cmp_polish_nonuniformity: "CMP 연마 불균일",
  cmp_edge_overpolish: "가장자리 과연마(CMP)",
  excessive_down_force: "과도한 하중(down force)",
  worn_out_pad: "패드 마모",
  low_slurry_flow: "슬러리 유량 부족",
  low_polish_rate_material_erosion: "연마율 저하·재료 침식",
  slurry_particle_agglomeration: "슬러리 입자 응집",
  defective_slurry_from_supplier: "슬러리 자재 불량(공급처)",
  slurry_dried_on_dispenser_sidewall: "디스펜서 벽면 슬러리 건조·고착",
  residual_slurry_in_deep_features: "깊은 패턴부 슬러리 잔류",
  mechanical_abrasion_during_polishing: "연마 중 기계적 마모",
  // ETCH
  nonuniform_etch_process: "식각 불균일(ETCH)",
  etch_rate_nonuniformity: "식각률 불균일",
  etching_non_uniformities: "식각 불균일",
  etch_nonuniformity: "식각 불균일",
  rf_power_drift: "RF 파워 드리프트",
  residual_sidewall_passivants: "측벽 패시베이션 잔류물",
  high_thermal_load_at_esc: "ESC 열부하 과다",
  chamber_pressure_deviation: "챔버 압력 이탈",
  system_pressure_too_high_or_low: "시스템 압력 이탈(과고·과저)",
  // DEPO / 확산·산화
  deposition_center_thickness: "중심부 증착 두께 편차",
  incorrect_gas_flow_into_furnace_tube: "퍼니스 튜브 가스 유량 이상",
  improper_gas_flow: "가스 유량 부적정",
  incorrect_process_gas_flow: "공정 가스 유량 이상",
  gas_flow_imbalance: "가스 유량 불균형",
  malfunctioning_mfc: "MFC(유량제어기) 오작동",
  malfunctioning_heating_system: "가열 계통 오작동",
  incorrect_temperature_control: "온도 제어 이상",
  incorrect_temperature_measurement_sensor_operation: "온도 센서 측정 이상",
  incorrect_operation_of_thermocouples: "열전대(thermocouple) 동작 이상",
  decrease_in_substrate_temperature: "기판 온도 저하",
  susceptor_temperature_drift: "서셉터 온도 드리프트",
  increase_in_deposition_rate: "증착률 상승",
  high_film_stress: "박막 응력 과다",
  excessive_stress: "응력 과다",
  stress: "응력",
  excessive_seed_layer_thickness: "시드층 두께 과다",
  excessive_seed_layer_thickness_on_wafer_surface: "웨이퍼 표면 시드층 두께 과다",
  particles_formed_after_deposition: "증착 후 파티클 생성",
  particles_on_surface_of_film: "박막 표면 파티클",
  moisture_in_chamber: "챔버 내 수분",
  system_leaks: "시스템 누설(leak)",
  outgassing: "아웃가싱",
  wafer_broken_inside_furnace: "퍼니스 내 웨이퍼 파손",
  incorrect_h2_o2_ratio_for_steam_process_o2_starved: "스팀 공정 H2/O2 비율 이상(O2 부족)",
  // CLEAN / 오염
  clean_nozzle_clog: "세정 노즐 막힘",
  excessive_megasonic_energy: "메가소닉 에너지 과다",
  excessive_megasonic_power: "메가소닉 파워 과다",
  h2o2_depletion_in_aged_sc_1_bath: "노후 SC-1 배스 H2O2 고갈",
  chemical_bath_temperature_drift: "케미컬 배스 온도 드리프트",
  low_chemical_flow_rate: "케미컬 유량 부족",
  insufficient_rinse_time: "린스 시간 부족",
  incomplete_drying: "건조 불완전",
  contaminated_preoxidation_clean: "산화 전 세정 오염",
  preoxidation_clean_steps: "산화 전 세정 단계 문제",
  exposure_to_di_water_containing_dissolved_oxygen: "용존산소 함유 DI수 노출",
  si_exposure_to_air: "실리콘 표면 대기 노출",
  chemical_contamination: "케미컬 오염",
  contamination_in_processing_conditions: "공정 조건 오염",
  alkali_metal_and_other_metal_impurities: "알칼리 금속 등 금속 불순물",
  gas_supply_contamination: "공급 가스 오염",
  incoming_gas_line_contamination: "인입 가스 라인 오염",
  contaminated_gas_filter_or_line: "가스 필터·배관 오염",
  gas_piping_reaction: "가스 배관 내 반응 생성물",
  contaminated_quartzware: "쿼츠웨어 오염",
  contaminated_carrier: "캐리어 오염",
  chamber_cleanliness: "챔버 청정도 저하",
  defective_filter: "필터 불량",
  airborne_aerosols_in_fab_air: "팹 대기 중 에어로졸",
  human_generated_particles: "작업자 유래 파티클",
  production_equipment_particle_source: "생산 장비 발 파티클",
  triboelectric_charging: "마찰 대전(정전기)",
  insulating_films_on_wafer: "웨이퍼 절연막 대전",
  bacteria_lubricants_vapors_detergents_solvents_moisture: "미생물·윤활유·용제·수분 등 복합 오염",
  particle_type_defects_cause: "파티클성 결함",
  // LITHO
  reticle_problem: "레티클 불량",
  wafer_or_reticle_stage_error: "웨이퍼·레티클 스테이지 오차",
  incorrect_alignment_system_measurement_of_reticle_and_wafer_alignment_marks:
    "정렬 마크 계측 오차(얼라인먼트)",
  overdeveloped_or_overexposed_positive_resist: "레지스트 과현상·과노광",
  overdeveloped_or_overexposed_positive_resist_across_entire_wafer: "웨이퍼 전면 레지스트 과현상·과노광",
  underdeveloped_or_underexposed_positive_resist: "레지스트 현상·노광 부족",
  underdeveloped_or_underexposed_positive_resist_across_entire_wafer: "웨이퍼 전면 레지스트 현상·노광 부족",
  resist_residue_remaining_on_wafer_after_develop: "현상 후 레지스트 잔막",
  improper_spin_coater_tool_setup: "스핀 코터 설정 부적정",
  misting_or_backsplashing_from_dispenser: "디스펜서 미스팅·튐",
  improper_setup_of_different_tools_used_in_track_for_processing_wafers: "트랙 장비 간 설정 불일치",
  incorrect_process_recipes_during_exposure_or_develop_steps: "노광·현상 레시피 오류",
  no_measurable_cds: "CD 측정 불가",
  // 설비 운영·핸들링 (공정 무관)
  improper_maintenance: "정비 부적정",
  incorrect_process_recipe: "공정 레시피 오류",
  wrong_process_recipe_for_product: "제품과 다른 레시피 적용",
  system_power_needs_adjustment: "설비 파워 조정 필요",
  wafer_handling: "웨이퍼 핸들링",
  handling_mechanical: "기계적 핸들링 손상",
  machine_handling_problems: "장비 핸들링 문제",
  improperly_applied_inspection_arm: "검사 암(arm) 접촉 불량",
  asymmetric_edge_handling: "가장자리 비대칭 핸들링",
  hard_particle_trapped_under_it: "경질 파티클 끼임",
  friction_particle_rumping_in_input_slurry: "투입 슬러리 내 마찰 파티클",
  tantalum_diffusion_barrier: "탄탈럼 확산 방지막 문제",
};

/** 대기열·카드에 찍을 원인 표시 문자열.
 *  gloss가 있으면 한국어, 없으면 snake_case를 최소한 **읽히는 형태**로 바꿔 준다
 *  (`etch_rate_drift` → `Etch rate drift`). 원문 id는 호출부가 title 속성으로 함께 단다. */
export function causeLabel(cause: string): string {
  const hit = CAUSE_LABELS[cause];
  if (hit) return hit;
  const spaced = cause.replace(/_/g, " ").trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : cause;
}

/** 인용 출처(citation) 라벨 — KG가 적재한 원천 문헌 id → 사람이 읽는 출처명.
 *
 *  카드에는 `[1] cause_center` 처럼 **파일 id가 그대로** 찍히고 있었는데, 이건 우리가 KG를
 *  적재할 때 붙인 내부 파일명이라 화면에서는 아무 뜻도 전달하지 못했다. 무엇을 근거로 삼았는지
 *  (논문인지, 공정별 트러블슈팅 가이드인지, 패턴 원인 발췌인지)가 보여야 근거로서 기능한다.
 *  원천은 `kg_rca/data/raw/`(문헌 5편)와 `kg_rca/data/docs/`(doc_A~H) 두 곳이다. */
export const CITATION_LABELS: Record<string, string> = {
  cause_center: "Center 패턴 원인 문헌 발췌",
  cause_edgering: "Edge-Ring 패턴 원인 문헌 발췌",
  cause_scratch: "Scratch 패턴 원인 문헌 발췌",
  paper_liao_rag: "Liao 외(2026) — 웨이퍼 결함 의미추론 논문",
  paper_edgering_cmp: "Xie & Boning(2005, MIT) — 웨이퍼 엣지 CMP 논문",
  table_ref56_patterns: "Shin 외(2025) — 웨이퍼 결함 패턴·원인 표",
  table_sze_troubleshooting: "반도체 전공정 5단계 트러블슈팅표",
  doc_A_wafermap_patterns: "웨이퍼맵 패턴–공정 연관 노트",
  doc_B_etch_troubleshooting: "ETCH 트러블슈팅 가이드",
  doc_C_depo_troubleshooting: "DEPO 트러블슈팅 가이드",
  doc_D_cmp_troubleshooting: "CMP 트러블슈팅 가이드",
  doc_E_litho_troubleshooting: "LITHO 트러블슈팅 가이드",
  doc_F_clean_troubleshooting: "CLEAN 트러블슈팅 가이드",
  doc_G_eds_troubleshooting: "EDS 트러블슈팅 가이드",
  doc_H_spatial_morphology_heuristics: "웨이퍼맵 형상 판독 현장 노트",
};

/** 인용 출처 표시명. 모르는 id는 causeLabel과 같은 관례로 읽히게만 낮춘다. */
export function citationLabel(text: string): string {
  return CITATION_LABELS[text] ?? text.replace(/_/g, " ");
}

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
  rejected: "✖ 제외",
  judge_unknown: "판단 보류",
};

/** KG 검증등급(기획안 §6.2) — 대괄호 코드값 대신 **그 등급이 뜻하는 확인 방법**으로 쓴다.
 *  `[자동]`은 우리 내부 표기라 화면에서 뜻이 안 통했다. 등급 자체는 팀 공용 어휘이므로
 *  개념은 유지하고 표현만 바꾼다. */
export const TIER_LABELS: Record<Tier, string> = {
  auto: "센서값 자동 검증",
  semi_auto: "정비·레시피 이력 확인",
  none: "문헌 근거만",
};

/** R1 확신 수준(불확실 표시). "확정"은 없음 — 단정하지 않는 것이 이 신호의 목적.
 *
 *  ⚠ 지금 **어디서도 렌더하지 않는다**(화면1 대기열 "확신 수준" 열을 뺐다). 백엔드
 *  `_confidence()`가 채택 "클러스터"가 아니라 행 수를 세는 탓에 사실상 상수 "low"라,
 *  전 행이 "불확실"로 같아 열의 정보량이 0이었기 때문. 응답 필드(§2.2/§2.5)와 store
 *  컬럼은 그대로 살아 있으므로 로직을 고치면 이 어휘로 열만 되살리면 된다 — 그때 다시
 *  쓰라고 남겨 둔 것이니 "미사용"이라고 지우지 말 것.
 *  (화면3 ResultPage의 "확정 아님" 배너는 이 맵을 쓰지 않고 confidence로 톤만 가른다.) */
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

/** 근거 섹션이 비어 있는 이유 — "도구 호출" 같은 내부 동작이 아니라 **왜 볼 게 없는지**로 쓴다.
 *  셋 다 오류가 아니라 정상 상태라는 점이 문구에서 드러나야 한다. */
export const REASON_LABELS: Record<UnavailableReason, string> = {
  not_collected_for_tier: "이 원인은 센서값으로 확인하는 유형이 아니라 조회하지 않았습니다",
  none_tier: "문헌 근거만 있는 원인이라 설비 데이터로는 확인할 수 없습니다",
  no_data_found: "해당 기간에 남아 있는 데이터가 없습니다",
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
  if (status === "unmapped") proc = "등록된 원인 정보 없음";
  else if (status === "insufficient") proc = "원인 확정 못 함";
  else if (status === "novel") proc = "처음 보는 결함 형태";
  else if (status === "normal_reading") proc = "결함 패턴 없음";
  else if (topStage) proc = STAGE_GLOSS[topStage] ?? topStage;
  else proc = "공정 미상";
  return `${shape} — ${proc}`;
}
