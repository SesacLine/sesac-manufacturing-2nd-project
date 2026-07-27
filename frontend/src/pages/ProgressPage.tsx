/** 화면2 분석 진행 — GET /batches/{id} 1.5초 폴링(§2.4).
 *  current_step은 steps[]의 0-based 인덱스(1-based로 읽지 말 것),
 *  completed/failed면 폴링 종료. 실패도 HTTP 200 + status:"failed"로 온다. */

import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError, formatDetail } from "../api/client";
import type { Batch } from "../api/types";
import BatchLogByPattern from "../components/BatchLogByPattern";
import { BATCH_STATUS_LABELS, STEP_LABELS, TOOL_LABELS } from "../labels";

const POLL_MS = 1500;

export default function ProgressPage() {
  const { batchId } = useParams<{ batchId: string }>();
  const navigate = useNavigate();
  const [batch, setBatch] = useState<Batch | null>(null);
  const [error, setError] = useState<string | null>(null);
  const consoleRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!batchId) return;
    let stopped = false;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const b = await api.batch(batchId);
        if (stopped) return;
        setBatch(b);
        if (b.status === "running") {
          timer = window.setTimeout(poll, POLL_MS);
        }
        // completed/failed → 폴링 종료(§2.4). 화면 이동은 사용자 조작에 맡긴다.
      } catch (e) {
        if (stopped) return;
        setError(formatDetail((e as ApiError).detail));
      }
    };
    poll();
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [batchId]);

  useEffect(() => {
    // 새 로그가 붙으면 콘솔을 아래로 스크롤
    const el = consoleRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [batch?.logs.length]);

  if (error) {
    return (
      <section className="panel">
        <div className="panel-head">
          <span>분석 진행</span>
        </div>
        <div className="panel-body">
          <div className="notice error">{error}</div>
        </div>
      </section>
    );
  }
  if (!batch) {
    return (
      <section className="panel">
        <div className="panel-head">
          <span>분석 진행</span>
        </div>
        <div className="panel-body">
          <div className="na-note">불러오는 중...</div>
        </div>
      </section>
    );
  }

  const done = batch.status === "completed";
  const failed = batch.status === "failed";

  return (
    <section className="panel">
      <div className="panel-head">
        <span>
          {batch.batch_id} — {BATCH_STATUS_LABELS[batch.status] ?? batch.status}
        </span>
      </div>
      <div className="panel-body">
        <div className="box-title">진행 단계</div>
        <div className="steps">
          {batch.steps.map((key, i) => {
            const cls =
              done || i < batch.current_step
                ? "step done"
                : i === batch.current_step && batch.status === "running"
                  ? "step current"
                  : i === batch.current_step
                    ? "step done"
                    : "step";
            return (
              <div key={key} className={cls}>
                <div className="circle">{i + 1}</div>
                <div className="label">{STEP_LABELS[key] ?? key}</div>
              </div>
            );
          })}
        </div>

        {/* 진행 중에는 흐르는 콘솔(지금 무슨 도구를 부르는지), 완료 후에는 패턴별 토글
            (무엇을 어떻게 확인했는지 되짚기). 같은 로그를 목적에 맞게 다르게 보여준다. */}
        {done || failed ? (
          <>
            <div className="box-title">
              <span>결함 패턴별 분석 로그</span>
              <span style={{ fontWeight: 400, color: "var(--text-dim)" }}>
                패턴 클릭 → 도구별 호출 내역 · 결과 열람은 대기열에서
              </span>
            </div>
            <BatchLogByPattern logs={batch.logs} />
          </>
        ) : (
          <>
            <div className="box-title">설비 데이터 조회 로그</div>
            <div className="log-console" ref={consoleRef}>
              {batch.logs.length === 0 && <div>대기 중...</div>}
              {batch.logs.map((log, i) => (
                <div key={i}>
                  [{log.time}] {TOOL_LABELS[log.tool] ?? log.tool} — {log.message}{" "}
                  {log.status === "done" && <span className="ok">✓ 완료</span>}
                  {log.status === "running" && <span className="run">… 진행</span>}
                  {log.status === "error" && <span className="err">✗ 오류</span>}
                </div>
              ))}
            </div>
          </>
        )}

        {batch.status === "running" && (
          <div className="caption" style={{ marginTop: 8 }}>
            분석 중입니다. 잠시만 기다려주세요... (1.5초 간격 자동 갱신)
          </div>
        )}
        {done && (
          <div className="notice">
            분석 완료 — {batch.result_ids?.length ?? 0}건이 대기열에 쌓였습니다.{" "}
            <button className="ghost-btn" onClick={() => navigate("/")}>
              대시보드에서 확인
            </button>
          </div>
        )}
        {failed && <div className="notice error">배치 실행 실패 — {batch.error}</div>}
      </div>
      <div className="foot-note">
        결함 패턴별 그룹화 → 원인 후보 조회 → 설비 데이터 검증까지 진행합니다 · 완료되면 모든
        그룹 결과가 대시보드 목록에 한 번에 올라갑니다
      </div>
    </section>
  );
}
