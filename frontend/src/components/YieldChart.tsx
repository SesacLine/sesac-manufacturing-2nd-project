/** §2.1 수율 추이 차트 — series[].name 키 매칭(인덱스 금지), points null은 선 끊김,
 *  길이는 points.length 기준(상수 7 하드코딩 금지), ×100 재적용 금지(서버가 이미 적용). */

import type { YieldSummary } from "../api/types";
import { SERIES_LABELS } from "../labels";

const W = 1100;
const H = 150;
const PAD = { l: 34, r: 12, t: 10, b: 8 };

const STYLE_BY_NAME: Record<string, { stroke: string; dash?: string }> = {
  low_yield_eq: { stroke: "#1f2328" },
  line_avg: { stroke: "#9aa0a7", dash: "5,4" },
};

function segments(points: (number | null)[]): string[] {
  // null 지점에서 선을 끊는다 — 보간하지 않음(§2.1 gap 처리).
  const n = points.length;
  if (n === 0) return [];
  const x = (i: number) => PAD.l + ((W - PAD.l - PAD.r) * i) / Math.max(n - 1, 1);
  const y = (v: number) => PAD.t + (H - PAD.t - PAD.b) * (1 - v / 100);
  const paths: string[] = [];
  let current: string[] = [];
  points.forEach((v, i) => {
    if (v === null || v === undefined) {
      if (current.length > 1) paths.push(current.join(" "));
      current = [];
    } else {
      current.push(`${x(i).toFixed(1)},${y(v).toFixed(1)}`);
    }
  });
  if (current.length > 1) paths.push(current.join(" "));
  return paths;
}

export default function YieldChart({ data }: { data: YieldSummary }) {
  if (data.series.length === 0) {
    return <div className="na-note">수율 데이터가 없습니다.</div>;
  }
  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none">
        {[0, 25, 50, 75, 100].map((v) => {
          const y = PAD.t + (H - PAD.t - PAD.b) * (1 - v / 100);
          return (
            <g key={v}>
              <line x1={PAD.l} x2={W - PAD.r} y1={y} y2={y} stroke="#e4e6ea" />
              <text x={PAD.l - 5} y={y + 3.5} textAnchor="end" fontSize="10" fill="#6b7178">
                {v}
              </text>
            </g>
          );
        })}
        {data.series.map((s) => {
          const style = STYLE_BY_NAME[s.name] ?? { stroke: "#1f2328" };
          return segments(s.points).map((pts, i) => (
            <polyline
              key={`${s.name}-${i}`}
              points={pts}
              fill="none"
              stroke={style.stroke}
              strokeWidth={s.name === "low_yield_eq" ? 2 : 1.5}
              strokeDasharray={style.dash}
            />
          ));
        })}
      </svg>
      <div className="caption">
        {data.series
          .map((s) => `${s.name === "line_avg" ? "점선" : "실선"}: ${SERIES_LABELS[s.name] ?? s.name}`)
          .join(" · ")}
        {" · 최근 "}
        {Math.max(...data.series.map((s) => s.points.length))}
        {"일(데이터축 최신일 기준)"}
      </div>
    </>
  );
}
