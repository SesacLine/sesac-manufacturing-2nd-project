/** 권장 조치(§2.5 actions) — OCAP 취지로 type별 그룹(격리→시정→예방→추가조사) 렌더.
 *  type 키는 서버 enum, 한국어 라벨은 ACTION_TYPE_LABELS(프론트 소유). hold=true는 즉시
 *  격리 성격 → 그룹 헤더 강조 + 항목 Hold 태그. 항목 클릭 = 완료 체크.
 *
 *  체크 상태는 **브라우저(localStorage)에 분석별로 남긴다.** 예전엔 useState뿐이라 화면을
 *  벗어나는 순간 사라졌다 — 조치를 확인하고 대기열로 돌아왔다 다시 들어오면 전부 초기화됐다.
 *
 *  왜 서버가 아니라 localStorage인가 — 이건 "이 담당자가 어디까지 처리했나"라는 **개인 작업
 *  상태**이지 서버가 소유한 분석 결과가 아니다. API 계약(v2.0 10종)을 늘리지 않아도 되고,
 *  한 사람의 체크가 다른 사람 화면을 바꾸지도 않는다.
 *  대시보드에서 batch_id를 localStorage에서 걷어낸 적이 있는데(DashboardPage 주석), 그건
 *  **서버에 진실이 있는 값**을 브라우저에 둬서 다른 기기·새로고침에서 안 보이던 문제였다.
 *  여기는 반대로 서버에 둘 진실이 없다 — 같은 실수가 아니다.
 */

import { useEffect, useState } from "react";
import type { ActionType, RecommendedAction } from "../api/types";
import { ACTION_TYPE_LABELS } from "../labels";

// 표시 순서 고정 — 서버가 어떤 순서로 주든 OCAP 순서로 묶는다.
const TYPE_ORDER: ActionType[] = ["containment", "corrective", "preventive", "investigation"];

/** 저장 키. 분석별로 갈라야 A의 조치 체크가 B로 새지 않는다. v1은 저장 포맷 버전. */
const storageKey = (analysisId: string) => `waefer:action-checks:v1:${analysisId}`;

/** 항목 식별자 — 인덱스가 아니라 **내용**으로 잡는다. 배치를 다시 돌려 조치 순서나 개수가
 *  바뀌어도 이미 체크한 항목이 엉뚱한 줄로 옮겨가지 않는다(인덱스 기반이 갖는 실패 모드). */
const actionKey = (a: RecommendedAction) => `${a.type}::${a.text}`;

/** localStorage는 사생활 보호 모드·용량 초과·정책 차단에서 던진다. 체크 표시는 부가 기능이라
 *  여기서 실패해도 조치 목록 자체는 그대로 보여야 한다 — 조용히 무시하고 빈 상태로 간다. */
function loadChecked(analysisId: string): Set<string> {
  try {
    const raw = window.localStorage.getItem(storageKey(analysisId));
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((x): x is string => typeof x === "string"));
  } catch {
    return new Set();
  }
}

function saveChecked(analysisId: string, checked: Set<string>): void {
  try {
    window.localStorage.setItem(storageKey(analysisId), JSON.stringify([...checked]));
  } catch {
    /* 저장 실패는 무시 — 이번 세션 동안은 화면 상태로만 유지된다 */
  }
}

export default function ActionList({
  actions,
  analysisId,
}: {
  actions: RecommendedAction[];
  analysisId: string;
}) {
  const [checked, setChecked] = useState<Set<string>>(() => loadChecked(analysisId));

  // 같은 화면에서 다른 분석으로 갈아타면(라우트 파라미터만 바뀌고 컴포넌트는 유지) 그 분석의
  // 저장분을 다시 읽는다. 안 하면 앞 분석의 체크가 남아 보인다.
  useEffect(() => {
    setChecked(loadChecked(analysisId));
  }, [analysisId]);

  const toggle = (a: RecommendedAction) => {
    const key = actionKey(a);
    setChecked((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      saveChecked(analysisId, next);
      return next;
    });
  };

  if (actions.length === 0) {
    return <div style={{ fontSize: 12.5, color: "var(--text-dim)" }}>권장 조치 없음</div>;
  }

  // 원본 인덱스는 렌더 key로만 쓴다(체크 식별은 위 actionKey 담당).
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
                className={checked.has(actionKey(a)) ? "action-item checked" : "action-item"}
                onClick={() => toggle(a)}
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
