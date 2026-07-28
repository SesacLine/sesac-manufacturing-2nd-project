/** E2E 고정 응답 — `docs/API_명세서_v2.0.md` 스키마 그대로.
 *
 *  왜 목킹인가: 배치 1회는 실LLM(⑤ 에이전트·⑦ 번역) + fab.db + Neo4j를 다 요구하고 1~2분
 *  걸린다(백엔드가 `BATCH_E2E=1` opt-in으로 격리해 둔 것과 같은 이유). UI가 "받은 데이터를
 *  제대로 그리는가"는 그 비용 없이 검증할 수 있고, 그게 여기서 잡고 싶은 회귀다.
 *
 *  ⚠️ 이 파일은 목 데이터인 동시에 **계약 스냅샷**이다. 백엔드가 필드를 바꾸면 여기도 같이
 *  고쳐야 하고, 그때 테스트가 깨지는 것이 의도된 신호다. 값은 §2.5 정렬 불변식(index 0 =
 *  대표)과 상태 enum 5종을 일부러 모두 태운다 — 화면이 드문 상태에서 깨지는 걸 막으려면
 *  드문 상태가 픽스처에 있어야 한다.
 */

import type { Route } from "@playwright/test";

export const TODAY = {
  today: "2026-02-09",
  target_from: "2026-02-08",
  target_to: "2026-02-08",
  done: false,
  batch_id: null,
};

/** 대기열 — reviewed / novel / normal_reading을 한 번에 태운다.
 *  yield_impact가 null인 행(구 저장분)도 하나 둬 정렬·표시 폴백을 함께 본다.
 *
 *  ⚠️ 값 배치가 의도적이다 — **날짜 순서와 수율영향 순서를 일부러 어긋나게** 뒀다.
 *  둘이 같으면 "정렬이 실제로 동작하는지"와 "서버가 준 순서 그대로인지"를 구분할 수 없다.
 *  배열 순서 = 분석일 내림차순(서버 sort=latest와 정합)이고, 같은 배치에서 나온 두 행은
 *  analyzed_date가 같다(그 값은 배치 started_at에서 파생되므로 배치가 같으면 같다). */
export const ANALYSES = {
  count: 4,
  items: [
    {
      analysis_id: "grp_center_20260208_01",
      batch_id: "batch_20260208_01",
      analyzed_date: "2026-02-08",
      pattern: "Center",
      lot_count: 7,
      cohort_count: 2, // 분석 참조 로트 — 소속과 별개 층(§2.2)
      top_cause: "center_polishing_too_fast",
      status: "reviewed",
      confidence: "medium",
      yield_impact: -1.2, // 최신이지만 피해는 가장 작다
    },
    {
      analysis_id: "grp_unknown_20260208_01",
      batch_id: "batch_20260208_01",
      analyzed_date: "2026-02-08", // 위와 같은 배치 → 같은 날짜(정상)
      pattern: "Unknown",
      lot_count: 2,
      cohort_count: 0,
      top_cause: null,
      status: "novel",
      confidence: "low",
      yield_impact: -2.1,
    },
    {
      analysis_id: "grp_edgering_20260207_01",
      batch_id: "batch_20260207_01",
      analyzed_date: "2026-02-07",
      pattern: "Edge-Ring",
      lot_count: 3,
      cohort_count: 1,
      top_cause: "nonuniform_etch_process",
      status: "reviewed",
      confidence: "low",
      yield_impact: -3.4, // 가장 오래됐지만 피해는 가장 크다
    },
    {
      analysis_id: "grp_normal_20260205_01",
      batch_id: "batch_20260205_01",
      analyzed_date: "2026-02-05",
      pattern: "Normal",
      lot_count: 5,
      cohort_count: 0,
      top_cause: null,
      status: "normal_reading",
      confidence: "low",
      yield_impact: null,
    },
  ],
};

export const YIELD_DAILY = {
  days: [
    { date: "2026-02-05", yield: 92.1 },
    { date: "2026-02-06", yield: 91.4 },
    { date: "2026-02-07", yield: 88.2 },
    { date: "2026-02-08", yield: 80.6 },
  ],
  events: [
    {
      date: "2026-02-08",
      analysis_id: "grp_center_20260208_01",
      pattern: "Center",
      status: "reviewed",
      cause: "center_polishing_too_fast",
      equipment: "CMP-02",
      stage: "CMP",
      tier: "auto",
      confidence: "medium",
    },
  ],
};

export const CAUSE_STATS = {
  equipment: [{ equipment_id: "CMP-02", stage: "CMP", count: 2 }],
  causes: [
    { pattern: "Center", cause: "center_polishing_too_fast", stage: "CMP", tier: "auto", count: 2 },
  ],
  patterns: [
    { pattern: "Center", wafer_count: 132, mapped: true },
    { pattern: "Unknown", wafer_count: 41, mapped: false },
  ],
};

/** 채택 2건이 같은 cluster_id(묶음 렌더) + 단독 채택 1건 + 제외 4건.
 *  제외를 PREVIEW_LIMIT(3)보다 많이 둬야 "더 보기"가 실제로 나타난다. */
export const ANALYSIS_REVIEWED = {
  analysis_id: "grp_center_20260208_01",
  pattern: "Center",
  description: "중심부에 조밀한 불량 군집이 보이며, 가장자리로 갈수록 결함이 드물다.",
  status: "reviewed",
  reason: null,
  confidence: "medium",
  yield_impact: -3.4,
  actions: [
    { type: "containment", hold: true, text: "해당 로트 Hold 후 CMP-02 격리" },
    { type: "corrective", hold: false, text: "CMP-02 패드 교체 이력 점검" },
  ],
  lot_count: 2,
  lot_ids: ["lot00042", "lot00043"],
  // 분석 참조 로트(그룹 소속 아님) — "분석 참조 로트" 카드 렌더 재료.
  cohort_lot_ids: ["lot00031", "lot00028"],
  hypotheses: [
    {
      hypothesis_id: "h0",
      cause: "center_polishing_too_fast",
      stage: "CMP",
      tier: "auto",
      verdict: "accepted",
      verdict_reason: null,
      narrative:
        "Center 패턴 — 추정 원인: center polishing too fast (CMP 공정). 확인 방법: down_force 센서값이 정상범위를 벗어났는지 확인",
      next_actions: [],
      citations: [{ id: 1, text: "paper_liao_rag" }, { id: 2, text: "doc_D_cmp_troubleshooting" }],
      cluster_id: "cl_cmp_downforce",
      is_primary: true,
    },
    {
      hypothesis_id: "h1",
      cause: "center_polishing_too_slow",
      stage: "CMP",
      tier: "auto",
      verdict: "accepted",
      verdict_reason: null,
      narrative:
        "Center 패턴 — 추정 원인: center polishing too slow (CMP 공정). 확인 방법: down_force 센서값이 정상범위를 벗어났는지 확인",
      next_actions: [],
      citations: [{ id: 1, text: "table_sze_troubleshooting" }],
      cluster_id: "cl_cmp_downforce",
      is_primary: false,
    },
    {
      hypothesis_id: "h2",
      cause: "improper_maintenance",
      stage: "CMP",
      tier: "semi_auto",
      verdict: "accepted",
      verdict_reason: null,
      narrative: "Center 패턴 — 추정 원인: improper maintenance (CMP 공정). 확인 방법: 정비 이력 확인 (판정은 사람이)",
      next_actions: [],
      citations: [],
      cluster_id: null,
      is_primary: true,
    },
    ...["etch_rate_nonuniformity", "moisture_in_chamber", "worn_out_pad", "system_leaks"].map(
      (cause, i) => ({
        hypothesis_id: `h${3 + i}`,
        cause,
        stage: "ETCH",
        tier: "none" as const,
        verdict: "rejected" as const,
        verdict_reason: "시간 역전 — 정비 시점이 결함 확정일 이후",
        narrative: `Center 패턴 — 추정 원인: ${cause.replace(/_/g, " ")} (ETCH 공정). 확인 방법: 문헌 서술만 있어 설비 데이터로는 확인 불가`,
        next_actions: [],
        citations: [{ id: 1, text: "cause_center" }],
        cluster_id: null,
        is_primary: false,
      }),
    ),
  ],
};

/** 판단불가 카드 — hypotheses:[]이고 reason이 채워지는 경로(§2.5 필드 존재 계약). */
export const ANALYSIS_NOVEL = {
  analysis_id: "grp_unknown_20260208_01",
  pattern: "Unknown",
  description: null,
  status: "novel",
  reason: "학습된 5개 클래스에 속하지 않는 형상이라 원인 추정을 하지 않았습니다.",
  confidence: "low",
  yield_impact: -1.2,
  actions: [{ type: "investigation", hold: true, text: "로트 격리 후 전문가 재판독" }],
  lot_count: 1,
  lot_ids: ["lot00099"],
  // 후보 0건 그룹이라 ⑤가 돌지 않았다 → 참조 없음. "분석 참조 로트" 카드가 숨는 경로.
  cohort_lot_ids: [],
  hypotheses: [],
};

export const EVIDENCE = {
  analysis_id: "grp_center_20260208_01",
  hypothesis_id: "h0",
  cause: "center_polishing_too_fast",
  stage: "CMP",
  tier: "auto",
  verdict: "accepted",
  verdict_reason: null,
  suspect: { equipment_id: "CMP-02", chamber_id: null },
  sections: {
    commonality: {
      available: true,
      rows: [
        {
          equipment_id: "CMP-02",
          chamber_id: null,
          matched_lots: 7,
          total_lots: 7,
          ratio: 1.0,
          note: null,
        },
      ],
      normal_ratio: { value: 0.05, caption: "정상 로트 중 5%만 이 장비를 지났습니다." },
      cohort_note: "최근 7일 동일 패턴 2로트를 분석 참조로 함께 비교했습니다.",
    },
    telemetry: {
      available: true,
      param: "down_force",
      unit: "N",
      normal_range: [40, 60] as [number, number],
      drift_detected: true,
      t0: "2026-02-07T04:00:00Z",
      caption: "정상범위 상단을 넘어선 구간이 관측됩니다.",
      series: [
        { ts: "2026-02-06T00:00:00Z", value: 51 },
        { ts: "2026-02-07T00:00:00Z", value: 58 },
        { ts: "2026-02-08T00:00:00Z", value: 67 },
      ],
    },
    events: { available: false, reason: "no_data_found" as const, rows: [] },
  },
  unverified: [],
  next_actions: [],
  citations: [{ id: 1, text: "paper_liao_rag" }],
  note: null,
};

/** 모든 §2.5 계약 라우트를 고정 응답으로 덮는다.
 *
 *  와일드카드 하나로 처리하지 않고 경로별로 나눈 이유: 프론트가 **어떤 URL을 부르는지**까지
 *  고정하기 위해서다. 프론트가 엉뚱한 경로를 부르면 fulfill이 안 걸려 테스트가 실패한다 —
 *  이것도 잡고 싶은 회귀에 포함된다.
 */
export async function mockApi(page: import("@playwright/test").Page) {
  const json = (route: Route, body: unknown) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

  await page.route("**/api/v1/batches/today", (r) => json(r, TODAY));
  await page.route("**/api/v1/yield-daily", (r) => json(r, YIELD_DAILY));
  await page.route("**/api/v1/stats/causes", (r) => json(r, CAUSE_STATS));
  await page.route("**/api/v1/analyses?**", (r) => json(r, ANALYSES));
  await page.route("**/api/v1/analyses/grp_center_20260208_01", (r) =>
    json(r, ANALYSIS_REVIEWED),
  );
  await page.route("**/api/v1/analyses/grp_unknown_20260208_01", (r) => json(r, ANALYSIS_NOVEL));
  await page.route("**/api/v1/analyses/*/evidence/*", (r) => json(r, EVIDENCE));
}
