/** §2.5 원인 후보 카드 — 받은 순서 그대로(index 0 = 대표, 재정렬 금지).
 *
 *  카드 안에서 같은 말을 두 번 하지 않는 것이 이 컴포넌트의 규칙이다. 판정(채택/제외/보류)은
 *  플래그 한 곳에서만 말하고, 불확실성은 화면 상단 배너가 한 번만 말한다(ResultPage).
 *  cause는 한국어 gloss로 찍고 원문 id는 tooltip으로만 남긴다 — KG·평가 대조 키가 원문이라
 *  접근은 가능해야 하지만, 카드 본문에 노출하면 읽는 흐름을 끊는다.
 */

import type { Hypothesis } from "../api/types";
import { causeLabel, citationLabel, TIER_LABELS, VERDICT_LABELS } from "../labels";

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
  // 채택 카드는 확률/확정 대신 "채택 유력(대표)"·"보조 후보" 플래그로 표기(v8·R1).
  // 제외·보류는 verdict 라벨을 그대로 쓴다.
  const flag = accepted
    ? isTop
      ? { cls: "adopt-flag", text: "✔ 가장 유력" }
      : { cls: "adopt-flag rej", text: "보조 후보" }
    : { cls: "adopt-flag rej", text: VERDICT_LABELS[h.verdict] ?? h.verdict };
  return (
    <div className={isTop && accepted ? "hcard top" : "hcard"}>
      <div className="h-row1">
        <div>
          {/* 원문 KG id는 tooltip으로만 — 본문에 병기하면 한 줄에 같은 원인이 두 번 나온다 */}
          <div className="h-name" title={h.cause}>
            {causeLabel(h.cause)}
          </div>
          <div className="h-stage">
            {h.stage ? `${h.stage} 공정` : "공정 미상"} · {TIER_LABELS[h.tier] ?? h.tier}
          </div>
        </div>
        <span className={flag.cls}>{flag.text}</span>
      </div>
      <div className="h-narr">{h.narrative}</div>
      {h.verdict_reason && (
        <div className="caption" style={{ marginTop: 6 }}>
          제외 사유: {h.verdict_reason}
        </div>
      )}
      {h.next_actions.length > 0 && (
        <div className="caption" style={{ marginTop: 6 }}>
          권장 조치: {h.next_actions.join(" · ")}
        </div>
      )}
      <div className="h-foot">
        {/* 출처는 파일 id가 아니라 문헌 이름으로. 번호([1][2])는 본문이 참조하지 않으므로 뺀다 */}
        <span className="caption">
          {h.citations.length > 0
            ? `문헌 근거 · ${h.citations.map((c) => citationLabel(c.text)).join(" · ")}`
            : "문헌 근거 없음"}
        </span>
        <button className="ghost-btn" onClick={() => onShowEvidence(h.hypothesis_id, h.cause)}>
          설비 데이터 근거 보기
        </button>
      </div>
    </div>
  );
}
