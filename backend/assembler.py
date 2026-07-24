"""FinalResponse(노드 내부 표현) → API 응답 payload(§2.5 + 가설별 §2.7) 조립.

배치 완료 시점에 한 번 조립해 app_state.db에 통째로 저장하고, 조회 API는 저장분을
꺼내기만 한다(§2.7 "리치 보존 → 조회만, 온디맨드 MCP 재계산 금지").

enum 정규화(tier 한글→영문, pattern 5종 접기)는 여기(API 경계)서만 한다 — AGENT_GUIDE §1-b.
"""

from __future__ import annotations

from .schemas import normalize_pattern, normalize_tier

# 반대근거 판정 임계(잠정, BACKEND_DECISIONS.md D6): 정상비율 50% 이상이면 "지지 약함".
_NORMAL_RATIO_WEAK_THRESHOLD = 0.5


def build_analysis_payload(analysis_id: str, final: dict) -> dict:
    """final_response[group_id] 1건을 §2.5 응답 + 가설별 §2.7 근거로 조립한다.

    반환 payload는 §2.5 응답 키 전체 + "evidence"(hypothesis_id → §2.7 응답) 맵.
    조회 API는 §2.5는 evidence만 빼고, §2.7은 evidence[hid]를 그대로 내려준다.
    """
    pattern = normalize_pattern(final["pattern"])
    hypotheses_out: list[dict] = []
    evidence_map: dict[str, dict] = {}

    for h in final.get("hypotheses", []):
        card, evidence = _build_hypothesis(analysis_id, h)
        hypotheses_out.append(card)
        evidence_map[card["hypothesis_id"]] = evidence

    return {
        "analysis_id": analysis_id,
        "pattern": pattern,
        "description": final.get("description"),  # ③VLM(영어)→한국어 번역, response._describe_ko 소관(§2.5). 없으면 None → 프론트 summary_line fallback
        "status": final["status"],
        "reason": final.get("reason"),
        # R1: 확신 수준(불확실 표시) — "medium"(잠정 지지)/"low"(불확실). "high"(확정) 없음.
        # ⑤/⑥ 게이트가 못 거른 환각을 프론트가 "단정하지 않음"으로 표현하게 하는 신호(eval R1·B1).
        # 구 저장분엔 없을 수 있어 기본 "low"(가장 보수적) 폴백.
        "confidence": final.get("confidence", "low"),
        "lot_count": final["lot_count"],
        "lot_ids": final["lot_ids"],
        "hypotheses": hypotheses_out,
        "evidence": evidence_map,
    }


def _build_hypothesis(analysis_id: str, h: dict) -> tuple[dict, dict]:
    """가설 1건 → (§2.5 hypotheses[] 원소, §2.7 근거 응답)."""
    tier = normalize_tier(h["tier"])
    verdict = h.get("verdict", "rejected")
    verdict_reason = h.get("verdict_reason")
    stage = h.get("stage")
    citations = h.get("citations", [])
    next_actions = h.get("next_actions") or []
    ev = h.get("evidence", {})
    suspect_eq = h.get("equipment")
    # chamber_id는 null 고정 — commonality가 장비/챔버를 별개 카운터로 집계해 장비별
    # 챔버 특정이 불가(BACKEND_DECISIONS.md D5).
    suspect = {"equipment_id": suspect_eq, "chamber_id": None} if suspect_eq else None

    card = {
        "hypothesis_id": h["hypothesis_id"],
        "cause": h["cause"],
        "stage": stage,
        "tier": tier,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "narrative": h.get("sentence", ""),
        "next_actions": next_actions,
        "citations": citations,
        # R2(원인군 카드): 같은 cluster_id = fab 증거가 동일한 원인군. 프론트가 이걸로 묶어
        # 단일 헤드라인 대신 "원인 후보 묶음"으로 제시한다(eval_scenario_kg_proposal.md R2).
        # ⑤가 안 채웠으면 None → 프론트가 단독 후보로 취급.
        "cluster_id": h.get("cluster_id"),
        "is_primary": bool(h.get("is_primary", False)),  # cause 대표 행(원인군 내 중복 cause 축약용)
    }

    evidence = {
        "analysis_id": analysis_id,
        "hypothesis_id": h["hypothesis_id"],
        "cause": h["cause"],
        "stage": stage,
        "tier": tier,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "suspect": suspect,
        "sections": {
            "commonality": _commonality_section(ev, suspect_eq),
            "telemetry": _telemetry_section(ev, tier, suspect_eq),
            "events": _events_section(ev, tier),
        },
        "unverified": [],
        "next_actions": next_actions,
        "citations": citations,
        "note": (
            "이 원인은 fab 데이터 검증 신호가 없어 문헌 서술만 제공됩니다."
            if tier == "none"
            else None
        ),
    }
    return card, evidence


def _commonality_section(ev: dict, suspect_eq: str | None) -> dict:
    rows = ev.get("commonality_rows") or []
    if not rows:
        return {"available": False, "reason": "no_data_found", "rows": [], "normal_ratio": None}
    normal_ratio = None
    value = ev.get("normal_ratio")
    if value is not None and suspect_eq:
        pct = round(value * 100)
        judgement = (
            "원인 지지 약함(반대근거 강함)"
            if value >= _NORMAL_RATIO_WEAK_THRESHOLD
            else "원인 지지(반대근거 약함)"
        )
        normal_ratio = {
            "value": value,
            "caption": f"{suspect_eq} 통과 로트 중 정상 {pct}% → {judgement}",
        }
    return {"available": True, "rows": rows, "normal_ratio": normal_ratio}


def _telemetry_section(ev: dict, tier: str, suspect_eq: str | None) -> dict:
    if tier == "none":
        return {"available": False, "reason": "none_tier", "series": []}
    if not ev.get("telemetry_collected"):
        # auto인데 suspect가 없어 앵커 부재로 미호출된 경우까지 포함해, 실제 미호출은
        # tier가 telemetry 대상이 아니면 not_collected_for_tier, 대상(auto)이면 no_data_found.
        reason = "no_data_found" if tier == "auto" and not suspect_eq else "not_collected_for_tier"
        return {"available": False, "reason": reason, "series": []}
    series = ev.get("telemetry_series") or []
    if not series:
        return {"available": False, "reason": "no_data_found", "series": []}
    normal_range = ev.get("telemetry_normal_range")
    drift = ev.get("drift_detected")
    caption = None
    if normal_range:
        caption = f"정상범위 {normal_range} " + ("이탈 감지" if drift else "이탈 미감지")
    return {
        "available": True,
        "param": ev.get("telemetry_param") or "",
        "unit": "",  # fab.db에 단위 메타 없음(BACKEND_DECISIONS.md D7) — 빈 문자열
        "normal_range": normal_range,
        "drift_detected": drift,
        "t0": None,  # 이상 시작 추정 미계산(변화점 탐지 미사용) — Nullable 계약
        "series": series,
        "caption": caption,
    }


def _events_section(ev: dict, tier: str) -> dict:
    if tier == "none":
        return {"available": False, "reason": "none_tier", "rows": []}
    if not ev.get("events_collected"):
        return {"available": False, "reason": "not_collected_for_tier", "rows": []}
    rows = ev.get("events_rows") or []
    if not rows:
        return {"available": False, "reason": "no_data_found", "rows": []}
    return {"available": True, "rows": rows}
