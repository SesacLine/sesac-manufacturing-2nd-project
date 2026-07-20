/** 화면1 대시보드 — 수율 요약(§2.1) + 분석 대기열(§2.2) + 배치 실행 버튼(§2.3). */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, formatDetail } from "../api/client";
import type { AnalysisList, YieldSummary } from "../api/types";
import YieldChart from "../components/YieldChart";
import { STATUS_LABELS } from "../labels";

const PAGE_SIZE = 10;

export default function DashboardPage() {
  const navigate = useNavigate();
  const [yieldData, setYieldData] = useState<YieldSummary | null>(null);
  const [yieldError, setYieldError] = useState<string | null>(null);
  const [list, setList] = useState<AnalysisList | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [runNotice, setRunNotice] = useState<string | null>(null);
  const [runBlocked, setRunBlocked] = useState(false);

  useEffect(() => {
    api.yieldSummary().then(setYieldData).catch((e) => setYieldError(formatDetail(e.detail ?? e.message)));
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

  return (
    <section className="panel">
      <div className="panel-head">
        <span>대시보드 (메인 진입 화면)</span>
        <span className="tag">일 1회 배치 (실시간 아님)</span>
      </div>
      <div className="panel-body">
        <div className="box">
          <div className="box-title">
            <span>수율 현황 요약 · 최근 7일 추이</span>
          </div>
          {yieldError ? (
            <div className="notice error">{yieldError}</div>
          ) : yieldData ? (
            <YieldChart data={yieldData} />
          ) : (
            <div className="na-note">불러오는 중...</div>
          )}
        </div>

        <div className="box">
          <div className="box-title">
            <span>
              ◆ 분석 결과 대기열 — 누적 {list?.count ?? 0}건 (행 클릭 시 결과 열람)
            </span>
            <span style={{ fontWeight: 400 }}>↓ 최신순</span>
          </div>
          {listError && <div className="notice error">{listError}</div>}
          {list && list.items.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>결함 패턴 그룹</th>
                  <th>소속 로트 수</th>
                  <th>유력 원인 후보</th>
                  <th>상태</th>
                </tr>
              </thead>
              <tbody>
                {list.items.map((item) => (
                  <tr
                    key={item.analysis_id}
                    className="clickable"
                    onClick={() => navigate(`/analyses/${item.analysis_id}`)}
                  >
                    <td>{item.pattern}</td>
                    <td>{item.lot_count}개 로트</td>
                    {/* top_cause는 열린 문자열 — 받은 값 그대로 표시(§2.2) */}
                    <td>{item.top_cause ?? "—"}</td>
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
