"""⑥ 응답생성. 파이프라인에서 실시간으로 LLM을 호출하는 두 노드 중 하나(다른 하나는 ①VLM).

critic_result + graphrag_candidates(인용 재사용)로 최종 카드를 만든다.
Root Cause "확정"이 아니라 "가설(채택) + 근거"까지가 스코프다(산출물_mvp설계서.md §2).
판단불가/미매핑 패턴 케이스는 일반 결과와 구분되는 형태로 표시한다(UC-2, UC-3).
"""

from __future__ import annotations

from ..state import RCAState

# TODO(Walking Skeleton, 스텝7에서 교체 대상): summary를 LLM으로 자연어 합성하는 대신
# 결정적 템플릿 문자열로 채운다 — ⓪~⑥ 전체 배선을 LLM 비용 없이 먼저 검증하기 위함.


def generate_response(state: RCAState, group_id: str) -> dict:
    """critic_result[group_id]를 바탕으로 final_response[group_id]를 채운다."""
    group = next((g for g in state["groups"] if g["group_id"] == group_id), None)
    pattern = group["pattern"] if group else "unknown"
    graphrag_result = state["graphrag_candidates"].get(group_id)

    # UC-3: 애초에 KG 매핑 대상(Center/Edge-Ring/Scratch) 밖이라 후보가 없던 그룹.
    if not graphrag_result or not graphrag_result["candidates"]:
        return {
            "final_response": {
                group_id: {
                    "group_id": group_id,
                    "pattern": pattern,
                    "hypotheses": [],
                    "rejected": [],
                    "summary": f"{pattern} 패턴은 원인 분석 데이터가 없습니다(KG 매핑 대상 3종 밖).",
                }
            }
        }

    critic = state["critic_result"].get(group_id)

    # UC-2: 후보는 있었지만 Critic이 하나도 채택 못 한 경우 — 판단 불가.
    if critic is None or critic["status"] == "insufficient_evidence":
        return {
            "final_response": {
                group_id: {
                    "group_id": group_id,
                    "pattern": pattern,
                    "hypotheses": [],
                    "rejected": critic["rejected"] if critic else [],
                    "summary": f"{pattern} 패턴은 판단 불가 — 채택 가능한 근거 있는 가설이 없습니다.",
                }
            }
        }

    # 정상 흐름(UC-1): 채택된 가설 + 근거를 카드로 조립.
    lines = [
        f"- {h['cause']} (등급: {h['tier']}, 의심 장비: {h['equipment']})" for h in critic["accepted"]
    ]
    summary = f"{pattern} 패턴 — 가설 {len(critic['accepted'])}건 채택:\n" + "\n".join(lines)

    return {
        "final_response": {
            group_id: {
                "group_id": group_id,
                "pattern": pattern,
                "hypotheses": critic["accepted"],
                "rejected": critic["rejected"],
                "summary": summary,
            }
        }
    }
