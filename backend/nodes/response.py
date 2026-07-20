"""⑥(코드)/⑦(명세) 응답생성. 파이프라인에서 실시간으로 LLM을 호출하는 두 노드 중 하나(다른 하나는 ①VLM).

critic_result + graphrag_candidates(인용 재사용)로 최종 카드를 만든다.
Root Cause "확정"이 아니라 "가설(채택) + 근거"까지가 스코프다(산출물_mvp설계서.md §2).
판단불가/미매핑 패턴 케이스는 일반 결과와 구분되는 형태로 표시한다(UC-2, UC-3).

2026-07-20 확장(API 명세 §2.5 정렬 불변식):
    - hypotheses[]를 "대표 accepted가 index 0"이 되도록 정렬해 내보낸다.
      대표 선정 규칙(§4-1 잠정, docs/BACKEND_DECISIONS.md D1): accepted 중 kg_rca 후보 순위
      (hypotheses.json rank = candidates 배열 순서) 최상위 1건. Critic이 순서를 보존하므로
      accepted[0]이 곧 대표다. 나머지는 accepted 원순서 → 비채택 원순서로 잇는다.
    - 정렬 확정 **뒤** 배열 인덱스로 hypothesis_id("h{n}")를 부여한다(§2.5/§2.7 드릴다운 키).
    - 각 원소에 verdict("accepted"/"rejected"/"insufficient")를 싣는다 — 기각 사유의
      고정 토큰(critic.py) 중 P5_NO_KG_MECHANISM만 insufficient로 승격(자연어 매칭 금지).
    - 그룹 status("reviewed"/"insufficient"/"unmapped")와 reason·lot_ids·lot_count를 싣는다.
    tier/pattern enum 영문 변환은 여기서 하지 않는다 — API 경계(schemas.py/api) 소관.
"""

from __future__ import annotations

from ..state import RCAState
from .critic import TOKEN_NO_KG_MECHANISM

# TODO(Walking Skeleton, 스텝7에서 교체 대상): summary를 LLM으로 자연어 합성하는 대신
# 결정적 템플릿 문자열로 채운다 — 전체 배선을 LLM 비용 없이 먼저 검증하기 위함.
# description(그룹 대표 VLM 서술, §2.5)도 VLM 미연동 동안 None이다(프론트 summary_line fallback).


def generate_response(state: RCAState, group_id: str) -> dict:
    """critic_result[group_id]를 바탕으로 final_response[group_id]를 채운다."""
    group = next((g for g in state["groups"] if g["group_id"] == group_id), None)
    pattern = group["pattern"] if group else "unknown"
    lot_ids = list(group["lot_ids"]) if group else []
    graphrag_result = state["graphrag_candidates"].get(group_id)

    # UC-3: 애초에 KG 매핑 대상(Center/Edge-Ring/Scratch) 밖이라 후보가 없던 그룹.
    if not graphrag_result or not graphrag_result["candidates"]:
        return _final(
            group_id,
            pattern,
            lot_ids,
            status="unmapped",
            reason="이 결함 패턴은 원인 매핑 데이터가 없어 판독까지만 지원됩니다.",
            hypotheses=[],
            summary=f"{pattern} 패턴은 원인 분석 데이터가 없습니다(KG 매핑 대상 3종 밖).",
        )

    critic = state["critic_result"].get(group_id)
    accepted = list(critic["accepted"]) if critic else []
    non_accepted = list(critic["rejected"]) if critic else []

    # §2.5 정렬 불변식: 대표(accepted 중 kg_rca 순위 최상위 = accepted[0])를 index 0에.
    ordered: list[dict] = []
    for h in accepted:
        ordered.append({**h, "verdict": "accepted", "verdict_reason": None})
    for h in non_accepted:
        verdict = "insufficient" if h.get("reject_token") == TOKEN_NO_KG_MECHANISM else "rejected"
        ordered.append({**h, "verdict": verdict, "verdict_reason": h.get("reject_reason")})
    # 정렬 확정 뒤에 h{n} 부여 (§2.5 — 정렬 전에 매기면 h0가 대표가 아니게 된다).
    for n, h in enumerate(ordered):
        h["hypothesis_id"] = f"h{n}"

    # UC-2: 후보는 있었지만 Critic이 하나도 채택 못 한 경우 — 판단 불가(근거부족).
    if not accepted:
        return _final(
            group_id,
            pattern,
            lot_ids,
            status="insufficient",
            reason=(
                "매핑된 원인 후보는 있으나 시간 정합·정상 로트 대조에서 "
                "채택 가능한 후보가 없어 판단 불가(근거부족)."
            ),
            hypotheses=ordered,
            summary=f"{pattern} 패턴은 판단 불가 — 채택 가능한 근거 있는 가설이 없습니다.",
        )

    # 정상 흐름(UC-1): 채택된 가설 + 근거를 카드로 조립.
    lines = [
        f"- {h['cause']} (등급: {h['tier']}, 의심 장비: {h['equipment']})" for h in accepted
    ]
    summary = f"{pattern} 패턴 — 가설 {len(accepted)}건 채택:\n" + "\n".join(lines)
    return _final(
        group_id, pattern, lot_ids,
        status="reviewed", reason=None, hypotheses=ordered, summary=summary,
    )


def _final(
    group_id: str,
    pattern: str,
    lot_ids: list[str],
    *,
    status: str,
    reason: str | None,
    hypotheses: list[dict],
    summary: str,
) -> dict:
    return {
        "final_response": {
            group_id: {
                "group_id": group_id,
                "pattern": pattern,
                "status": status,          # reviewed | insufficient | unmapped (§2.2/§2.5)
                "reason": reason,
                "lot_ids": lot_ids,
                "lot_count": len(lot_ids),
                "hypotheses": hypotheses,  # 정렬·h{n}·verdict 포함 (대표 = index 0)
                "summary": summary,
            }
        }
    }
