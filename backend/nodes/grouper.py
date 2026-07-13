"""② Grouper. 결정적 함수, KG 미조회.

대표패턴 확정(다수결) -> 패턴 1차분리 -> 최소로트수 게이트 -> (선택) 유사도 서브클러스터링.
산출물_기능목록_유스케이스.md §1 참고.
"""

from __future__ import annotations

import collections

from ..state import RCAState

# TODO(팀 결정 필요): 지금은 게이트가 없다(로트 1개짜리 그룹도 통과). 서브클러스터링도 안 함.
MIN_LOTS_PER_GROUP = 1


def group_by_pattern(state: RCAState) -> dict:
    """vlm_results를 패턴별로 묶어 groups를 채운다.

    로트당 대표패턴은 그 로트에 속한 웨이퍼들의 pattern 다수결로 정하고,
    같은 대표패턴을 가진 로트끼리 그룹 하나로 묶는다.
    """
    patterns_by_lot: dict[str, list[str]] = collections.defaultdict(list)
    for vlm_result in state["vlm_results"]:
        patterns_by_lot[vlm_result["lot_id"]].append(vlm_result["pattern"])

    rep_pattern_by_lot = {
        lot_id: collections.Counter(patterns).most_common(1)[0][0]
        for lot_id, patterns in patterns_by_lot.items()
    }

    lots_by_pattern: dict[str, list[str]] = collections.defaultdict(list)
    for lot_id, pattern in rep_pattern_by_lot.items():
        lots_by_pattern[pattern].append(lot_id)

    groups = [
        {
            "group_id": f"{pattern}-{state['cursor_date']}",
            "pattern": pattern,
            "lot_ids": lot_ids,
            "status": "ok",
        }
        for pattern, lot_ids in lots_by_pattern.items()
        if len(lot_ids) >= MIN_LOTS_PER_GROUP
    ]
    return {"groups": groups}
