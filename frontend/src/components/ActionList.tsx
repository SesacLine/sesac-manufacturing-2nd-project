/** 권장 조치(§2.5 actions) — OCAP 취지로 type별 그룹(격리→시정→예방→추가조사) 렌더.
 *  type 키는 서버 enum, 한국어 라벨은 ACTION_TYPE_LABELS(프론트 소유). hold=true는 즉시
 *  격리 성격 → 그룹 헤더 강조 + 항목 Hold 태그. 항목 클릭 = 완료 체크(로컬 UI 상태만). */

import { useState } from "react";
import type { ActionType, RecommendedAction } from "../api/types";
import { ACTION_TYPE_LABELS } from "../labels";

// 표시 순서 고정 — 서버가 어떤 순서로 주든 OCAP 순서로 묶는다.
const TYPE_ORDER: ActionType[] = ["containment", "corrective", "preventive", "investigation"];

export default function ActionList({ actions }: { actions: RecommendedAction[] }) {
  // 완료 체크는 순수 표시용 로컬 상태(서버 반영 없음) — 인덱스로 식별.
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const toggle = (i: number) =>
    setChecked((prev) => {
      const next = new Set(prev);
      next.has(i) ? next.delete(i) : next.add(i);
      return next;
    });

  if (actions.length === 0) {
    return <div style={{ fontSize: 11, color: "var(--text-dim)" }}>권장 조치 없음</div>;
  }

  // 원본 인덱스를 유지한 채 type별로 묶는다(체크 상태 식별 안정성).
  const indexed = actions.map((a, i) => ({ a, i }));
  return (
    <>
      {TYPE_ORDER.map((type) => {
        const group = indexed.filter(({ a }) => a.type === type);
        if (group.length === 0) return null;
        const anyHold = group.some(({ a }) => a.hold);
        return (
          <div key={type} className="act-group">
            <div className={anyHold ? "act-ghead hold" : "act-ghead"}>
              {ACTION_TYPE_LABELS[type] ?? type}
            </div>
            {group.map(({ a, i }) => (
              <div
                key={i}
                className={checked.has(i) ? "action-item checked" : "action-item"}
                onClick={() => toggle(i)}
              >
                <span className="chk" />
                <span className="txt">{a.text}</span>
                {a.hold && <span className="hold-tag">Hold</span>}
              </div>
            ))}
          </div>
        );
      })}
    </>
  );
}
