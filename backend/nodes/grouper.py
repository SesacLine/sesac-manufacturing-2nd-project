"""② Grouper. 결정적 함수, KG 미조회.

대표패턴 확정(다수결) -> 패턴 1차분리 -> 최소로트수 게이트 -> (선택) 유사도 서브클러스터링.
산출물_기능목록_유스케이스.md §1 참고.
"""

from __future__ import annotations

from ..state import RCAState


def group_by_pattern(state: RCAState) -> dict:
    """vlm_results를 패턴별로 묶어 groups를 채운다.

    TODO: 4단계 로직(다수결 대표패턴 확정 -> 패턴 분리 -> 최소 로트수 게이트 ->
          선택적 서브클러스터링) 구현. fan-out 방식(순차 loop vs LangGraph Send API)은
          jiun_work_0710.md에 미확정 항목으로 남아 있음 — 지금 규모면 순차 loop로 충분.
    """
    raise NotImplementedError
