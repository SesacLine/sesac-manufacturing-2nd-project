"""angular_coverage 판별자 — 관측 모폴로지로 후보를 재가중(감점 전용)한다.

각 신호를 다르게 취급하는 이유:
- shape@zone은 **하드 진입점**이다. 후보가 존재한다는 것 자체가 이미 매칭 성공이므로
  여기서 다시 보지 않는다.
- angular_coverage는 **판별자(강)**다. full ring과 partial arc는 인과가 갈리고(전방위=계통적
  반경 이슈, 한쪽 호=비대칭 핸들링/엣지 장비), die-matrix에서 결정적으로 나오므로 신뢰할 수 있다.
- density/continuity/clock_positions는 **소프트 신호**다. VLM 텍스트 기반이라 노이즈가 있어
  약하게만 반영한다.

방침: **감점 전용(demote-only).** 상충하는 후보는 아래로 내리되, 일치/무관측은 0점(중립)이라
kg_rca가 이미 매긴 근거 기반 순위를 인위적으로 끌어올리지 않는다(경로/근거 우선 보존).
관측이나 후보 모폴로지가 없으면(step/direct 경로, unknown/not_applicable) 0점 → 순서 불변.
"""

from __future__ import annotations

# 판별자(강) — 상충 시 강등
ANGULAR_MISMATCH = -10.0
# 소프트 신호 — 상충 시 약한 강등만
CLOCK_DISJOINT = -3.0
DENSITY_MISMATCH = -1.0
CONTINUITY_MISMATCH = -1.0

# 강한 모순 컷 — 이 점수 이하는 리스트에서 제외한다(강등이 아니라 드롭).
# 소프트 신호는 다 합쳐도 -5(clock -3 + density -1 + continuity -1)라 이 선을 못 넘는다.
# 즉 -10 이하 = **angular full↔partial 상충**이 있다는 뜻 — 관측이 "한쪽 호"인데 후보는
# "전방위 링" 전제처럼, 이번 웨이퍼 형상과 근본적으로 안 맞는 원인이다. "그럴듯함"이 아니라
# **관측 사실**로 거르는 컷이라 환각 억제 원칙과 부딪히지 않는다.
STRONG_CONTRADICTION = ANGULAR_MISMATCH  # -10.0

# "값 없음"으로 취급해 비교를 건너뛰는 토큰
_UNKNOWN = {None, "unknown", "not_applicable"}


def _both_known(a, b) -> bool:
    return a not in _UNKNOWN and b not in _UNKNOWN


def morphology_penalty(observation: dict, morphology: dict | None) -> float:
    """관측 모폴로지와 후보 FORMS_IN 엣지 모폴로지를 비교한 감점 합(<= 0)."""
    if not morphology:
        return 0.0

    penalty = 0.0

    obs_ang, cand_ang = observation.get("angular_coverage"), morphology.get("angular_coverage")
    if _both_known(obs_ang, cand_ang):
        if obs_ang != cand_ang:
            penalty += ANGULAR_MISMATCH            # 판별자: full vs partial 상충 → 강한 강등
        elif obs_ang == "partial":
            # 둘 다 partial이면 시계 위치까지 본다 (겹치면 무벌점, 완전히 어긋나면 소폭 강등)
            obs_clock = set(observation.get("clock_positions") or [])
            cand_clock = set(morphology.get("clock_positions") or [])
            if obs_clock and cand_clock and not (obs_clock & cand_clock):
                penalty += CLOCK_DISJOINT

    obs_den, cand_den = observation.get("density"), morphology.get("density")
    if _both_known(obs_den, cand_den) and obs_den != cand_den:
        penalty += DENSITY_MISMATCH

    obs_con, cand_con = observation.get("continuity"), morphology.get("continuity")
    if _both_known(obs_con, cand_con) and obs_con != cand_con:
        penalty += CONTINUITY_MISMATCH

    return penalty


def rerank_by_observation(
    candidates: list[dict],
    observation: dict | None,
    drop_contradictions: bool = True,
) -> list[dict]:
    """관측 모폴로지로 후보를 재정렬한다. 관측이 없으면 원본을 그대로 돌려준다.

    각 후보에 `morphology_score`(<= 0)를 달고, 그 점수 내림차순으로 **안정 정렬**한다.
    파이썬 정렬은 안정적이라 동점(0점 포함)은 kg_rca가 준 원래 순서를 유지한다 —
    소프트 상충 후보만 아래로 가라앉고 나머지는 순위 불변.

    drop_contradictions=True(기본)이면 **강한 모순**(score <= STRONG_CONTRADICTION, 즉 angular
    full↔partial 상충)인 후보는 순위에서 빼는 게 아니라 **리스트에서 제외**한다. 이번 웨이퍼
    형상과 근본적으로 안 맞는 원인이라 남겨둘 이유가 없다. 소프트 신호(clock/density/continuity)
    상충은 감점만 하고 남긴다. False면 옛 동작(강등만).
    """
    if not observation:
        return candidates

    for candidate in candidates:
        candidate["morphology_score"] = morphology_penalty(
            observation, candidate.get("morphology")
        )

    kept = candidates
    if drop_contradictions:
        kept = [c for c in candidates if c["morphology_score"] > STRONG_CONTRADICTION]
    return sorted(kept, key=lambda c: c["morphology_score"], reverse=True)
