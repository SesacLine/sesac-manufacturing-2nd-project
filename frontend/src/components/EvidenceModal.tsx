/** §2.7 근거 모달 3섹션 — available:false는 "미수집"으로 렌더(에러 아님),
 *  ratio·normal_ratio.value만 % 변환(caption은 완성 문장이라 그대로),
 *  telemetry 차트에 normal_range 밴드·t0 수직선. */

import { useEffect, useState } from "react";
import { api, ApiError, formatDetail } from "../api/client";
import type { Evidence, TelemetrySection } from "../api/types";
import { REASON_LABELS, TIER_LABELS, VERDICT_LABELS } from "../labels";

function TelemetryChart({ tel }: { tel: TelemetrySection }) {
  const W = 300;
  const H = 90;
  const series = tel.series;
  if (series.length === 0) return null;
  const values = series.map((p) => p.value);
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (tel.normal_range) {
    lo = Math.min(lo, tel.normal_range[0]);
    hi = Math.max(hi, tel.normal_range[1]);
  }
  const pad = (hi - lo || 1) * 0.1;
  lo -= pad;
  hi += pad;
  const x = (i: number) => (W * i) / Math.max(series.length - 1, 1);
  const y = (v: number) => H * (1 - (v - lo) / (hi - lo));
  const pts = series.map((p, i) => `${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const t0Index = tel.t0 ? series.findIndex((p) => p.ts >= tel.t0!) : -1;

  return (
    <div className="spark-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="90" preserveAspectRatio="none">
        {tel.normal_range && (
          <rect
            x={0}
            width={W}
            y={y(tel.normal_range[1])}
            height={Math.max(y(tel.normal_range[0]) - y(tel.normal_range[1]), 1)}
            fill="#eaf4ec"
          />
        )}
        {t0Index >= 0 && (
          <line x1={x(t0Index)} x2={x(t0Index)} y1={0} y2={H} stroke="#6b7178" strokeDasharray="3,3" />
        )}
        <polyline points={pts} fill="none" stroke="#1f2328" strokeWidth="2" />
      </svg>
      <div className="caption">
        {tel.t0 ? `점선 세로: 이상 시작 추정 t0(${tel.t0}) · ` : ""}
        {tel.normal_range ? `정상범위 [${tel.normal_range[0]}, ${tel.normal_range[1]}] ` : ""}
        {tel.caption ?? ""}
      </div>
    </div>
  );
}

export default function EvidenceModal({
  analysisId,
  hypothesisId,
  cause,
  onClose,
}: {
  analysisId: string;
  hypothesisId: string;
  cause: string;
  onClose: () => void;
}) {
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .evidence(analysisId, hypothesisId)
      .then(setEvidence)
      .catch((e: ApiError) => setError(formatDetail(e.detail)));
  }, [analysisId, hypothesisId]);

  const sections = evidence?.sections;
  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-head">
          <span>근거 상세 — {cause}</span>
          <button className="close-btn" onClick={onClose}>
            ✕ 닫기
          </button>
        </div>
        <div className="modal-body">
          {error && <div className="notice error">{error}</div>}
          {!error && !evidence && <div className="na-note">불러오는 중...</div>}
          {evidence && sections && (
            <>
              <div className="caption" style={{ marginBottom: 10 }}>
                판정: {VERDICT_LABELS[evidence.verdict] ?? evidence.verdict} ·{" "}
                {TIER_LABELS[evidence.tier] ?? evidence.tier}
                {evidence.suspect &&
                  ` · 용의 장비: ${evidence.suspect.equipment_id}${evidence.suspect.chamber_id ? ` (${evidence.suspect.chamber_id})` : ""}`}
                {evidence.verdict_reason && ` · ${evidence.verdict_reason}`}
              </div>

              <div className="ev-sec">
                <div className="ev-sec-title">
                  <span className="num">①</span>Commonality — 공통 장비 집계
                </div>
                <div className="ev-sec-body">
                  {sections.commonality.available ? (
                    <>
                      <table>
                        <thead>
                          <tr>
                            <th>장비 (챔버)</th>
                            <th>불량 Lot 통과</th>
                            <th>일치율</th>
                            <th>비고</th>
                          </tr>
                        </thead>
                        <tbody>
                          {sections.commonality.rows.map((r, i) => (
                            <tr key={i}>
                              <td>
                                {r.equipment_id}
                                {r.chamber_id ? ` (${r.chamber_id})` : ""}
                                {evidence.suspect?.equipment_id === r.equipment_id && " ★"}
                              </td>
                              <td>
                                {r.matched_lots} / {r.total_lots}
                              </td>
                              {/* ratio는 0~1 원값 — 표시 % 변환은 프론트 몫(§1) */}
                              <td>{Math.round(r.ratio * 100)}%</td>
                              <td>{r.note ?? "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {sections.commonality.normal_ratio && (
                        <div className="caption">
                          반대 증거: {sections.commonality.normal_ratio.caption}
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="na-note">
                      {REASON_LABELS[sections.commonality.reason ?? "no_data_found"] ??
                        sections.commonality.reason}
                    </div>
                  )}
                </div>
              </div>

              <div className="ev-sec">
                <div className="ev-sec-title">
                  <span className="num">②</span>Telemetry — 파라미터 시계열 vs 정상범위
                </div>
                <div className="ev-sec-body">
                  {sections.telemetry.available ? (
                    <>
                      <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 6 }}>
                        {evidence.suspect?.equipment_id} · {sections.telemetry.param}
                        {sections.telemetry.unit ? ` (${sections.telemetry.unit})` : ""}
                        {sections.telemetry.drift_detected != null &&
                          (sections.telemetry.drift_detected ? " · 정상범위 이탈 감지" : " · 이탈 미감지")}
                      </div>
                      <TelemetryChart tel={sections.telemetry} />
                    </>
                  ) : (
                    <div className="na-note">
                      {REASON_LABELS[sections.telemetry.reason ?? "no_data_found"] ??
                        sections.telemetry.reason}
                    </div>
                  )}
                </div>
              </div>

              <div className="ev-sec">
                <div className="ev-sec-title">
                  <span className="num">③</span>Alarm · Maintenance 이력
                </div>
                <div className="ev-sec-body">
                  {sections.events.available ? (
                    <table>
                      <thead>
                        <tr>
                          <th>시각</th>
                          <th>구분</th>
                          <th>Equipment</th>
                          <th>내용</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sections.events.rows.map((r, i) => (
                          <tr key={i}>
                            <td>{r.ts}</td>
                            <td>
                              {r.type === "maintenance" ? `정비${r.kind ? ` (${r.kind})` : ""}` : `알람${r.code ? ` ${r.code}` : ""}`}
                            </td>
                            <td>{r.equipment_id}</td>
                            <td>{r.detail}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <div className="na-note">
                      {REASON_LABELS[sections.events.reason ?? "no_data_found"] ??
                        sections.events.reason}
                    </div>
                  )}
                </div>
              </div>

              {evidence.unverified.length > 0 && (
                <div className="caption" style={{ marginTop: 10 }}>
                  검증 제외 인용:{" "}
                  {evidence.unverified.map((u) => `${u.ref} (${u.reason})`).join(" · ")}
                </div>
              )}
              {evidence.note && <div className="notice">{evidence.note}</div>}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
