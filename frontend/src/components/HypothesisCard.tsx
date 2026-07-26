/** §2.5 가설 카드 — 받은 순서 그대로(index 0 = 대표, 재정렬 금지),
 *  cause는 열린 문자열이라 raw 그대로, verdict/tier는 라벨 매핑(없으면 raw). */

import type { Hypothesis } from "../api/types";
import { TIER_LABELS, VERDICT_LABELS } from "../labels";

export default function HypothesisCard({
  hypothesis,
  isTop,
  onShowEvidence,
}: {
  hypothesis: Hypothesis;
  isTop: boolean;
  onShowEvidence: (hypothesisId: string, cause: string) => void;
}) {
  const h = hypothesis;
  const accepted = h.verdict === "accepted";
  // 채택 카드는 확률/확정 대신 "채택 유력(대표)"·"보조 가설" 플래그로 표기(v8·R1).
  // 기각·미판정은 verdict 라벨(✖ 기각 / △ 미판정)을 그대로 쓴다.
  const flag = accepted
    ? isTop
      ? { cls: "adopt-flag", text: "✔ 채택 유력" }
      : { cls: "adopt-flag rej", text: "△ 보조 가설" }
    : { cls: "adopt-flag rej", text: VERDICT_LABELS[h.verdict] ?? h.verdict };
  return (
    <div className={isTop && accepted ? "hcard top" : "hcard"}>
      <div className="h-row1">
        <div>
          <div className="h-name">{h.cause}</div>
          <div className="h-stage">
            공정 단계: {h.stage ?? "공정 미상"} · {TIER_LABELS[h.tier] ?? h.tier}
          </div>
        </div>
        <span className={flag.cls}>{flag.text}</span>
      </div>
      <div className="h-narr">{h.narrative}</div>
      {h.verdict_reason && (
        <div className="caption" style={{ marginTop: 6 }}>
          사유: {h.verdict_reason}
        </div>
      )}
      {h.next_actions.length > 0 && (
        <div className="caption" style={{ marginTop: 6 }}>
          권장 조치: {h.next_actions.join(" · ")}
        </div>
      )}
      <div className="h-foot">
        <span className="caption">
          {h.citations.length > 0
            ? h.citations.map((c) => `[${c.id}] ${c.text}`).join(" · ")
            : "인용 없음"}
        </span>
        <button className="ghost-btn" onClick={() => onShowEvidence(h.hypothesis_id, h.cause)}>
          근거 보기
        </button>
      </div>
    </div>
  );
}
