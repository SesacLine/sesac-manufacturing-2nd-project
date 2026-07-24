"""② Grouper. 결정적 함수, KG 미조회.

대표패턴 확정(다수결) -> 패턴 1차분리 -> 최소로트수 게이트 -> (선택) 유사도 서브클러스터링.
산출물_기능목록_유스케이스.md §1 참고.
"""

from __future__ import annotations

import collections

from ..state import RCAState

# TODO(팀 결정 필요): 지금은 게이트가 없다(로트 1개짜리 그룹도 통과). 서브클러스터링도 안 함.
MIN_LOTS_PER_GROUP = 1

# 다수결 동률 우선순위 (07-22 팀 확정, 판독 설계서 §3): Edge-Ring > Center > Scratch > Unknown.
# WM-811K 분포 기반. Normal은 우선순위에서 제외 — 동률에 결함 패턴이 하나라도 끼면 결함이 이긴다
# (Normal이 단독 과반일 때만 그 로트가 "판독상 정상"으로 분류된다).
_TIE_PRIORITY = ["Edge-Ring", "Center", "Scratch", "Unknown"]


def _representative_pattern(patterns: list[str]) -> str:
    """로트 대표패턴 = 다수결, 동률이면 _TIE_PRIORITY 순."""
    counts = collections.Counter(patterns)
    top = max(counts.values())
    tied = [p for p, n in counts.items() if n == top]
    for p in _TIE_PRIORITY:  # 결함 패턴이 동률에 있으면 우선순위대로
        if p in tied:
            return p
    return tied[0]  # 전부 우선순위 밖(= Normal 단독)일 때


def group_by_pattern(state: RCAState) -> dict:
    """cnn_results를 패턴별로 묶어 groups를 채운다. Normal 다수결 로트는 그룹 미생성.

    로트당 대표패턴은 그 로트에 속한 웨이퍼들의 pattern 다수결(동률은 _TIE_PRIORITY)로 정하고,
    같은 대표패턴을 가진 로트끼리 그룹 하나로 묶는다.

    대표패턴이 Normal인 로트(저수율인데 웨이퍼맵상 정상 = 맵 비가시 수율손실 의심)는
    기획 §6.1대로 그룹을 만들지 않고 `normal_lots`로 따로 내보낸다 — "판독상 정상 N로트"
    전용 카드 노출(이슈 #69 (b)안)의 원천. 조용히 버리면 이 신호가 사라지므로 폐기하지 않는다.
    (구 동작: Normal 그룹을 만들어 run_groups 가드가 스킵 — 정보가 유실됐다.)
    """
    patterns_by_lot: dict[str, list[str]] = collections.defaultdict(list)
    for cnn_result in state["cnn_results"]:
        patterns_by_lot[cnn_result["lot_id"]].append(cnn_result["pattern"])

    rep_pattern_by_lot = {
        lot_id: _representative_pattern(patterns)
        for lot_id, patterns in patterns_by_lot.items()
    }

    normal_lots = sorted(
        lot_id for lot_id, pattern in rep_pattern_by_lot.items() if pattern == "Normal"
    )

    lots_by_pattern: dict[str, list[str]] = collections.defaultdict(list)
    for lot_id, pattern in rep_pattern_by_lot.items():
        if pattern != "Normal":
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
    return {"groups": groups, "normal_lots": normal_lots}
