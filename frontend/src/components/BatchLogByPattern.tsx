/** 배치 로그를 결함 패턴별로 접어 보여준다(화면2 완료 후). 2단계 토글: 패턴 > 도구.
 *
 *  왜 "도구"로 2단계를 나누나 — 와이어프레임 v9는 단계2(후보검색)/단계3(증거수집)/단계4(검증)로
 *  나눴지만, 실제 로그는 전부 ⑤ Hypothesis의 MCP 호출이다(실측 572건 = 6개 도구 전부 ⑤ 소관).
 *  ④ KG조회·⑥ Critic·⑦ 응답은 MCP를 안 써서 로그가 없다 — 단계축으로 나누면 한 칸에 전부
 *  몰리고 나머지는 빈다. 그래서 v9의 2단계 구조와 밀도는 유지하되 축만 실재하는 값(도구)으로
 *  바꿨다. "무슨 근거를 몇 번 확인했나"가 드러나 의미도 더 산다.
 *
 *  패턴은 message 앞머리의 "[패턴]" 태그에서 읽는다(backend/batch_runner.py `_tag_message`가
 *  run_groups 구간에서 contextvars로 붙인다). 태그가 없는 로그(⓪~③ 배치 레벨·파이프라인 오류)는
 *  "공통" 묶음으로 따로 낸다 — 조용히 버리면 배치 실패 로그가 화면에서 사라진다.
 */

import type { BatchLogEntry } from "../api/types";
import { TOOL_LABELS, batchLogPatternLabel } from "../labels";

const COMMON = "공통";

/** "[Edge-Ring] lot44170" → { pattern: "Edge-Ring", body: "lot44170" } */
function parseTag(message: string): { pattern: string; body: string } {
  const m = /^\[([^\]]+)\]\s*/.exec(message);
  return m ? { pattern: m[1], body: message.slice(m[0].length) } : { pattern: COMMON, body: message };
}

type Row = BatchLogEntry & { body: string };

export default function BatchLogByPattern({ logs }: { logs: BatchLogEntry[] }) {
  if (logs.length === 0) {
    return <div className="na-note">로그가 없습니다.</div>;
  }

  // 패턴 → 도구 → 로그. 등장 순서를 보존한다(시간순 = 파이프라인 진행 순).
  const byPattern = new Map<string, Map<string, Row[]>>();
  for (const log of logs) {
    const { pattern, body } = parseTag(log.message);
    if (!byPattern.has(pattern)) byPattern.set(pattern, new Map());
    const byTool = byPattern.get(pattern)!;
    if (!byTool.has(log.tool)) byTool.set(log.tool, []);
    byTool.get(log.tool)!.push({ ...log, body });
  }

  // "공통"은 배치 전체 맥락이라 맨 위로 올린다(패턴별 상세보다 먼저 읽어야 한다).
  const patterns = [...byPattern.keys()].sort((a, b) =>
    a === COMMON ? -1 : b === COMMON ? 1 : 0,
  );

  return (
    <>
      {patterns.map((pattern) => {
        const byTool = byPattern.get(pattern)!;
        const total = [...byTool.values()].reduce((n, rows) => n + rows.length, 0);
        const errors = [...byTool.values()]
          .flat()
          .filter((r) => r.status === "error").length;
        return (
          <details key={pattern} className="acc">
            <summary>
              <span className="pat-name">{batchLogPatternLabel(pattern)}</span>
              {errors > 0 && <span className="badge warn">오류 {errors}건</span>}
              <span className="tw">
                도구 {byTool.size}종 · {total}건
              </span>
            </summary>
            <div className="acc-body">
              {[...byTool.entries()].map(([tool, rows]) => (
                <details key={tool} className="acc" style={{ margin: "4px 0" }}>
                  <summary style={{ fontSize: 12.5, padding: "7px 10px", fontWeight: 600 }}>
                    {TOOL_LABELS[tool] ?? tool}
                    <span className="tw">{rows.length}건</span>
                  </summary>
                  <div className="acc-body" style={{ padding: "6px 10px" }}>
                    <div className="minilog">
                      {rows.map((r, i) => (
                        <div key={i}>
                          [{r.time}] {r.body}{" "}
                          {r.status === "done" && <span className="ok">✓</span>}
                          {r.status === "running" && <span className="run">…</span>}
                          {r.status === "error" && <span className="err">✗ 오류</span>}
                        </div>
                      ))}
                    </div>
                  </div>
                </details>
              ))}
            </div>
          </details>
        );
      })}
    </>
  );
}
