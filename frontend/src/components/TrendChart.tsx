/** §2.8 일별 수율 추이 + 분석 이벤트 오버레이. days는 metric_series 전 구간(데이터축 날짜),
 *  events는 defect_date가 잡힌 분석(§2.7 저장분). 이벤트 마커는 해당 날짜의 라인 수율 위에
 *  얹는다(YieldEvent는 수율값을 안 실어줌 — day에서 조회). 벽시계 안 씀(§1). */

import type { YieldDaily } from "../api/types";
import { stageColor, TIER_LABELS } from "../labels";

const W = 1100,
  H = 230,
  L = 40,
  R = 12,
  T = 10,
  B = 30;
const IW = W - L - R;
const IH = H - T - B;

export default function TrendChart({ data }: { data: YieldDaily }) {
  const { days, events } = data;
  if (days.length === 0) {
    return (
      <div className="na-note">
        수율 추이 데이터가 없습니다 (fab.db 미빌드 시 비어 있음 — §2.8).
      </div>
    );
  }

  const times = days.map((d) => Date.parse(d.date));
  const t0 = Math.min(...times);
  const t1 = Math.max(...times);
  const x = (t: number) => L + (IW * (t - t0)) / Math.max(t1 - t0, 1);
  const y = (v: number) => T + IH * (1 - v / 100);

  const pts = days.map((d, i) => [x(times[i]), y(d.yield)] as const);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join("");
  const avg = days.reduce((s, d) => s + d.yield, 0) / days.length;

  // 날짜별 라인 수율 조회표 — 이벤트 마커를 라인 위에 얹기 위함.
  const yieldByDate = new Map(days.map((d) => [d.date, d.yield]));

  // 월 시작(1일)·중순(15일) 눈금 라벨.
  const monthTicks = days
    .filter((d) => d.date.endsWith("-01") || d.date.endsWith("-15"))
    .map((d) => ({ t: Date.parse(d.date), label: d.date.slice(5).replace("-", "/") }));

  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} className="chart-svg" preserveAspectRatio="none">
        {[0, 20, 40, 60, 80, 100].map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="#e4e6ea" />
            <text className="chart-ax" x={L - 6} y={y(v) + 4} textAnchor="end">
              {v}
            </text>
          </g>
        ))}
        {monthTicks.map((m) => (
          <text key={m.t} className="chart-ax" x={x(m.t)} y={H - 9} textAnchor="middle">
            {m.label}
          </text>
        ))}
        {/* 라인 평균 기준선 */}
        <line x1={L} x2={W - R} y1={y(avg)} y2={y(avg)} stroke="#9aa0a7" strokeDasharray="5 4" />
        <text className="chart-ax" x={W - R} y={y(avg) - 5} textAnchor="end">
          라인 평균 {avg.toFixed(1)}%
        </text>
        {/* 일별 수율 라인 */}
        <path d={line} fill="none" stroke="#2a78d6" strokeWidth={2} />
        {/* 이상 이벤트 마커 — 색은 공정 단계 */}
        {events.map((ev) => {
          const dy = yieldByDate.get(ev.date);
          if (dy === undefined) return null;
          return (
            <circle
              key={ev.analysis_id}
              cx={x(Date.parse(ev.date)).toFixed(1)}
              cy={y(dy).toFixed(1)}
              r={4}
              fill={stageColor(ev.stage)}
              stroke="#fff"
              strokeWidth={1.5}
            >
              <title>
                {ev.date} · {ev.pattern} · 수율 {dy}%
                {ev.cause ? `\n근본원인: ${ev.cause}` : ""}
                {ev.equipment ? `\n원인 장비: ${ev.equipment}` : ""}
                {ev.stage ? ` (${ev.stage})` : ""}
                {ev.tier ? `\n검증등급: ${TIER_LABELS[ev.tier] ?? ev.tier}` : ""}
              </title>
            </circle>
          );
        })}
      </svg>
      <div className="caption">
        실선: 일별 라인 평균 수율 · 마커: 분석 이벤트 {events.length}건(색 = 공정 단계, 마우스
        올리면 원인·장비) · 점선: 전 구간 평균 {avg.toFixed(1)}%
      </div>
    </>
  );
}
