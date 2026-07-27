"""② Grouper. 결정적 함수, KG 미조회.

대표패턴 확정(다수결) -> 패턴 1차분리 -> 시간 서브클러스터링 -> 최소로트수 게이트.
산출물_기능목록_유스케이스.md §1 참고.
"""

from __future__ import annotations

import collections

from ..state import RCAState

# TODO(팀 결정 필요): 지금은 게이트가 없다(로트 1개짜리 그룹도 통과).
MIN_LOTS_PER_GROUP = 1

# 시간 서브클러스터링 = **결함 확정일(EDS 날짜) 단위**. 같은 패턴이어도 날짜가 다르면 다른
# 그룹으로 나눈다.
#
# 왜 "날짜"인가 — 운영 단위와 그루핑 단위를 일치시키기 위해서다. 이 서비스는 "아침에 한 번
# 눌러 전날 쌓인 것을 본다"이므로 평상시 배치 창은 하루다(batch_runner._cursor_range). 즉 정상
# 운영에서 나오는 그룹은 항상 하루치다. 캐치업(첫 배치·주말 건너뜀)에서만 창이 넓어지는데,
# 여기서 며칠을 한 그룹으로 묶으면 **정상 운영에서는 결코 만들어질 수 없는 카드**가 생겨
# 같은 사건이 언제 분석됐느냐에 따라 다르게 보인다. 날짜 단위로 통일하면 캐치업 결과가
# "그날그날 눌렀다면 나왔을 결과"와 같아진다.
#
# 무엇을 고치는가 — 패턴만 같으면 몇 달 차이도 한 그룹이던 옛 동작은 ⑥ Critic의 시간정합(P2)을
# 구조적으로 무력화했다: P2 비교 기준인 defect_ts가 그룹 최솟값이라, 늦은 사건의 정당한 원인
# 정비가 "결함 이후"로 판정돼 통째로 기각된다.
#   실측(2026-07-27) — 1/20·1/30 두 로트가 한 Center 그룹(스팬 9일)이 되자 채택 0건 /
#   P2 기각 176건. 날짜로 나눈 뒤엔 두 그룹 모두 reviewed(각 채택 4건).
#
# 트레이드오프 — GT 실측상 실제 결함 사건은 3~6일에 걸쳐 있어(로트들이 며칠간 그 장비를 통과),
# 날짜로 자르면 한 사건이 여러 카드로 쪼개진다. 다만 정상 운영에서도 그 사건은 어차피 날짜별로
# 나뉘어 분석되므로(하루 창), 이 분할이 오히려 운영 실제와 일치한다. 대신 그룹당 로트 수가
# 줄어 commonality 판별력이 약해질 수 있다 — 다만 ⑥의 인과 서명 게이트가 공통률뿐 아니라
# **방향 일치**도 함께 요구하므로, 단일 로트 그룹에서도 판별은 유지된다(실측 확인).

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


def split_by_day(lot_ids: list[str], defect_ts: dict[str, str]) -> list[list[str]]:
    """같은 패턴 로트를 **결함 확정일(EDS 날짜)** 단위로 쪼갠다. 날짜 오름차순.

    시각을 모르는 로트(defect_ts 없음)는 쪼개지 않고 첫 덩어리에 남긴다 — 정보가 없다고
    임의로 분리하면 없던 사건을 만들어내므로, 판단 보류 쪽이 안전하다. lot_defect_ts를
    아예 안 넘기는 호출(구 동작·단위 테스트)에서는 전체가 한 덩어리로 유지된다.
    """
    by_day: dict[str, list[str]] = collections.defaultdict(list)
    unknown: list[str] = []
    for lot in lot_ids:
        ts = defect_ts.get(lot)
        if ts:
            by_day[ts[:10]].append(lot)   # "YYYY-MM-DD HH:MM:SS" → 날짜만
        else:
            unknown.append(lot)

    if not by_day:
        return [lot_ids]

    days = sorted(by_day)
    clusters = [by_day[d] for d in days]
    clusters[0] = unknown + clusters[0]   # 시각 미상은 첫(가장 이른) 날에 흡수
    return clusters


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

    # 같은 패턴이라도 결함 확정일이 다르면 다른 그룹(split_by_day) — 운영 단위(하루)와 일치.
    defect_ts = state.get("lot_defect_ts") or {}
    groups = []
    for pattern, lot_ids in lots_by_pattern.items():
        for cluster in split_by_day(lot_ids, defect_ts):
            if len(cluster) < MIN_LOTS_PER_GROUP:
                continue
            # group_id는 그 그룹의 결함일로 짓는다(배치 커서가 아니라) — 캐치업 배치에서
            # 날짜별로 갈린 그룹들이 서로 구분되고, "그날 눌렀다면 나왔을 id"와도 같아진다.
            # 하위 그래프의 그룹키·로그 태그가 전부 group_id 기준이라 유니크해야 한다.
            day = defect_ts.get(cluster[0], "")[:10] or state["cursor_date"]
            groups.append({
                "group_id": f"{pattern}-{day}",
                "pattern": pattern,
                "lot_ids": cluster,
                "status": "ok",
            })
    return {"groups": groups, "normal_lots": normal_lots}
