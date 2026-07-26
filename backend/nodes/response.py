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

# ── R1: 확신 수준(불확실 표시) ─────────────────────────────────────────────────────────
# 판정 층(⑤/⑥)이 못 거른 환각을 표현 층에서 완화한다(eval_scenario_kg_proposal.md R1·B1).
# 미지 결함(정답 KG에 없음)은 과채택으로 "채택 0건" 가드가 발화 못 해 status=reviewed로 나오는데,
# 그럴 때 "이것이 근본 원인"이라 단정하지 않도록 confidence를 함께 내보낸다.
#   · 절대 "high"(확정)를 내지 않는다 — RCA 스코프는 "가설(채택)+근거"까지지 확정이 아니다.
#   · 재료는 이미 넘어온 evidence만 읽는다 — 새 증거를 만들지 않는다(faithfulness firewall).
#   · "medium" = 후보가 소수로 좁혀졌고 그중 fab 증거로 적극 지지되는 가설이 있음.
#   · "low"    = 채택이 다수(좁히지 못함)이거나 적극 지지 증거가 없음 → "단정하지 않음".
_MANY_ACCEPTED = 3           # 채택이 이 수를 넘으면 "좁히지 못함"(불확실) 신호
_NORMAL_RATIO_WEAK = 0.5     # assembler._NORMAL_RATIO_WEAK_THRESHOLD와 같은 임계(정상비율 이상=반대근거 강함)


def _has_strong_support(h: dict) -> bool:
    """채택 가설 1건이 fab 증거로 '적극 지지'되는가 — 방향일치 drift 또는 반대근거 약함."""
    ev = h.get("evidence") or {}
    # 자동 tier: drift가 KG 예상 방향과 일치(direction_match=True)하면 적극 지지.
    if ev.get("drift_detected") and ev.get("direction_match"):
        return True
    # 정상 로트 대조에서 반대근거가 약하면(정상비율이 임계 미만) 지지.
    nr = ev.get("normal_ratio")
    if nr is not None and nr < _NORMAL_RATIO_WEAK:
        return True
    return False


def _confidence(accepted: list[dict]) -> str:
    """'medium'(잠정 지지) / 'low'(불확실). 확정('high')은 내지 않는다(R1)."""
    if not accepted:
        return "low"
    strong = sum(1 for h in accepted if _has_strong_support(h))
    if strong >= 1 and len(accepted) <= _MANY_ACCEPTED:
        return "medium"
    return "low"


# ── 권장 조치(구조화, 와이어프레임 v8 정합) ────────────────────────────────────────────
# OCAP 취지의 3+1 분류: containment(격리)/corrective(시정)/preventive(예방)/investigation(조사).
# type은 영문 enum(§3 vocabulary 노선 — 라벨은 프론트 소유), text는 사용자 노출 한국어.
# hold=True는 "로트 Hold·격리" 성격의 즉시 조치 표시. 전부 결정론적 템플릿(LLM 아님) —
# AI 제안일 뿐 실행은 엔지니어 판단(와이어프레임 문구와 동일 스탠스).


def group_actions(status: str, pattern: str, lot_count: int, top: dict | None) -> list[dict]:
    """그룹(분석) 단위 권장 조치 목록. status와 대표 채택 가설(top)에서 결정론적으로 만든다.

    공개 이름인 이유: ⑦ 노드를 타지 않는 normal_reading(#69)도 batch_runner가 이 함수를 불러
    조치 템플릿을 만든다 — 조치 문구의 단일 소스를 유지하기 위해서다.
    """
    hold = {
        "type": "containment",
        "hold": True,
        "text": f"영향 로트 {lot_count}건 Hold·격리 여부 검토 (수율영향 기반 disposition)",
    }
    if status == "reviewed" and top is not None:
        equipment = top.get("equipment") or "의심 장비"
        return [
            hold,
            {"type": "corrective", "hold": False,
             "text": f"{equipment} 점검 — {top['cause']} 관련 부위·파라미터 확인"},
            {"type": "preventive", "hold": False,
             "text": "재발 방지 — 관련 알람 임계·PM 주기 재검토"},
        ]
    if status == "insufficient":
        return [
            hold,
            {"type": "investigation", "hold": False,
             "text": "수동 조사 이관 — 담당 엔지니어 배정"},
            {"type": "investigation", "hold": False,
             "text": "후보 장비 정상 로트 표본 확대·텔레메트리 보강 후 재분석"},
        ]
    if status == "novel":
        return [
            hold,
            {"type": "investigation", "hold": False,
             "text": "전문가 재판독 — 신규 패턴 여부 확정"},
            {"type": "investigation", "hold": False,
             "text": "신규 패턴 후보 등록 — 데이터 축적 후 재학습 검토"},
        ]
    if status == "normal_reading":
        # 판독상 정상(#69): 결함 패턴이 없어 Hold 근거가 없다 — 맵 밖 원인 조사로만 이관.
        return [
            {"type": "investigation", "hold": False,
             "text": "맵 비가시 수율손실 조사 — EDS 파라메트릭/전기적 특성 리뷰"},
            {"type": "investigation", "hold": False,
             "text": "해당 로트 공정 이력·계측 데이터 수동 확인"},
        ]
    # unmapped: 이상 자체가 매핑 밖(지식 공백) — Hold보다는 온톨로지 확충이 조치.
    return [
        {"type": "investigation", "hold": False,
         "text": f"{pattern} 패턴 원인 매핑(온톨로지) 확충 검토"},
    ]

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

    confidence = _confidence(accepted)  # R1: 확정 아님(medium/low) — 표현 층 불확실 표시
    level_ko = "잠정 지지" if confidence == "medium" else "불확실"
    lines = [
        f"- {h['cause']} (등급: {h['tier']}, 의심 장비: {h['equipment']})" for h in accepted
    ]
    # R1: 단정형("가설 N건 채택") 대신 비단정형 — "확정 아님"과 확신 수준을 명시한다.
    summary = (
        f"{pattern} 패턴 — 가능성 있는 원인 후보 {len(accepted)}건 "
        f"(확정 아님 · 확신: {level_ko}):\n" + "\n".join(lines)
    )
    return _final(
        state["group_id"], pattern, lot_ids,
        status="reviewed", reason=None, hypotheses=ordered, summary=summary,
        description=_group_description(state, translate), confidence=confidence,
        actions=group_actions("reviewed", pattern, len(lot_ids), accepted[0] if accepted else None),
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

    # 후보 0건 그룹의 판단불가 세분류 (와이어프레임 v8 (a)/(b), API v1.1):
    #   novel    — CNN이 Unknown(미지 패턴, OSR)으로 판정한 그룹. 억지 분류 대신 abstain —
    #              이상은 유효하므로 격리+전문가 재판독 대상.
    #   unmapped — 기지 패턴인데 KG 후보가 없던 그룹(지식 공백). 판독까지만 지원.
    if not state.get("candidates"):
        if pattern == "Unknown":
            return _final(
                group_id,
                pattern,
                lot_ids,
                status="novel",
                reason=(
                    "알려진 패턴 어디에도 맞지 않는 새 시각 패턴(open-set) 후보입니다. "
                    "억지 분류 대신 판단 불가로 처리하며, 이상은 유효하므로 격리·재판독 대상입니다."
                ),
                hypotheses=[],
                summary=f"{pattern} 패턴은 미확인 신규 패턴(OSR) — 전문가 재판독 대상입니다.",
                description=description,
                confidence="low",  # R1: 채택 원인 없음 → 불확실
                actions=group_actions("novel", pattern, len(lot_ids), None),
            )
        return _final(
            group_id,
            pattern,
            lot_ids,
            status="unmapped",
            reason="이 결함 패턴은 원인 매핑 데이터가 없어 판독까지만 지원됩니다.",
            hypotheses=[],
            summary=f"{pattern} 패턴은 원인 분석 데이터가 없습니다(KG 매핑 대상 3종 밖).",
            description=description,
            confidence="low",  # R1: 채택 원인 없음 → 불확실
            actions=group_actions("unmapped", pattern, len(lot_ids), None),
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
        confidence="low",  # R1: 채택 0건 → 불확실(판단 불가)
        actions=group_actions("insufficient", pattern, len(lot_ids), None),
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
    confidence: str,
    actions: list[dict],
) -> dict:
    return {
        "final_response": {
            "group_id": group_id,
            "pattern": pattern,
            "status": status,          # reviewed | insufficient | unmapped | novel (§2.2/§2.5, v1.1)
            "reason": reason,
            "lot_ids": lot_ids,
            "lot_count": len(lot_ids),
            "hypotheses": hypotheses,  # 정렬·h{n}·verdict 포함 (대표 = index 0)
            "summary": summary,        # 결정론적 템플릿(내부용, LLM 아님)
            "description": description,  # ③VLM(영어) → 한국어 번역, §2.5 (없으면 None → 프론트 summary_line)
            "confidence": confidence,  # R1: medium|low — 확정("high") 없음. 표현 층 불확실 표시
            # 그룹 단위 권장 조치 [{type, hold, text}] — 결정론적 템플릿(API v1.1, 와이어프레임 v8 정합)
            "actions": actions,
        }
    }
