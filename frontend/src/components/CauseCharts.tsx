/** §2.9 원인 장비 구성비(도넛) · 결함 패턴 Pareto(막대) · 패턴별 채택 원인(칩).
 *  전부 app_state.db 저장분 집계(조회만, §2.7). 색 = 공정 단계(stageColor). patterns.mapped는
 *  KG 매핑 3종 여부(§3) — mapped=파랑, 미매핑=회색. 정답 라벨 누출 없음(집계 카운트만). */

import type { CauseStats } from "../api/types";
import { causeLabel, CHART_NEUTRAL, stageColor, TIER_LABELS } from "../labels";

// ---- 도넛 (원인 장비 구성비) ----
function Donut({ equipment }: { equipment: CauseStats["equipment"] }) {
  if (equipment.length === 0) return <div className="na-note">채택 원인 장비 없음.</div>;
  const total = equipment.reduce((s, e) => s + e.count, 0);
  const items = [...equipment].sort((a, b) => b.count - a.count);
  const cx = 150,
    cy = 105,
    r = 72,
    r2 = 42;
  let a0 = -Math.PI / 2;
  const p = (a: number, rr: number) =>
    `${(cx + rr * Math.cos(a)).toFixed(1)} ${(cy + rr * Math.sin(a)).toFixed(1)}`;

  return (
    <svg viewBox="0 0 300 210" className="chart-svg">
      {items.map((e) => {
        const frac = e.count / total;
        // frac===1이면 360° 아크가 안 그려져 hairline 갭을 남긴다.
        const a1 = a0 + 2 * Math.PI * (frac >= 1 ? 0.9999 : frac);
        const mid = (a0 + a1) / 2;
        const big = a1 - a0 > Math.PI ? 1 : 0;
        const d = `M${p(a0, r)}A${r} ${r} 0 ${big} 1 ${p(a1, r)}L${p(a1, r2)}A${r2} ${r2} 0 ${big} 0 ${p(a0, r2)}Z`;
        const lx = cx + (r + 20) * Math.cos(mid);
        const ly = cy + (r + 20) * Math.sin(mid) + 4;
        a0 = a1;
        return (
          <g key={e.equipment_id}>
            <path d={d} fill={stageColor(e.stage)} stroke="#fff" strokeWidth={2}>
              <title>
                {e.equipment_id}
                {e.stage ? ` (${e.stage})` : ""} — 채택 {e.count}건
              </title>
            </path>
            <text className="chart-lb" x={lx} y={ly} textAnchor="middle">
              {e.equipment_id} {e.count}
            </text>
          </g>
        );
      })}
      <text className="chart-vl" x={cx} y={cy - 1} textAnchor="middle" fontSize={16}>
        {total}건
      </text>
      <text className="chart-ax" x={cx} y={cy + 15} textAnchor="middle">
        채택 유력
      </text>
    </svg>
  );
}

// ---- Pareto (결함 패턴별 판독 웨이퍼 수) ----
function Pareto({ patterns }: { patterns: CauseStats["patterns"] }) {
  if (patterns.length === 0) return <div className="na-note">판독 집계 없음.</div>;
  const items = [...patterns].sort((a, b) => b.wafer_count - a.wafer_count);
  const max = items[0].wafer_count || 1;
  const W = 400,
    L = 68,
    R = 56,
    T = 4,
    bh = 20,
    gap = 8;
  const x = (v: number) => L + ((W - L - R) * v) / max;
  const H = T + items.length * (bh + gap);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart-svg">
      {items.map((v, i) => {
        const Y = T + i * (bh + gap);
        return (
          <g key={v.pattern}>
            <text className="chart-lb" x={L - 6} y={Y + bh / 2 + 4} textAnchor="end">
              {v.pattern}
            </text>
            <rect
              x={L}
              y={Y}
              width={(x(v.wafer_count) - L).toFixed(1)}
              height={bh}
              fill={v.mapped ? "#2a78d6" : CHART_NEUTRAL}
            >
              <title>
                {v.pattern} — {v.wafer_count.toLocaleString()}장 ·{" "}
                {v.mapped ? "원인 분석 대상" : "판독만 지원"}
              </title>
            </rect>
            <text className="chart-vl" x={x(v.wafer_count) + 5} y={Y + bh / 2 + 4}>
              {v.wafer_count.toLocaleString()}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ---- 원인 칩 (패턴별 채택 원인) ----
function CauseChips({ causes }: { causes: CauseStats["causes"] }) {
  if (causes.length === 0) return <div className="na-note">채택 원인 없음.</div>;
  // 패턴별 그룹, 패턴은 총 카운트 내림차순.
  const byPattern = new Map<string, CauseStats["causes"]>();
  for (const c of causes) {
    if (!byPattern.has(c.pattern)) byPattern.set(c.pattern, []);
    byPattern.get(c.pattern)!.push(c);
  }
  const pats = [...byPattern.keys()].sort(
    (a, b) =>
      byPattern.get(b)!.reduce((s, c) => s + c.count, 0) -
      byPattern.get(a)!.reduce((s, c) => s + c.count, 0),
  );
  return (
    <div>
      {pats.map((pat) => (
        <div key={pat} className="cause-row">
          <span className="cause-pat">{pat}</span>
          <div className="chips">
            {byPattern.get(pat)!.map((c, i) => (
              <span
                key={`${c.cause}-${i}`}
                className="cause-chip"
                style={{ background: stageColor(c.stage) }}
                title={`${c.cause} — ${c.count}건 · ${TIER_LABELS[c.tier ?? "none"] ?? c.tier ?? ""}${c.stage ? ` · ${c.stage}` : ""}`}
              >
                {causeLabel(c.cause)}
                {c.count > 1 ? ` ×${c.count}` : ""}
                {c.stage && <small>{c.stage}</small>}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function CauseCharts({ data }: { data: CauseStats }) {
  // 도넛의 모수 — 채택 원인으로 지목된 건수 합(장비별 count의 합). v9는 더미라 8을 박아뒀지만
  // 여기서는 실제 집계에서 센다("8건 기준"이 데이터와 어긋나면 오히려 신뢰를 깎는다).
  const adoptedTotal = data.equipment.reduce((n, e) => n + e.count, 0);
  return (
    <div className="chart-grid">
      <div>
        <div className="chart-sub">
          원인 장비<span className="sd">채택 유력 {adoptedTotal}건 기준</span>
        </div>
        <Donut equipment={data.equipment} />
      </div>
      <div>
        <div className="chart-sub">
          결함 패턴별 웨이퍼 수<span className="sd">파랑 = 원인 분석 대상</span>
        </div>
        <Pareto patterns={data.patterns} />
      </div>
      <div>
        <div className="chart-sub">
          패턴별 채택 원인<span className="sd">색 = 발생 공정</span>
        </div>
        <CauseChips causes={data.causes} />
      </div>
    </div>
  );
}
