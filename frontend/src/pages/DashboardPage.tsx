/** 화면1  — 수율 요약(§2.1) + 분석 대기열(§2.2) + 배치 실행 버튼(§2.3). */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, formatDetail } from "../api/client";
import type { AnalysisList, BatchToday, CauseStats, YieldDaily } from "../api/types";
import CauseCharts from "../components/CauseCharts";
import TrendChart from "../components/TrendChart";
import {
  causeLabel,
  CONFIDENCE_LABELS,
  impactClass,
  QUEUE_CAUSE_FALLBACK,
  QUEUE_STATUS_PILL,
  STAGE_COLOR,
} from "../labels";

const PAGE_SIZE = 10;

export default function DashboardPage() {
  const navigate = useNavigate();
  const [trend, setTrend] = useState<YieldDaily | null>(null); // §2.8
  const [causes, setCauses] = useState<CauseStats | null>(null); // §2.9
  const [chartError, setChartError] = useState<string | null>(null);
  const [today, setToday] = useState<BatchToday | null>(null); // 서버 '오늘'(§2.3 부속)
  const [list, setList] = useState<AnalysisList | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [runNotice, setRunNotice] = useState<string | null>(null);
  const [runBlocked, setRunBlocked] = useState(false);

  // §2.8 추이·§2.9 집계는 독립 조회 — 하나가 비어도(fab.db 미빌드) 나머지는 뜬다.
  // 배치를 돌리거나 초기화하면 커서가 움직여 셋 다 값이 바뀌므로 한 묶음으로 다시 읽는다.
  const loadHeader = useCallback(() => {
    api.yieldDaily().then(setTrend).catch((e) => setChartError(formatDetail(e.detail ?? e.message)));
    api.causeStats().then(setCauses).catch((e) => setChartError(formatDetail(e.detail ?? e.message)));
    api
      .batchToday()
      .then((t) => {
        setToday(t);
        // 그 날짜 배치가 이미 끝났으면 눌러봐야 409 — 클릭 전에 잠근다.
        setRunBlocked(t.done);
      })
      .catch(() => {
        /* 배지만 못 뜬다 — 배치 실행 자체는 막지 않는다 */
      });
  }, []);
  useEffect(loadHeader, [loadHeader]);

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

  const resetLastBatch = async () => {
    if (!window.confirm("가장 최근 배치를 되돌립니다. 그 배치가 만든 분석이 삭제되고 같은 날짜를 다시 돌릴 수 있게 됩니다. 계속할까요?")) {
      return;
    }
    setRunNotice(null);
    try {
      const r = await api.resetLastBatch();
      setRunNotice(`${r.batch_id} 초기화 완료 — 분석 ${r.removed_analyses}건 삭제.`);
      setPage(0);
      loadList();
      // 커서가 뒤로 갔으니 배지 날짜·차트 범위·버튼 잠금이 전부 한 칸 되돌아간다.
      loadHeader();
    } catch (e) {
      setRunNotice(formatDetail((e as ApiError).detail ?? "초기화에 실패했습니다."));
    }
  };

  const totalPages = list ? Math.max(1, Math.ceil(list.count / PAGE_SIZE)) : 1;

  // "로그 확인"이 걸 배치 — 대기열 최신 행(sort=latest라 items[0]이 가장 최근 배치)의 batch_id.
  // 예전엔 실행 응답을 localStorage에 담아 썼는데, 그러면 이 브라우저에서 버튼을 눌러본 적이
  // 없을 때(새로고침·다른 기기·서버에서 직접 실행) 버튼이 아예 안 뜬다. 서버 데이터에서
  // 가져오면 누가 언제 돌렸든 항상 최신 로그로 이어진다.
  const lastBatchId = list?.items[0]?.batch_id ?? null;

  // 화면 표시 정렬: 이 페이지의 행을 수율영향 큰 순(가장 음수 먼저)으로 재배열한다(v8 "↓ 수율영향순").
  // 서버 정렬은 latest 고정이라 페이지 내에서만 재정렬 — null(구 저장분)은 맨 뒤로 민다.
  const rows = list
    ? [...list.items].sort((a, b) => (a.yield_impact ?? Infinity) - (b.yield_impact ?? Infinity))
    : [];

  return (
    <section className="panel">
      <div className="panel-head">
        <span> 대시보드 </span>
        {/* 배치 날짜 배지 — 서버 '오늘'(커서 파생)이라 배치를 돌릴 때마다 하루씩 바뀐다.
            "일 1회"가 추상 규칙이 아니라 "지금 이 날짜의 배치"로 읽히도록 날짜를 크게 둔다. */}
        <span className="tag batch-day">
          {today ? (
            <>
              일 1회 배치 · <b>{today.today}</b>
              {today.done && <span className="batch-day-done">분석 완료</span>}
            </>
          ) : (
            "일 1회 배치 (실시간 아님)"
          )}
        </span>
      </div>
      <div className="panel-body">
        {/* 접기/펼치기(details)를 걷어냈다 — 대시보드에서 가장 먼저 봐야 할 게 수율 추이인데
            토글이 있으면 접힌 상태로 시연이 시작될 수 있고, 열고 닫는 조작 자체가 정보가 아니다. */}
        <div className="box chart-box">
          {chartError && <div className="notice error">{chartError}</div>}

          <div className="box-title">
            <span>수율 현황 요약 · 일별 수율 추이</span>
          </div>
          {trend ? (
            <TrendChart data={trend} />
          ) : (
            !chartError && <div className="na-note">불러오는 중...</div>
          )}

          <div style={{ borderTop: "1px dashed var(--line)", margin: "14px 0 10px" }} />

          <div className="box-title">
            <span>원인 장비 · 결함 패턴 · 패턴별 채택 원인</span>
            {/* 색 = 공정 단계. 말로만 쓰지 않고 실제 색 견본을 함께 둔다(v9 범례) —
                세 차트가 전부 이 색을 쓰므로 여기 한 번만 두면 셋 다 읽힌다. */}
            <span style={{ fontWeight: 400, color: "var(--text-dim)" }}>
              색 = 공정
              {(["ETCH", "DEPO", "CMP", "CLEAN"] as const).map((s) => (
                <span key={s}>
                  {"  "}
                  <span className="chart-lg" style={{ background: STAGE_COLOR[s] }} />
                  {s}
                </span>
              ))}
            </span>
          </div>
          {causes ? (
            <CauseCharts data={causes} />
          ) : (
            !chartError && <div className="na-note">불러오는 중...</div>
          )}
        </div>

        <div className="box">
          <div className="box-title">
            <span>
              ◆ 분석 결과 — 누적 {list?.count ?? 0}건 (행 클릭 시 결과 열람 가능)
            </span>
            <span style={{ fontWeight: 400 }}>↓ 날짜순</span>
          </div>
          {list && list.items.length > 0 && (
            <div className="caption" style={{ marginBottom: 6 }}>
            </div>
          )}
          {listError && <div className="notice error">{listError}</div>}
          {list && list.items.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>분석일</th>
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
                    {/* 분석 실행일(배치 시작일) — 결함 발생일이 아니다. 구 저장분은 null */}
                    <td style={{ whiteSpace: "nowrap", color: "var(--text-dim)" }}>
                      {item.analyzed_date ?? "—"}
                    </td>
                    <td>{item.pattern}</td>
                    {/* 수율영향 %p — 색은 프론트 표시 규칙(§3), 백엔드 severity 아님. null=구 저장분 */}
                    <td className={impactClass(item.yield_impact)}>
                      {item.yield_impact === null ? "—" : `${item.yield_impact}%p`}
                    </td>
                    <td>{item.lot_count}개</td>
                    {/* reviewed면 top_cause를 한국어 gloss로(원문 id는 tooltip에 남긴다 —
                        KG·평가 대조는 원문 문자열로 하므로 화면에서 사라지면 안 된다).
                        그 외 상태는 top_cause가 null이라 상태별 판단불가 사유로 대체. */}
                    <td title={item.top_cause ?? undefined}>
                      {item.top_cause
                        ? causeLabel(item.top_cause)
                        : (QUEUE_CAUSE_FALLBACK[item.status] ?? "판단 불가")}
                    </td>
                    {/* R1 확신 수준(§2.5) — "확정"은 없음 */}
                    <td>{CONFIDENCE_LABELS[item.confidence] ?? "불확실"}</td>
                    {/* v9: 상태 열은 "조치 필요 여부"만 — 세부 사유는 왼쪽 원인 열이 말한다 */}
                    <td>
                      {(() => {
                        const pill = QUEUE_STATUS_PILL[item.status];
                        return pill ? (
                          <span className={`status-pill ${pill.cls}`}>{pill.text}</span>
                        ) : (
                          <span className="status-pill na">{item.status}</span>
                        );
                      })()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {list && list.items.length === 0 && (
            <div className="caption">
              아직 분석된 결과가 없습니다. 아래 "오늘 판독 배치 확인"을 누르면 웨이퍼 판독부터
              원인 후보 검증까지 한 번에 실행되고, 결과가 이 목록에 쌓입니다.
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
        <div
          style={{
            marginTop: 16,
            display: "flex",
            gap: 10,
            justifyContent: "center",
            alignItems: "center",
          }}
        >
          <button className="primary-btn" onClick={runBatch} disabled={runBlocked}>
            ▶ 오늘 판독 배치 확인
          </button>
          {/* 이 클릭이 실제로 훑을 데이터 구간. 평상시는 하루치지만 첫 배치·건너뛴 날이
              있으면 그만큼 넓어지므로 from~to를 그대로 보여준다. */}
          {today?.target_from && today.target_to && !today.done && (
            <span className="caption" style={{ marginTop: 0 }}>
              대상 구간{" "}
              {today.target_from === today.target_to
                ? today.target_from
                : `${today.target_from} ~ ${today.target_to}`}
            </span>
          )}
          {/* 직전 배치의 도구 호출 내역 되짚기 — 결과 카드가 "왜 그렇게 나왔는지"의 추적 경로 */}
          {lastBatchId && (
            <button className="ghost-btn" onClick={() => navigate(`/batches/${lastBatchId}`)}>
              로그 확인
            </button>
          )}
          {/* 시연용 — 마지막 배치를 되돌려 같은 날짜를 다시 돌린다(분석 삭제 + 커서 복원) */}
          {lastBatchId && (
            <button className="ghost-btn" onClick={resetLastBatch}>
              ↺ 초기화
            </button>
          )}
        </div>
      </div>
      <div className="foot-note">
        버튼 클릭 = 전날 저수율 로트를 결함 패턴별로 묶어 원인 후보를 찾고, 설비 데이터로
        하나씩 검증한 결과를 위 목록에 쌓습니다.
      </div>
    </section>
  );
}
