/** §2.8 일별 수율 추이 + 분석 이벤트 오버레이. days는 metric_series 전 구간(데이터축 날짜),
 *  events는 defect_date가 잡힌 분석(§2.7 저장분). 이벤트 마커는 해당 날짜의 라인 수율 위에
 *  얹는다(YieldEvent는 수율값을 안 실어줌 — day에서 조회). 벽시계 안 씀(§1).
 *
 *  호버: **모든 날짜**에 투명 히트영역을 깔아 커서를 따라다니는 툴팁을 띄운다. 이벤트가 있는
 *  날은 원인·장비·검증등급까지, 없는 날은 "특이사항 없음"으로 — 평상일에도 수율을 읽을 수
 *  있어야 추이 위의 급락 지점을 비교할 수 있다. 브라우저 기본 <title>은 지연이 크고 스타일을
 *  못 줘서 쓰지 않는다.
 *
 *  ⚠️ 와이어프레임(v9)은 툴팁에 시나리오 ID(SC-002 등)를 함께 띄우지만 여기서는 뺀다 —
 *  그건 ground truth(정답 카드) 식별자라 노출하면 정답 누출이다(MCP가 웨이퍼 라벨을 절대
 *  반환하지 않는 것과 같은 원칙). 대신 analysis_id를 실어 클릭 시 그 분석 상세로 보낸다.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { YieldDaily, YieldEvent } from "../api/types";
import { causeLabel, stageColor, TIER_LABELS } from "../labels";

const W = 1100,
  H = 230,
  L = 40,
  R = 12,
  T = 10,
  B = 30;
const IW = W - L - R;
const IH = H - T - B;

type Hover = { x: number; y: number; date: string; yield: number; event?: YieldEvent };

export default function TrendChart({ data }: { data: YieldDaily }) {
  const navigate = useNavigate();
  const [hover, setHover] = useState<Hover | null>(null);

  const { days, events } = data;
  if (days.length === 0) {
    // 배치를 한 번도 안 돌렸거나(커서 없음) fab.db가 없을 때. 둘 다 "아직 볼 게 없다"라
    // 한 문구로 묶되, 다음 행동(배치 실행)을 알려준다.
    return (
      <div className="na-note">
        아직 표시할 수율 추이가 없습니다 — 배치를 한 번 실행하면 분석된 구간까지 그려집니다
        (fab.db가 없을 때도 비어 있습니다 — §2.8).
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
  // 날짜 → 이벤트(같은 날 여러 건이면 첫 건). 히트영역이 이벤트 유무를 즉시 판별하는 용도.
  const eventByDate = new Map(events.map((ev) => [ev.date, ev]));

  // x축 눈금 — 구간 길이에 맞춰 간격을 정한다. 월초·중순만 찍던 옛 방식은 한 달 남짓
  // 구간에서 눈금이 2~3개밖에 안 걸려 어느 날짜인지 읽을 수 없었다(실측 36일 → 3개).
  // 라벨이 겹치지 않는 선(약 14개)을 상한으로 두고 1·2·3·7·14·30일 중 맞는 간격을 고른다.
  const MAX_TICKS = 14;
  const tickStep = [1, 2, 3, 7, 14, 30].find((s) => days.length / s <= MAX_TICKS) ?? 30;
  const ticks = days
    // 뒤에서부터 세어 마지막 날(=가장 최근, 분석 완료 지점)이 항상 눈금에 들어오게 한다.
    .filter((_, i) => (days.length - 1 - i) % tickStep === 0)
    .map((d) => ({ t: Date.parse(d.date), label: d.date.slice(5).replace("-", "/") }));

  return (
    <>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="chart-svg"
        preserveAspectRatio="none"
        onMouseLeave={() => setHover(null)}
      >
        {[0, 20, 40, 60, 80, 100].map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="#e4e6ea" />
            <text className="chart-ax" x={L - 6} y={y(v) + 4} textAnchor="end">
              {v}
            </text>
          </g>
        ))}
        {ticks.map((m) => (
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
            />
          );
        })}
        {/* 히트영역 — 모든 날짜. 마커(r=4)보다 넉넉해야 잡히므로 r=7, 투명. 맨 위에 깔아
            아래 요소가 이벤트를 가로채지 않게 한다. */}
        {days.map((d, i) => {
          const ev = eventByDate.get(d.date);
          return (
            <circle
              key={d.date}
              className={ev ? "hit" : undefined}
              cx={pts[i][0].toFixed(1)}
              cy={pts[i][1].toFixed(1)}
              r={7}
              fill="transparent"
              onMouseMove={(e) =>
                setHover({ x: e.clientX, y: e.clientY, date: d.date, yield: d.yield, event: ev })
              }
              onClick={() => ev && navigate(`/analyses/${ev.analysis_id}`)}
            />
          );
        })}
      </svg>

      {hover && (
        <div
          className="chart-tip"
          style={{
            // 오른쪽 끝에서 잘리지 않게 화면 폭 안으로 접는다.
            left: Math.min(hover.x + 14, window.innerWidth - 310),
            top: hover.y + 12,
          }}
        >
          <span className="tip-head">
            {hover.date}
            {hover.event ? ` · ${hover.event.pattern}` : " · 정상 조업"}
          </span>
          <span className="tip-yield">수율 {hover.yield}%</span>
          {hover.event ? (
            <>
              <div>
                <span className="tip-l">근본원인: </span>
                {hover.event.cause ? causeLabel(hover.event.cause) : "판단 불가"}
              </div>
              <div>
                <span className="tip-l">원인 장비: </span>
                {hover.event.equipment ?? "—"}
                {hover.event.stage ? ` (${hover.event.stage})` : ""}
              </div>
              <div>
                <span className="tip-l">검증등급: </span>
                {hover.event.tier ? (TIER_LABELS[hover.event.tier] ?? hover.event.tier) : "—"}
              </div>
              <span className="tip-hint">클릭하면 분석 상세로 이동</span>
            </>
          ) : (
            <div className="tip-l">특이사항 없음</div>
          )}
        </div>
      )}

      {/* 범례는 한 줄 가로 배치 — "실선:/마커:/점선:"을 글로 풀어 쓰면 줄이 계속 늘어나
          차트보다 설명이 길어진다. 선·점 견본을 그대로 보여주면 단어 없이도 읽힌다.
          조작 안내는 오른쪽 끝으로 밀어(margin-left:auto) 범례와 섞이지 않게 한다. */}
      <div className="chart-legend">
        <span className="lg">
          <i className="sw-line" />일별 수율
        </span>
        <span className="lg">
          <i className="sw-dot" />분석 이벤트 {events.length}건 · 색 = 공정
        </span>
        <span className="lg">
          <i className="sw-dash" />전 구간 평균 {avg.toFixed(1)}%
        </span>
        <span className="lg-hint">날짜에 마우스를 올리면 상세 · 이벤트 클릭 시 분석으로 이동</span>
      </div>
    </>
  );
}
