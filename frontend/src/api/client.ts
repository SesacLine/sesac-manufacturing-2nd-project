/** fetch 래퍼 — Base URL 주입, 에러 detail(문자열/배열) 분기(§1.1). */

import type {
  Analysis,
  AnalysisList,
  Batch,
  BatchAccepted,
  BatchToday,
  CauseStats,
  ErrorDetail,
  Evidence,
  LotWafers,
  YieldDaily,
  YieldSummary,
} from "./types";

/** Base URL: 빌드타임 env(VITE_API_BASE_URL)로 주입, 기본은 §1 값. */
export const API_BASE: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  "http://localhost:8000/api/v1";

export class ApiError extends Error {
  status: number;
  detail: ErrorDetail;
  constructor(status: number, detail: ErrorDetail) {
    super(formatDetail(detail));
    this.status = status;
    this.detail = detail;
  }
}

/** §1.1 — 422만 배열(loc/msg 조합), 그 외는 문자열 그대로. 무조건 문자열 렌더 금지. */
export function formatDetail(detail: ErrorDetail): string {
  if (Array.isArray(detail)) {
    return detail.map((d) => `${d.loc.join(".")}: ${d.msg}`).join(" / ");
  }
  return String(detail);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError(0, "서버에 연결할 수 없습니다. 백엔드가 실행 중인지 확인하세요.");
  }
  if (!res.ok) {
    let detail: ErrorDetail = res.statusText;
    try {
      const body = await res.json();
      if (body && body.detail !== undefined) detail = body.detail;
    } catch {
      /* JSON 아님 — statusText 유지 */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  yieldSummary: () => request<YieldSummary>("/yield-summary"),
  /** §2.8 v1.1 — 일별 수율 전 구간 + 분석 이벤트 오버레이 (대시보드 추이 차트) */
  yieldDaily: () => request<YieldDaily>("/yield-daily"),
  /** §2.9 v1.1 — 장비 구성·패턴 Pareto·채택 원인 집계 (도넛/막대/칩) */
  causeStats: () => request<CauseStats>("/stats/causes"),
  analyses: (sort: "latest" | "oldest", limit: number, offset: number) =>
    request<AnalysisList>(`/analyses?sort=${sort}&limit=${limit}&offset=${offset}`),
  analysis: (analysisId: string) =>
    request<Analysis>(`/analyses/${encodeURIComponent(analysisId)}`),
  evidence: (analysisId: string, hypothesisId: string) =>
    request<Evidence>(
      `/analyses/${encodeURIComponent(analysisId)}/evidence/${encodeURIComponent(hypothesisId)}`,
    ),
  runBatch: () =>
    request<BatchAccepted>("/batches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    }),
  batch: (batchId: string) => request<Batch>(`/batches/${encodeURIComponent(batchId)}`),
  /** 서버 '오늘' + 이번 클릭의 대상 구간 — 화면1 배지가 배치 날짜를 그대로 찍는 데 쓴다. */
  batchToday: () => request<BatchToday>("/batches/today"),
  /** 시연용 — 마지막 배치를 되돌린다(분석 삭제 + 커서 복원). 같은 날짜를 다시 돌릴 수 있게. */
  resetLastBatch: () =>
    request<{ batch_id: string; removed_analyses: number; cursor_restored_to: string | null }>(
      "/batches/reset",
      { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
    ),
  lotWafers: (lotId: string) =>
    request<LotWafers>(`/lots/${encodeURIComponent(lotId)}/wafers`),
  /** §2.6 die_map_url(Base URL 없는 경로) → 절대 URL. 값에 /api/v1이 없으므로 여기서만 결합. */
  dieMapUrl: (dieMapPath: string) => `${API_BASE}${dieMapPath}`,
};
