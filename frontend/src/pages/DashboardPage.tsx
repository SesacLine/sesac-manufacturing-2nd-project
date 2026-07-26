/** 화면1 대시보드 — 수율 요약(§2.1) + 분석 대기열(§2.2) + 배치 실행 버튼(§2.3). */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, formatDetail } from "../api/client";
import type { AnalysisList, CauseStats, YieldDaily } from "../api/types";
import CauseCharts from "../components/CauseCharts";
import TrendChart from "../components/TrendChart";
import { CONFIDENCE_LABELS, impactClass, QUEUE_CAUSE_FALLBACK, STATUS_LABELS } from "../labels";

const PAGE_SIZE = 10;

export default function DashboardPage() {
  const navigate = useNavigate();
  const [trend, setTrend] = useState<YieldDaily | null>(null); // §2.8
  const [causes, setCauses] = useState<CauseStats | null>(null); // §2.9
  const [chartError, setChartError] = useState<string | null>(null);
  const [list, setList] = useState<AnalysisList | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [runNotice, setRunNotice] = useState<string | null>(null);
  const [runBlocked, setRunBlocked] = useState(false);

  useEffect(() => {
    // §2.8 추이·§2.9 집계는 독립 조회 — 하나가 비어도(fab.db 미빌드) 나머지는 뜬다.
    api.yieldDaily().then(setTrend).catch((e) => setChartError(formatDetail(e.detail ?? e.message)));
    api.causeStats().then(setCauses).catch((e) => setChartError(formatDetail(e.detail ?? e.message)));
  }, []);

  const loadList = useCallback(() => {
    api
      .analyses("latest", PAGE_SIZE, page * PAGE_SIZE)
      .then(setList)
      .catch((e: ApiError) => setListError(formatDetail(e.detail)));
  }, [page]);
  useEffect(loadList, [loadList]);

  const runBatch = async () => {
    setRunNotice(null);
    try {
      const accepted = await api.runBatch();
      navigate(`/batches/${accepted.batch_id}`);
    } catch (e) {
      const err = e as ApiError;
      // §2.3 409: detail 문자열을 그대로 안내(문자열 파싱 분기 금지), 자동 이동 없음, 버튼 비활성.
      if (err.status === 409) {
        setRunNotice(formatDetail(err.detail));
        setRunBlocked(true);
      } else {
        setRunNotice(formatDetail(err.detail ?? "배치 실행 요청에 실패했습니다."));
      }
    }
  };

  const totalPages = list ? Math.max(1, Math.ceil(list.count / PAGE_SIZE)) : 1;

  // 화면 표시 정렬: 이 페이지의 행을 수율영향 큰 순(가장 음수 먼저)으로 재배열한다(v8 "↓ 수율영향순").
  // 서버 정렬은 latest 고정이라 페이지 내에서만 재정렬 — null(구 저장분)은 맨 뒤로 민다.
  const rows = list
    ? [...list.items].sort((a, b) => (a.yield_impact ?? Infinity) - (b.yield_impact ?? Infinity))
    : [];

  return (
    <section className="panel">
      <div className="panel-head">
        <span>대시보드 (메인 진입 화면)</span>
        <span className="tag">일 1회 배치 (실시간 아님)</span>
      </div>
      <div className="panel-body">
        <details className="box chart-box" open>
          <summary>
            <span className="arr" />
            수율 현황 차트 — 일별 수율 추이(§2.8) · 원인 장비 구성 · 패턴 Pareto(§2.9){" "}
            <span style={{ fontWeight: 400, color: "var(--text-dim)" }}>(클릭 = 접기/펼치기)</span>
          </summary>
          {chartError && <div className="notice error">{chartError}</div>}

          <div className="box-title" style={{ marginTop: 12 }}>
            <span>수율 현황 요약 · 일별 수율 추이 (데이터축 전 구간 · 이상 이벤트 오버레이)</span>
          </div>
          {trend ? (
            <TrendChart data={trend} />
          ) : (
            !chartError && <div className="na-note">불러오는 중...</div>
          )}

          <div style={{ borderTop: "1px dashed var(--line)", margin: "14px 0 10px" }} />

          <div className="box-title">
            <span>원인 장비 구성비 · 결함 패턴 Pareto · 패턴별 채택 원인</span>
            <span style={{ fontWeight: 400, color: "var(--text-dim)" }}>색 = 공정 단계</span>
          </div>
          {causes ? (
            <CauseCharts data={causes} />
          ) : (
            !chartError && <div className="na-note">불러오는 중...</div>
          )}
        </details>

        <div className="box">
          <div className="box-title">
            <span>
              ◆ 분석 결과 대기열 — 누적 {list?.count ?? 0}건 (행 클릭 시 결과 열람)
            </span>
            <span style={{ fontWeight: 400 }}>↓ 수율영향순</span>
          </div>
          {list && list.items.length > 0 && (
            <div className="caption" style={{ marginBottom: 6 }}>
              위에서부터 수율영향 큰 순 · 색(고/중/저)은 −3%p·−2%p 임계의 프론트 표시 규칙이며
              백엔드 severity 필드가 아닙니다 · 확신 수준은 R1(잠정 지지/불확실)로 "확정"은 없습니다.
            </div>
          )}
          {listError && <div className="notice error">{listError}</div>}
          {list && list.items.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>결함 패턴 그룹</th>
                  <th>수율영향</th>
                  <th>소속 로트</th>
                  <th>유력 원인 후보</th>
                  <th>확신 수준</th>
                  <th>상태</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((item) => (
                  <tr
                    key={item.analysis_id}
                    className="clickable"
                    onClick={() => navigate(`/analyses/${item.analysis_id}`)}
                  >
                    <td>{item.pattern}</td>
                    {/* 수율영향 %p — 색은 프론트 표시 규칙(§3), 백엔드 severity 아님. null=구 저장분 */}
                    <td className={impactClass(item.yield_impact)}>
                      {item.yield_impact === null ? "—" : `${item.yield_impact}%p`}
                    </td>
                    <td>{item.lot_count}개</td>
                    {/* reviewed면 top_cause(열린 문자열 그대로 §2.2), 그 외는 상태별 판단불가 사유 */}
                    <td>{item.top_cause ?? QUEUE_CAUSE_FALLBACK[item.status] ?? "판단 불가"}</td>
                    {/* R1 확신 수준(§2.5) — "확정"은 없음 */}
                    <td>{CONFIDENCE_LABELS[item.confidence] ?? "불확실"}</td>
                    <td>
                      <span className={item.status === "reviewed" ? "badge dark" : "badge"}>
                        {STATUS_LABELS[item.status] ?? item.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {list && list.items.length === 0 && (
            <div className="caption">
              아직 분석된 결과가 없습니다. 아래 "오늘 판독 배치 확인"을 누르면 그룹화부터
              Hypothesis·Critic 전과정이 실행되고, 결과가 이 대기열에 한 번에 쌓입니다.
            </div>
          )}
          {list && list.count > PAGE_SIZE && (
            <div className="pager">
              <button className="ghost-btn" disabled={page === 0} onClick={() => setPage(page - 1)}>
                ◀ 이전
              </button>
              <span>
                {page + 1} / {totalPages}
              </span>
              <button
                className="ghost-btn"
                disabled={page + 1 >= totalPages}
                onClick={() => setPage(page + 1)}
              >
                다음 ▶
              </button>
            </div>
          )}
        </div>

        {runNotice && <div className="notice">{runNotice}</div>}
        <div style={{ marginTop: 16, textAlign: "center" }}>
          <button className="primary-btn" onClick={runBatch} disabled={runBlocked}>
            ▶ 오늘 판독 배치 확인 (그룹화 → 에이전트 전과정 실행)
          </button>
        </div>
      </div>
      <div className="foot-note">
        버튼 클릭 = 직전 배치 이후 누적 저수율 로트 자동 그룹화 + 전 그룹 Hypothesis·Critic 일괄
        실행 → 결과가 대기열에 누적
      </div>
    </section>
  );
}
