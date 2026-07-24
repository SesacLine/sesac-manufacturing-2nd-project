/** 화면3 분석 결과 — GET /analyses/{id}(§2.5) + 로트 클릭 웨이퍼맵(§2.6) + 근거 모달(§2.7).
 *  description null이면 summary_line(§3.2 gloss)로 fallback. hypotheses는 받은 순서 그대로. */

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError, formatDetail } from "../api/client";
import type { Analysis, Hypothesis, LotWafers } from "../api/types";
import EvidenceModal from "../components/EvidenceModal";
import HypothesisCard from "../components/HypothesisCard";
import WaferStrip from "../components/WaferStrip";
import { CONFIDENCE_LABELS, STATUS_LABELS, summaryLine } from "../labels";

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

  // R2(원인군 카드): 채택 가설을 cluster_id로 묶는다(등장 순서 보존). 같은 cluster_id는 fab
  // 증거가 동일한 원인군 — 그 안에서 단일 헤드라인을 뽑으면 문헌 근거 많은 generic 형제가
  // 정답을 덮으므로, 후보 묶음으로 함께 제시한다. cluster_id 없으면 단독 후보(__solo).
  // 기각·미판정은 원인군에 안 넣고 아래 평면 목록으로 둔다.
  const acceptedHyps = analysis.hypotheses.filter((h) => h.verdict === "accepted");
  const otherHyps = analysis.hypotheses.filter((h) => h.verdict !== "accepted");
  const clusterOrder: string[] = [];
  const clusterMap = new Map<string, Hypothesis[]>();
  for (const h of acceptedHyps) {
    const key = h.cluster_id ?? `__solo_${h.hypothesis_id}`;
    if (!clusterMap.has(key)) {
      clusterMap.set(key, []);
      clusterOrder.push(key);
    }
    clusterMap.get(key)!.push(h);
  }

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
            {/* R1: 확정 원인이 아니라 "가능성 있는 후보"임을 표현 층에서 명시(불확실 표시).
                confidence=low(다수 채택/증거 약함)일 때 특히 단정하지 않도록 경고 배너를 띄운다. */}
            {analysis.status === "reviewed" && analysis.confidence === "low" && (
              <div className="notice" style={{ borderStyle: "solid" }}>
                ⚠ 확정된 근본 원인이 아닙니다 — 아래는 <b>가능성 있는 원인 후보</b>이며,
                채택 후보가 많거나 검증 증거가 약해 확신 수준은 <b>불확실</b>입니다. 참고로만
                활용하세요.
              </div>
            )}
            <div className="box-title" style={{ margin: "6px 0 10px" }}>
              <span>
                Hypothesis · Critic 결과 — 원인 후보 {analysis.hypotheses.length}건 (대표 우선
                정렬, 받은 순서 그대로)
              </span>
              <span
                className={analysis.confidence === "low" ? "badge warn" : "badge"}
                title="R1 확신 수준 — 확정이 아니라 가설 스코프"
              >
                확신: {CONFIDENCE_LABELS[analysis.confidence]}
              </span>
            </div>
            {/* R2: 채택 가설을 원인군(cluster)으로 묶어 카드로 낸다. 원인군에 후보가 여럿이면
                "하나로 좁혀지지 않음"을 명시 — 단일 헤드라인이 정답을 가리는 문제 완화. */}
            {clusterOrder.map((key, ci) => {
              const members = clusterMap.get(key)!;
              const multi = members.length > 1;
              const stageLabel = members[0].stage ? ` · ${members[0].stage} 공정` : "";
              return (
                <div key={key} className="box">
                  <div className="box-title">
                    <span>
                      원인군 {ci + 1}
                      {stageLabel} — 후보 {members.length}건
                    </span>
                    {multi && <span className="badge warn">하나로 좁혀지지 않음</span>}
                  </div>
                  {multi && (
                    <div className="caption" style={{ marginBottom: 8 }}>
                      이 후보들은 fab 증거가 동일해 단일 원인으로 확정할 수 없습니다 — 원인군으로
                      함께 검토하세요.
                    </div>
                  )}
                  {members.map((h) => (
                    <HypothesisCard
                      key={h.hypothesis_id}
                      hypothesis={h}
                      isTop={analysis.hypotheses[0]?.hypothesis_id === h.hypothesis_id}
                      onShowEvidence={(hypothesisId, cause) => setModal({ hypothesisId, cause })}
                    />
                  ))}
                </div>
              );
            })}
            {otherHyps.length > 0 && (
              <>
                <div className="box-title" style={{ margin: "6px 0 10px" }}>
                  <span>기각 · 미판정 가설 {otherHyps.length}건</span>
                </div>
                {otherHyps.map((h) => (
                  <HypothesisCard
                    key={h.hypothesis_id}
                    hypothesis={h}
                    isTop={false}
                    onShowEvidence={(hypothesisId, cause) => setModal({ hypothesisId, cause })}
                  />
                ))}
              </>
            )}
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
