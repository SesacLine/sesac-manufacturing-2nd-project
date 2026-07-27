/** 화면3 분석 결과 — GET /analyses/{id}(§2.5) + 로트 클릭 웨이퍼맵(§2.6) + 근거 모달(§2.7).
 *  description null이면 summary_line(§3.2 gloss)로 fallback. hypotheses는 받은 순서 그대로. */

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError, formatDetail } from "../api/client";
import type { Analysis, AnalysisStatus, Hypothesis, LotWafers, Verdict } from "../api/types";
import ActionList from "../components/ActionList";
import EvidenceModal from "../components/EvidenceModal";
import HypothesisCard from "../components/HypothesisCard";
import WaferStrip from "../components/WaferStrip";
import { STATUS_LABELS, summaryLine } from "../labels";

// 판정별로 먼저 보여줄 건수. 실측 가설이 240~376건이라 전부 그리면 스크롤이 끝없이 길어진다.
// 받은 순서가 곧 중요도순(§2.5 정렬 불변식)이라 앞 N건이 상위 N건이다.
const PREVIEW_LIMIT = 3;

// 판단불가 세분류(reviewed 외) → unable-box 문구. 맵에 없는 신규 status는 아래 fallback.
const UNABLE_BOX: Partial<Record<AnalysisStatus, { mark: string; title: string }>> = {
  // 문구는 내부 분류명(OSR·NFF·매핑)이 아니라 "지금 무슨 상황이고 뭘 해야 하나"로 쓴다.
  unmapped: { mark: "?", title: "등록된 원인 정보가 없습니다 — 판독 결과까지만 제공" },
  novel: { mark: "!", title: "처음 보는 결함 형태입니다 — 로트 격리 후 전문가 재판독" },
  insufficient: { mark: "△", title: "원인을 확정하지 못했습니다 — 근거 부족" },
  // #69 — 저수율이지만 웨이퍼맵은 정상. "못 밝혔다"가 아니라 "결함이 없다"라서 마크도 다르다.
  normal_reading: { mark: "✓", title: "판독상 정상 — 결함 패턴 없음(수율 원인 별도 확인)" },
};

export default function ResultPage() {
  const { analysisId } = useParams<{ analysisId: string }>();
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedLot, setSelectedLot] = useState<string | null>(null);
  const [wafers, setWafers] = useState<LotWafers | null>(null);
  const [waferError, setWaferError] = useState<string | null>(null);
  const [modal, setModal] = useState<{ hypothesisId: string; cause: string } | null>(null);
  // 판정 버킷별 "더 보기" 상태 — 펼친 버킷만 담는다(기본은 전부 접힘).
  const [expanded, setExpanded] = useState<Set<Verdict>>(new Set());

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

  // 판정별 3버킷 — 실측상 가설이 240~376건까지 나와 전부 그리면 화면이 무한정 길어진다.
  // 각 버킷 상위 PREVIEW_LIMIT건만 먼저 보여주고 나머지는 "더 보기"로 펼친다(§2.5 정렬
  // 불변식대로 받은 순서가 곧 중요도순이라, 앞에서 자르는 것이 곧 상위 N건이다).
  const byVerdict: Record<Verdict, Hypothesis[]> = {
    accepted: [],
    rejected: [],
    judge_unknown: [],
  };
  for (const h of analysis.hypotheses) {
    (byVerdict[h.verdict] ?? byVerdict.rejected).push(h);
  }

  const visibleOf = (v: Verdict) =>
    expanded.has(v) ? byVerdict[v] : byVerdict[v].slice(0, PREVIEW_LIMIT);

  // R2(원인군 카드): 채택 가설을 cluster_id로 묶는다(등장 순서 보존). 같은 cluster_id는 fab
  // 증거가 동일한 원인군 — 그 안에서 단일 헤드라인을 뽑으면 문헌 근거 많은 generic 형제가
  // 정답을 덮으므로, 후보 묶음으로 함께 제시한다. cluster_id 없으면 단독 후보(__solo).
  // 묶는 대상은 "지금 보이는" 채택 가설뿐 — 더 보기를 누르면 그만큼 다시 묶인다.
  const clusterOrder: string[] = [];
  const clusterMap = new Map<string, Hypothesis[]>();
  for (const h of visibleOf("accepted")) {
    const key = h.cluster_id ?? `__solo_${h.hypothesis_id}`;
    if (!clusterMap.has(key)) {
      clusterMap.set(key, []);
      clusterOrder.push(key);
    }
    clusterMap.get(key)!.push(h);
  }

  /** 버킷 하단 "더 보기 / 접기" 버튼 — 남은 건수를 숫자로 알려 잘렸다는 사실을 숨기지 않는다. */
  const moreButton = (v: Verdict) => {
    const total = byVerdict[v].length;
    if (total <= PREVIEW_LIMIT) return null;
    const isOpen = expanded.has(v);
    return (
      <button
        className="ghost-btn"
        style={{ marginBottom: 12 }}
        onClick={() =>
          setExpanded((prev) => {
            const next = new Set(prev);
            next.has(v) ? next.delete(v) : next.add(v);
            return next;
          })
        }
      >
        {isOpen ? `접기 (상위 ${PREVIEW_LIMIT}건만 보기)` : `더 보기 (+${total - PREVIEW_LIMIT}건)`}
      </button>
    );
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <span>
          분석 결과 — {analysis.pattern} 그룹 ({analysis.lot_count} Lots) ·{" "}
          {STATUS_LABELS[analysis.status] ?? analysis.status}
        </span>
      </div>
      <div className="panel-body">
        {/* 이 한 줄이 무엇인지(사람이 쓴 게 아니라 AI 판독 결과) 라벨로 먼저 밝히고 줄을 바꾼다 */}
        <div className="box headline-box">
          <div className="headline-label">AI 분석결과</div>
          {headline}
        </div>

        <div className="box">
          <div className="box-title">
            <span>소속 로트 {analysis.lot_count}개</span>
            <span style={{ fontWeight: 400, color: "var(--text-dim)" }}>
              로트를 누르면 판독한 웨이퍼맵을 봅니다
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

        {analysis.status !== "reviewed" ? (
          (() => {
            // reviewed 외 상태(unmapped/novel/insufficient/그 외)는 판단불가 카드로 노출.
            const cfg =
              UNABLE_BOX[analysis.status] ?? {
                mark: "△",
                title: STATUS_LABELS[analysis.status] ?? "원인 미확정",
              };
            return (
              <div className="unable-box">
                <div className="mark">{cfg.mark}</div>
                <div className="title">{cfg.title}</div>
                <div className="desc">{analysis.reason}</div>
              </div>
            );
          })()
        ) : (
          <>
            {/* 불확실성은 **여기 한 곳에서만** 말한다. 예전에는 이 배너 + 제목 옆 "확신: 불확실"
                배지 + 원인군의 "하나로 좁혀지지 않음" 배지 + 그 아래 설명문까지 네 번 반복돼,
                정작 무엇이 원인 후보인지가 문구에 파묻혔다. */}
            <div className={analysis.confidence === "low" ? "conf-warn" : "conf-note"}>
              {analysis.confidence === "low" ? (
                <>
                  ⚠ <b>확정된 원인이 아닙니다.</b> 후보가 여럿이거나 뒷받침하는 설비 데이터가 약해
                  아직 하나로 좁혀지지 않았습니다 — 참고용으로만 활용하세요.
                </>
              ) : (
                <>
                  <b>확정된 원인이 아닙니다.</b> 아래 후보는 설비 데이터로 뒷받침되지만, 최종 판단은
                  엔지니어 몫입니다.
                </>
              )}
            </div>
            <div className="box-title" style={{ margin: "14px 0 10px" }}>
              <span>원인 후보 {byVerdict.accepted.length}건</span>
              {byVerdict.accepted.length > PREVIEW_LIMIT && (
                <span style={{ fontWeight: 400, color: "var(--text-dim)" }}>
                  유력한 순서로 {PREVIEW_LIMIT}건씩 표시
                </span>
              )}
            </div>
            {/* 같은 설비 증거를 공유하는 후보는 하나로 묶어 낸다(단일 헤드라인이 정답을 가리는
                문제 완화). 묶을 게 없는 단독 후보는 **껍데기 없이 카드만** 그린다 — 후보 1건짜리
                박스 제목은 아무 정보도 더하지 않으면서 화면만 두 겹으로 만든다. */}
            {clusterOrder.map((key) => {
              const members = clusterMap.get(key)!;
              const cards = members.map((h) => (
                <HypothesisCard
                  key={h.hypothesis_id}
                  hypothesis={h}
                  isTop={analysis.hypotheses[0]?.hypothesis_id === h.hypothesis_id}
                  onShowEvidence={(hypothesisId, cause) => setModal({ hypothesisId, cause })}
                />
              ));
              if (members.length === 1) return <div key={key}>{cards}</div>;
              return (
                <div key={key} className="box tie-group">
                  <div className="caption" style={{ marginTop: 0, marginBottom: 8 }}>
                    아래 {members.length}건은 설비 데이터상 구분되지 않습니다 — 함께 검토하세요.
                  </div>
                  {cards}
                </div>
              );
            })}
            {moreButton("accepted")}

            {/* 기각·미판정은 판정별로 나눠 각각 상위 PREVIEW_LIMIT건만. 섞어서 한 목록으로
                두면 "무엇이 왜 떨어졌는지"가 안 보이고, 건수가 많은 쪽이 화면을 삼킨다. */}
            {(["rejected", "judge_unknown"] as const).map((v) =>
              byVerdict[v].length === 0 ? null : (
                <div key={v}>
                  <div className="box-title" style={{ margin: "18px 0 10px" }}>
                    <span>
                      {v === "rejected" ? "검토 후 제외된 후보" : "판단 보류된 후보"}{" "}
                      {byVerdict[v].length}건
                    </span>
                    {byVerdict[v].length > PREVIEW_LIMIT && (
                      <span style={{ fontWeight: 400, color: "var(--text-dim)" }}>
                        {PREVIEW_LIMIT}건씩 표시
                      </span>
                    )}
                  </div>
                  {visibleOf(v).map((h) => (
                    <HypothesisCard
                      key={h.hypothesis_id}
                      hypothesis={h}
                      isTop={false}
                      onShowEvidence={(hypothesisId, cause) => setModal({ hypothesisId, cause })}
                    />
                  ))}
                  {moreButton(v)}
                </div>
              ),
            )}
          </>
        )}

        {/* 권장 조치(§2.5 actions) — 모든 상태 공통. novel/insufficient도 investigation
            조치가 올 수 있으므로 status와 무관하게 actions가 있으면 노출한다(OCAP). */}
        {analysis.actions.length > 0 && (
          <>
            <div className="box-title" style={{ margin: "20px 0 6px" }}>
              <span>권장 조치</span>
              <span style={{ fontWeight: 400, color: "var(--text-dim)" }}>
                제안일 뿐이며 실행 여부는 엔지니어가 판단합니다 · 항목을 누르면 완료 체크
              </span>
            </div>
            <div className="box">
              <ActionList actions={analysis.actions} />
            </div>
          </>
        )}
      </div>
      <div className="foot-note">
        각 후보의 "설비 데이터 근거 보기"를 누르면 공통 장비 · 센서값 추이 · 정비/알람 이력을
        확인할 수 있습니다.
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
