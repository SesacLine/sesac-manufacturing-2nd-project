/** 화면1  — 수율 요약(§2.1) + 분석 대기열(§2.2) + 배치 실행 버튼(§2.3). */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, formatDetail } from "../api/client";
import type { AnalysisList, AnalysisSummary, BatchToday, CauseStats, YieldDaily } from "../api/types";
import CauseCharts from "../components/CauseCharts";
import TrendChart from "../components/TrendChart";
import {
  causeLabel,
  impactClass,
  QUEUE_CAUSE_FALLBACK,
  QUEUE_STATUS_PILL,
  STAGE_COLOR,
} from "../labels";

const PAGE_SIZE = 10;

// 대기열은 서버에서 **한 번에 다 받아** 정렬·페이징을 프론트가 한다(§2.2 각주 "정렬 자체는
// 프론트 몫 — 서버 정렬 키는 여전히 배치 시각"). 페이지 단위로 받으면 정렬이 그 페이지
// 안에서만 일어나 "가장 위험한 그룹"이 2페이지에 숨는다. 규모가 작아 가능한 선택이다 —
// 배치는 하루 1회고 하루 분석은 보통 1~3건이라, 데이터축 90일을 다 돌려도 수백 건이다.
const FETCH_LIMIT = 500;

/** 정렬 가능한 열. 값은 AnalysisSummary의 키 — 비교 함수가 이 키로 값을 꺼낸다. */
type SortKey = "analyzed_date" | "pattern" | "yield_impact" | "lot_count" | "top_cause" | "status";
type SortDir = "asc" | "desc";

/** 열별 기본 방향 — 처음 눌렀을 때 "보통 보고 싶은 순서"가 나오게 한다.
 *  수율영향은 가장 음수(=가장 나쁨)가 위, 날짜는 최신이 위. */
const DEFAULT_DIR: Record<SortKey, SortDir> = {
  analyzed_date: "desc",
  pattern: "asc",
  yield_impact: "asc", // -3.8 < -1.2 → 오름차순이 곧 "피해 큰 순"
  lot_count: "desc",
  top_cause: "asc",
  status: "asc",
};

const SORT_LABEL: Record<SortKey, string> = {
  analyzed_date: "분석일",
  pattern: "결함 패턴 그룹",
  yield_impact: "수율영향",
  // 한 열에 두 값을 "소속/참조"로 나란히 보여준다. 정렬 키는 **소속 로트 수**다 —
  // 참조는 이 카드의 처분 대상이 아니라 근거 계산에 참조만 한 로트라, 그걸로 줄을
  // 세우면 "일이 많은 순"이 아니라 "이력이 많았던 순"이 된다.
  lot_count: "소속/참조 로트",
  top_cause: "유력 원인 후보",
  status: "상태",
};

/** null은 방향과 무관하게 **항상 맨 뒤**로 보낸다.
 *  값이 없는 건 "작은 값"이 아니라 "모르는 값"이라, 오름차순에서 맨 위로 올라오면
 *  구 저장분(yield_impact/analyzed_date가 null)이 가장 위험한 그룹처럼 보인다. */
function compareRows(a: AnalysisSummary, b: AnalysisSummary, key: SortKey, dir: SortDir): number {
  const av = a[key];
  const bv = b[key];
  if (av === null && bv === null) return 0;
  if (av === null) return 1;
  if (bv === null) return -1;
  const sign = dir === "asc" ? 1 : -1;
  if (typeof av === "number" && typeof bv === "number") return (av - bv) * sign;
  return String(av).localeCompare(String(bv), "ko") * sign;
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const [trend, setTrend] = useState<YieldDaily | null>(null); // §2.8
  const [causes, setCauses] = useState<CauseStats | null>(null); // §2.9
  const [chartError, setChartError] = useState<string | null>(null);
  const [today, setToday] = useState<BatchToday | null>(null); // 서버 '오늘'(§2.3 부속)
  const [list, setList] = useState<AnalysisList | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  // 대기열 정렬 — 기본은 **분석일 최신순**. 이 화면은 "매일 아침 눌러 쌓인 이력"을 보는
  // 곳이라 방금 돌린 배치 결과가 맨 위에 있어야 한다. 위험도로 보고 싶으면 수율영향
  // 머리글을 누른다(예전엔 수율영향순이 강제였고 머리글은 "↓ 날짜순"으로 하드코딩돼 있어
  // 표시와 동작이 어긋나 있었다).
  const [sortKey, setSortKey] = useState<SortKey>("analyzed_date");
  const [sortDir, setSortDir] = useState<SortDir>(DEFAULT_DIR.analyzed_date);
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

  // 전량 조회(정렬·페이징은 아래에서 프론트가 한다). sort=latest는 유지 — lastBatchId가
  // items[0]을 "가장 최근 배치"로 읽기 때문이고, 표시 순서는 sortKey가 따로 정한다.
  const loadList = useCallback(() => {
    api
      .analyses("latest", FETCH_LIMIT, 0)
      .then(setList)
      .catch((e: ApiError) => setListError(formatDetail(e.detail)));
  }, []);
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

  /** 열 머리 클릭 — 같은 열이면 방향만 뒤집고, 다른 열이면 그 열의 기본 방향으로 간다.
   *  정렬이 바뀌면 1페이지로 돌아간다(3페이지를 보던 중 정렬만 바뀌면 엉뚱한 구간이 보인다). */
  const toggleSort = (key: SortKey) => {
    setSortDir((prev) => (key === sortKey ? (prev === "asc" ? "desc" : "asc") : DEFAULT_DIR[key]));
    setSortKey(key);
    setPage(0);
  };

  // "로그 확인"이 걸 배치 — 대기열 최신 행(sort=latest라 items[0]이 가장 최근 배치)의 batch_id.
  // 예전엔 실행 응답을 localStorage에 담아 썼는데, 그러면 이 브라우저에서 버튼을 눌러본 적이
  // 없을 때(새로고침·다른 기기·서버에서 직접 실행) 버튼이 아예 안 뜬다. 서버 데이터에서
  // 가져오면 누가 언제 돌렸든 항상 최신 로그로 이어진다.
  const lastBatchId = list?.items[0]?.batch_id ?? null;

  // 전체를 정렬한 뒤 잘라야 "가장 위험한 그룹"이 1페이지에 온다 — 페이지를 먼저 자르고
  // 정렬하면 그 페이지 안에서만 순서가 바뀐다(예전 동작).
  const sorted = list ? [...list.items].sort((a, b) => compareRows(a, b, sortKey, sortDir)) : [];
  const rows = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  // 페이지 수는 **실제로 받아 온 행 수** 기준이다. list.count는 서버의 전체 건수라, 혹시
  // FETCH_LIMIT를 넘어 잘렸다면 있지도 않은 페이지가 생겨 빈 화면이 나온다.
  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));

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
            {/* 예전엔 "↓ 날짜순"이 하드코딩돼 있었는데 실제 정렬은 수율영향순이라 표시와
                동작이 어긋나 있었다. 지금은 현재 정렬 상태를 그대로 읽어 쓴다. */}
            <span style={{ fontWeight: 400 }}>
              {sortDir === "asc" ? "↑" : "↓"} {SORT_LABEL[sortKey]}순 (머리글 클릭)
            </span>
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
                  {/* 머리글 = 정렬 버튼. aria-sort로 현재 정렬 열·방향을 노출하고(스크린리더),
                      CSS도 그 속성으로 강조한다 — 상태의 단일 소스가 되어 어긋날 수 없다.
                      정렬 중이 아닌 열은 화살표 자리를 빈 칸으로 남겨 열 너비를 고정한다. */}
                  {(Object.keys(SORT_LABEL) as SortKey[]).map((key) => (
                    <th
                      key={key}
                      className="sortable"
                      aria-sort={
                        sortKey !== key ? "none" : sortDir === "asc" ? "ascending" : "descending"
                      }
                    >
                      <button type="button" onClick={() => toggleSort(key)}>
                        {SORT_LABEL[key]}
                        <span className="arr">
                          {sortKey !== key ? "" : sortDir === "asc" ? "▲" : "▼"}
                        </span>
                      </button>
                    </th>
                  ))}
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
                    {/* 소속/참조 — 참조 로트(§2.2 cohort_count)는 공통 장비를 찾을 때만
                        참조한 최근 7일 동일 패턴 로트라 처분 대상이 아니다. 합산하지 않고
                        슬래시로 나란히 둬서 "1개로 판단한 게 아니다"가 목록에서도 읽히게 한다. */}
                    <td style={{ whiteSpace: "nowrap" }}>
                      {item.lot_count}개
                      <span style={{ color: "var(--text-dim)" }}>/{item.cohort_count}개</span>
                    </td>
                    {/* reviewed면 top_cause를 한국어 gloss로(원문 id는 tooltip에 남긴다 —
                        KG·평가 대조는 원문 문자열로 하므로 화면에서 사라지면 안 된다).
                        그 외 상태는 top_cause가 null이라 상태별 판단불가 사유로 대체. */}
                    <td title={item.top_cause ?? undefined}>
                      {item.top_cause
                        ? causeLabel(item.top_cause)
                        : (QUEUE_CAUSE_FALLBACK[item.status] ?? "판단 불가")}
                    </td>
                    {/* 확신 수준(§2.5 confidence) 열은 뺐다 — 백엔드 _confidence()가 사실상 상수
                        "low"라(채택 "클러스터"가 아니라 행 수를 세는 문제) 전 행이 "불확실"로 같아
                        정보량이 0이었다. 응답 필드·store 컬럼은 그대로라 로직 수리 후 열만 되살리면
                        된다. "확정 아님" 고지 자체는 화면3 배너(ResultPage)가 계속 말한다. */}
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
          {sorted.length > PAGE_SIZE && (
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
