/** 화면3 분석 결과 — GET /analyses/{id}(§2.5) + 로트 클릭 웨이퍼맵(§2.6) + 근거 모달(§2.7).
 *  description null이면 summary_line(§3.2 gloss)로 fallback. hypotheses는 받은 순서 그대로. */

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError, formatDetail } from "../api/client";
import type { Analysis, LotWafers } from "../api/types";
import EvidenceModal from "../components/EvidenceModal";
import HypothesisCard from "../components/HypothesisCard";
import WaferStrip from "../components/WaferStrip";
import { STATUS_LABELS, summaryLine } from "../labels";

export default function ResultPage() {
  const { analysisId } = useParams<{ analysisId: string }>();
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedLot, setSelectedLot] = useState<string | null>(null);
  const [wafers, setWafers] = useState<LotWafers | null>(null);
  const [waferError, setWaferError] = useState<string | null>(null);
  const [modal, setModal] = useState<{ hypothesisId: string; cause: string } | null>(null);

  useEffect(() => {
    if (!analysisId) return;
    api
      .analysis(analysisId)
      .then(setAnalysis)
      .catch((e: ApiError) => setError(formatDetail(e.detail)));
  }, [analysisId]);

  const loadWafers = (lotId: string) => {
    if (selectedLot === lotId) {
      setSelectedLot(null);
      setWafers(null);
      return;
    }
    setSelectedLot(lotId);
    setWafers(null);
    setWaferError(null);
    api
      .lotWafers(lotId)
      .then(setWafers)
      .catch((e: ApiError) => setWaferError(formatDetail(e.detail)));
  };

  if (error) {
    return (
      <section className="panel">
        <div className="panel-head">
          <span>분석 결과</span>
        </div>
        <div className="panel-body">
          <div className="notice error">{error}</div>
        </div>
      </section>
    );
  }
  if (!analysis) {
    return (
      <section className="panel">
        <div className="panel-head">
          <span>분석 결과</span>
        </div>
        <div className="panel-body">
          <div className="na-note">불러오는 중...</div>
        </div>
      </section>
    );
  }

  // §3.2: description(VLM 자연어, 계약) 우선, null이면 summary_line(결정적 gloss 조립) fallback.
  const headline =
    analysis.description ??
    summaryLine(analysis.pattern, analysis.status, analysis.hypotheses[0]?.stage);

  return (
    <section className="panel">
      <div className="panel-head">
        <span>
          분석 결과 — {analysis.pattern} 그룹 ({analysis.lot_count} Lots) ·{" "}
          {STATUS_LABELS[analysis.status] ?? analysis.status}
        </span>
      </div>
      <div className="panel-body">
        <div className="box" style={{ fontWeight: 700 }}>
          결함 서술 요약 · {headline}
        </div>

        <div className="box">
          <div className="box-title">
            <span>그룹 소속 로트 목록</span>
            <span style={{ fontWeight: 400, color: "var(--text-dim)" }}>
              로트 클릭 → 판독 웨이퍼맵
            </span>
          </div>
          {analysis.lot_ids.map((lotId) => (
            <span
              key={lotId}
              className={selectedLot === lotId ? "lot-chip sel" : "lot-chip"}
              onClick={() => loadWafers(lotId)}
            >
              {lotId}
            </span>
          ))}
        </div>

        {selectedLot && waferError && <div className="notice error">{waferError}</div>}
        {selectedLot && wafers && (
          <WaferStrip
            data={wafers}
            onClose={() => {
              setSelectedLot(null);
              setWafers(null);
            }}
          />
        )}

        {analysis.status === "unmapped" ? (
          <div className="unable-box">
            <div className="mark">?</div>
            <div className="title">판독까지만 지원 — 원인 매핑 없음</div>
            <div className="desc">{analysis.reason}</div>
          </div>
        ) : (
          <>
            {analysis.status === "insufficient" && (
              <div className="unable-box">
                <div className="mark">△</div>
                <div className="title">판단 불가 — 근거부족</div>
                <div className="desc">{analysis.reason}</div>
              </div>
            )}
            <div className="box-title" style={{ margin: "6px 0 10px" }}>
              Hypothesis · Critic 결과 — 가설 {analysis.hypotheses.length}건 (대표 우선 정렬,
              받은 순서 그대로)
            </div>
            {analysis.hypotheses.map((h, i) => (
              <HypothesisCard
                key={h.hypothesis_id}
                hypothesis={h}
                isTop={i === 0}
                onShowEvidence={(hypothesisId, cause) => setModal({ hypothesisId, cause })}
              />
            ))}
          </>
        )}
      </div>
      <div className="foot-note">
        가설 카드 · 근거 보기 = 3섹션 모달(Commonality / Telemetry / Events)
      </div>

      {modal && analysisId && (
        <EvidenceModal
          analysisId={analysisId}
          hypothesisId={modal.hypothesisId}
          cause={modal.cause}
          onClose={() => setModal(null)}
        />
      )}
    </section>
  );
}
