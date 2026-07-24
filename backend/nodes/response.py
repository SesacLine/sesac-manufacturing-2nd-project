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
    - 각 원소에 verdict("accepted"/"rejected"/"judge_unknown")를 싣는다 — 기각 사유의
      고정 토큰(critic.py) 중 judge_unknown 계열(P5_NO_KG_MECHANISM·SEMI_AUTO_PENDING·
        NOT_INVESTIGATED)만 verdict="judge_unknown"으로 승격(자연어 매칭 금지, hypo_critic_py.md §13-1 C1·C2).
      (그룹 status의 "insufficient"와는 다른 층 — verdict는 가설 1건, status는 그룹 전체.)
    - 그룹 status("reviewed"/"insufficient"/"unmapped")와 reason·lot_ids·lot_count를 싣는다.
    tier/pattern enum 영문 변환은 여기서 하지 않는다 — API 경계(schemas.py/api) 소관.
"""

from __future__ import annotations

from ..state import GroupState
from .critic import TOKEN_NO_KG_MECHANISM, TOKEN_SEMI_AUTO_PENDING, TOKEN_NOT_INVESTIGATED

# judge_unknown(미조사·근거없음) → verdict="judge_unknown". 나머지 사유는 "rejected".
# NOT_INVESTIGATED = 자동 tier의 미조사 폴백(S2-6) — 반자동 SEMI_AUTO_PENDING과 같은 보류 버킷.
_JUDGE_UNKNOWN_TOKENS = {TOKEN_NO_KG_MECHANISM, TOKEN_SEMI_AUTO_PENDING, TOKEN_NOT_INVESTIGATED}

# ── 사용자 노출용 그룹 서술(description, API 명세 §2.5) ──────────────────────────────
# 설계 결정: VLM(노드③)은 **영어 서술만** 생성하고(프롬프트 단순·출력 자연스러움), 한국어 번역은
# 이 응답 단계에서 한다. 번역기(translate: str→str)는 조립 시점 partial로 주입된다
# (graph.py ← deps.response_translator, RESPONSE_LLM=1일 때만 실체·아니면 None).
#   · VLM 실생성 판별 = 관측 메타 `vlm_track` 존재(VLM_LIVE 경로 성공 시에만 붙는다).
#   · 스켈레톤/결정적 폴백 문구는 지어낸 값이라 **노출 금지 → None**(프론트가 summary_line으로
#     fallback, §2.5 동작 그대로). 즉 vlm_track이 없으면 무조건 None.
#   · translate 미주입(기본/CI)이면 원문(영어)을 그대로 운반 — 결정적, LLM 비용 0.
#   · 번역 실패는 원문(영어)으로 폴백 — 실제 관측 내용을 잃지 않게(곱게 무너짐).


def _group_description(state: GroupState, translate=None) -> str | None:
    """§2.5 description — VLM이 실제로 생성한 그룹 서술만 (번역해) 운반한다(없으면 None)."""
    obs = state.get("observation") or {}
    if not obs.get("vlm_track"):  # VLM 실생성 아님(스켈레톤/폴백) → 노출 금지
        return None
    english = obs.get("total_description")
    if not english or translate is None:  # 번역기 미주입 → 원문 운반(결정적)
        return english
    try:
        return translate(english)
    except Exception:  # noqa: BLE001 — 번역 실패해도 원문 보존(내용 유지)
        return english


def _ordered_hypotheses(critic: dict | None) -> list[dict]:
    """critic_result를 §2.5 정렬 불변식대로 배열화한다 — 대표(accepted[0])를 index 0에,
    각 원소에 verdict/verdict_reason, 정렬 확정 뒤 h{n} 부여.

    ⑦(reviewed)과 ⑦'(insufficient)이 이 헬퍼를 공유해 두 경로의 배열이 어긋나지 않게 한다
    (골격설계 §5.2.1). 정렬 전에 h{n}을 매기면 h0가 대표가 아니게 되므로 순서 확정 뒤에 매긴다.
    """
    accepted = list(critic["accepted"]) if critic else []
    non_accepted = list(critic["rejected"]) if critic else []

    ordered: list[dict] = []
    for h in accepted:
        ordered.append({**h, "verdict": "accepted", "verdict_reason": None})
    for h in non_accepted:
        verdict = "judge_unknown" if h.get("reject_token") in _JUDGE_UNKNOWN_TOKENS else "rejected"
        ordered.append({**h, "verdict": verdict, "verdict_reason": h.get("reject_reason")})
    for n, h in enumerate(ordered):
        h["hypothesis_id"] = f"h{n}"
    return ordered


def generate_response(state: GroupState, translate=None) -> dict:
    """채택 가설이 있는 그룹의 최종 카드를 조립한다(UC-1, status="reviewed").

    후보 0건/채택 0건 분기는 라우팅(route_on_candidates·route_on_verdicts)이 갈라 ⑦'로 보내므로
    여기 오지 않는다 — 이 함수는 채택 ≥1만 처리한다(골격설계 §6). summary는 결정론적 템플릿(내부용,
    LLM 아님 — 확정). translate는 조립 시점 partial로 주입되는 영어→한국어 번역기(없으면 원문 운반)
    — description에만 쓴다.
    """
    pattern = state["pattern"]
    lot_ids = list(state["lot_ids"])

    critic = state.get("critic_result")
    ordered = _ordered_hypotheses(critic)
    accepted = list(critic["accepted"]) if critic else []

    lines = [
        f"- {h['cause']} (등급: {h['tier']}, 의심 장비: {h['equipment']})" for h in accepted
    ]
    summary = f"{pattern} 패턴 — 가설 {len(accepted)}건 채택:\n" + "\n".join(lines)
    return _final(
        state["group_id"], pattern, lot_ids,
        status="reviewed", reason=None, hypotheses=ordered, summary=summary,
        description=_group_description(state, translate),
    )


def respond_without_llm(state: GroupState, translate=None) -> dict:
    """LLM을 부르지 않는 응답 — 후보 0건(UC-3)/채택 0건(UC-2) 두 경우를 만든다(골격설계 §5.2·§5.2.1).

    라우팅이 이 노드로 보낸 케이스만 처리한다: candidates가 비면 unmapped(hypotheses=[]),
    아니면 insufficient(⑦과 동일 헬퍼로 정렬 배열+h{n}+verdict 재현 — 근거 모달이 hypothesis_id로
    열려야 하므로 반드시 배열을 채운다, §2.7). description은 두 경우 모두 카드에 실어 보낸다
    (translate는 그 번역용 — 관측 옮기기라 "LLM 미사용" 불변식과 충돌 아님, 원인 생성은 여전히 없음).
    """
    group_id = state["group_id"]
    pattern = state["pattern"]
    lot_ids = list(state["lot_ids"])
    description = _group_description(state, translate)

    # UC-3: 애초에 KG 매핑 대상(Center/Edge-Ring/Scratch) 밖이라 후보가 없던 그룹.
    if not state.get("candidates"):
        return _final(
            group_id,
            pattern,
            lot_ids,
            status="unmapped",
            reason="이 결함 패턴은 원인 매핑 데이터가 없어 판독까지만 지원됩니다.",
            hypotheses=[],
            summary=f"{pattern} 패턴은 원인 분석 데이터가 없습니다(KG 매핑 대상 3종 밖).",
            description=description,
        )

    # UC-2: 후보는 있었지만 Critic이 하나도 채택 못 한 경우 — 판단 불가(근거부족).
    critic = state.get("critic_result")
    ordered = _ordered_hypotheses(critic)
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
        description=description,
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
    description: str | None,
) -> dict:
    return {
        "final_response": {
            "group_id": group_id,
            "pattern": pattern,
            "status": status,          # reviewed | insufficient | unmapped (§2.2/§2.5)
            "reason": reason,
            "lot_ids": lot_ids,
            "lot_count": len(lot_ids),
            "hypotheses": hypotheses,  # 정렬·h{n}·verdict 포함 (대표 = index 0)
            "summary": summary,        # 결정론적 템플릿(내부용, LLM 아님)
            "description": description,  # ③VLM(영어) → 한국어 번역, §2.5 (없으면 None → 프론트 summary_line)
        }
    }
