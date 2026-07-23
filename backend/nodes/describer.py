"""③ VLM description 생성(describer) — 그룹(스택맵) 단위 Observation 1건을 만들어 group["observation"]에 싣는다.

기획안 v1.5의 "③ VLM description 생성" 스테이지가 이 노드다 — 실제 VLM이 붙으면 여기가
스택맵 이미지를 서술하는 실시간 모델 노드가 된다(현 nodes/vlm.py는 ① CNN 자리의 스탠드인).

기획안 v1.5 목표 구조에서 VLM은 Grouper **뒤**에서 그룹 스택맵(같은 CNN 라벨 웨이퍼들의
die_map 오버레이)에 1회 적용된다 — 웨이퍼별 판독을 합치는 집계 과정이 없다
(kg_rca/데이터 모델 설계_v3.0.md §3.0). 이 노드가 그 자리다.

관측의 세 생산자와 스켈레톤 대체물:
  CNN 라벨        -> group["pattern"] 그대로 (현재 ① read_wafer_maps가 CNN 스탠드인)
  VLM 자연어      -> TODO(Walking Skeleton): 실제 VLM 미연동. 패턴별 결정적 템플릿 문자열
  die-matrix 통계 -> TODO(Walking Skeleton): 스택맵 미구축. 패턴별 결정적 기본값
                     (실구현: 그룹 웨이퍼들의 wafer.die_map을 오버레이한 스택맵에서
                      angular/clock/density/continuity/defect_die_ratio를 계산)

여기서 만든 observation은 ④ graphrag가 kg_client.get_candidates(pattern, observation)로
넘긴다 — 자연어(location/morphology_text)는 의미 진입(임베딩)에, 구조화 값(angular 등)은
판별자 재랭킹에 쓰인다. KGClient(파일 조회)는 observation의 구조화 값만, LiveKGClient는
자연어까지 사용한다.
"""

from __future__ import annotations

from ..state import Observation, RCAState

# TODO(Walking Skeleton, VLM/스택맵 연동 시 교체): 패턴별 결정적 관측 템플릿.
# 자연어는 doc_H(형상·모폴로지 목업)와 같은 어휘로 써서 의미 진입이 올바른 시그니처에
# 닿게 한다. 값은 "그 패턴의 가장 전형적인 관측"으로 고정 — 실제 스택맵 계산이 붙기 전까지의
# 자리채움이며, 판별자 검증엔 라이브 테스트(test_semantic_entry.py)가 별도로 있다.
_SKELETON_OBSERVATIONS: dict[str, Observation] = {
    "Center": {
        "pattern_candidate": "Center",
        "location_text": "a concentrated cluster of failing dies at the geometric center of the wafer",
        "morphology_text": "a dense, solid, continuous blob — the classic bulls-eye",
        "angular_coverage": "unknown",       # 중심 blob은 원주 방향 개념이 없다
        "clock_positions": [],
        "density": "high",
        "continuity": "continuous",
    },
    "Edge-Ring": {
        "pattern_candidate": "Edge-Ring",
        "location_text": "failing dies distributed around the entire wafer edge",
        "morphology_text": "a dense, nearly unbroken circular ring wrapping the full circumference",
        "angular_coverage": "full",
        "clock_positions": [],
        "density": "high",
        "continuity": "continuous",
    },
    "Scratch": {
        "pattern_candidate": "Scratch",
        "location_text": "an elongated line of failing dies cutting across the wafer",
        "morphology_text": "a thin, continuous, low-density linear streak",
        "angular_coverage": "unknown",
        "clock_positions": [],
        "density": "low",
        "continuity": "continuous",
    },
}


def _build_observation(pattern: str) -> Observation:
    """그룹 1개의 관측 스켈레톤. 3종 밖(Unknown 포함)은 자연어 없는 최소 관측만 낸다.

    미지 패턴의 실관측은 VLM이 스택맵을 보고 자연어를 내야 성립한다(그게 의미 진입의 입력).
    스켈레톤은 그 자연어를 지어낼 수 없으므로 — 지어내면 가짜 근거로 KG를 오도한다 —
    pattern_candidate만 채워 보낸다. LiveKGClient는 자연어 없는 Unknown에 candidates=[]를
    돌려주고, 그 그룹은 기존 UC-3(미매핑 패턴) 흐름을 탄다.
    """
    if pattern in _SKELETON_OBSERVATIONS:
        return dict(_SKELETON_OBSERVATIONS[pattern])  # 그룹별 독립 사본 (공유 dict 변조 방지)
    return {"pattern_candidate": pattern, "location_text": "", "morphology_text": ""}


def describe_groups(state: RCAState) -> dict:
    """groups 각각에 그룹 단위 관측 1건을 붙인다. 결정적, 그룹당 1건, 집계 없음."""
    groups = [
        {**group, "observation": _build_observation(group["pattern"])}
        for group in state["groups"]
    ]
    return {"groups": groups}
