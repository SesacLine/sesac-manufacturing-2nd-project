"""③ 관측 생산 — 그룹(스택맵) 단위 Observation 1건을 만들어 group["observation"]에 싣는다.

기획안 v1.5 목표 구조에서 VLM은 Grouper **뒤**에서 그룹 스택맵(같은 CNN 라벨 웨이퍼들의
die_map 오버레이)에 1회 적용된다 — 웨이퍼별 판독을 합치는 집계 과정이 없다
(kg_rca/데이터 모델 설계_v3.0.md §3.0). 이 노드가 그 자리다.

관측의 세 생산자:
  CNN 라벨        -> group["pattern"] 그대로 (현재 ① read_wafer_maps가 CNN 스탠드인)
  die-matrix 통계 -> **실연동**: 그룹 로트들의 wafer.die_map을 stacking으로 겹쳐 스택맵을 만들고
                     wafer_reading.quantitative가 shape/zone/signature/angular/clock/density/
                     continuity/defect_die_ratio를 KG 어휘로 계산한다.
  VLM 자연어      -> TODO: 실제 VLM 미연동. location/morphology_text는 아직 빈 값(스켈레톤 폴백만
                     자연어를 채운다). signature가 있으면 KG는 enum 진입이라 자연어가 없어도 된다.

fab.db가 없거나(CI/팀원 환경) die_map을 못 읽으면 **패턴별 스켈레톤 관측으로 폴백**해 파이프라인이
끊기지 않게 한다. 여기서 만든 observation은 ④ graphrag가 get_candidates(pattern, observation)로
넘긴다 — signature는 enum 진입에, angular 등 구조화 값은 판별자 재랭킹에 쓰인다.
"""

from __future__ import annotations

import io
import os
import sqlite3

import numpy as np

from ..state import Observation, RCAState
from wafer_reading.quantitative import compute_group_stats
from wafer_reading.stacking import stack_wafer_maps

# 스택맵/quantitative 미연동 환경(fab.db 없음 등)의 폴백. 자연어는 doc_H(형상·모폴로지 목업)와
# 같은 어휘로 써서, 의미 진입이 붙을 경우 올바른 시그니처에 닿게 한다. 값은 "그 패턴의 가장
# 전형적인 관측"으로 고정 — 실제 계산이 되면 _observation_from_die_maps가 대체한다.
_SKELETON_OBSERVATIONS: dict[str, Observation] = {
    "Center": {
        "pattern_candidate": "Center",
        "location_text": "a concentrated cluster of failing dies at the geometric center of the wafer",
        "morphology_text": "a dense, solid, continuous blob — the classic bulls-eye",
        "total_description": "A localized, high-density amorphous blob of failing dies concentrated at the wafer center, with density decreasing sharply outward.",
        "angular_coverage": "unknown",
        "clock_positions": [],
        "density": "high",
        "continuity": "continuous",
    },
    "Edge-Ring": {
        "pattern_candidate": "Edge-Ring",
        "location_text": "failing dies distributed around the entire wafer edge",
        "morphology_text": "a dense, nearly unbroken circular ring wrapping the full circumference",
        "total_description": "A continuous, high-density circumferential band of failing dies along the wafer periphery, sharply contrasted against a clean interior.",
        "angular_coverage": "full",
        "clock_positions": [],
        "density": "high",
        "continuity": "continuous",
    },
    "Scratch": {
        "pattern_candidate": "Scratch",
        "location_text": "an elongated line of failing dies cutting across the wafer",
        "morphology_text": "a thin, continuous, low-density linear streak",
        "total_description": "A continuous filamentary string of failing dies tracing a jagged linear trajectory across adjacent die fields.",
        "angular_coverage": "unknown",
        "clock_positions": [],
        "density": "low",
        "continuity": "continuous",
    },
}


def _skeleton(pattern: str) -> Observation:
    """폴백 관측. 3종은 전형적 템플릿, 그 외(Unknown 포함)는 자연어 없는 최소 관측.

    미지 패턴의 자연어를 지어내면 가짜 근거로 KG를 오도하므로 pattern_candidate만 채운다
    — LiveKGClient가 자연어·signature 없는 Unknown에 candidates=[]를 돌려주고(UC-3 흐름).
    """
    if pattern in _SKELETON_OBSERVATIONS:
        return dict(_SKELETON_OBSERVATIONS[pattern])  # 그룹별 독립 사본
    return {"pattern_candidate": pattern, "location_text": "", "morphology_text": ""}


def _fetch_die_maps(lot_ids: list[str]) -> list[np.ndarray]:
    """그룹 로트들의 웨이퍼 die_map(0/1/2 배열)을 fab.db에서 읽는다.

    die_map은 BLOB(np.save 바이트, secsgem-mcp/README.md §3). fab.db 없거나 읽기 실패 시 []
    → 호출부가 스켈레톤으로 폴백한다.
    """
    db = os.environ.get("FAB_DB")
    if not lot_ids or not db or not os.path.exists(db):
        return []
    placeholders = ",".join("?" * len(lot_ids))
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            f"SELECT die_map FROM wafer WHERE lot_id IN ({placeholders}) AND die_map IS NOT NULL",
            lot_ids,
        ).fetchall()
    finally:
        con.close()

    die_maps: list[np.ndarray] = []
    for row in rows:
        try:
            die_maps.append(np.load(io.BytesIO(row["die_map"]), allow_pickle=False))
        except Exception:  # noqa: BLE001 — 손상 맵 한 장이 그룹 전체를 막지 않게
            continue
    return die_maps


def _observation_from_die_maps(pattern: str, die_maps: list[np.ndarray]) -> Observation:
    """스택맵 → quantitative die-matrix 통계 → KG 어휘 관측. 결함 0이면 스켈레톤."""
    stats = compute_group_stats(stack_wafer_maps(die_maps))
    if not stats.get("signature"):
        return _skeleton(pattern)  # 그룹에 유의미한 결함 형상 없음
    return {
        "pattern_candidate": pattern,
        # die-matrix 구조화 (quantitative) — signature는 enum 진입, 나머지는 판별자
        "signature": stats["signature"],
        "angular_coverage": stats["angular_coverage"],
        "clock_positions": stats["clock_positions"],
        "density": stats["density"],
        "continuity": stats["continuity"],
        "defect_die_ratio": stats["defect_die_ratio"],
        # VLM 자연어 미연동 — signature가 있어 enum 진입이므로 빈 값이어도 조회 성립
        "location_text": "",
        "morphology_text": "",
    }


def _member_keys(
    pattern: str, lot_ids: list[str], vlm_results: list[dict]
) -> list[tuple[str, str]]:
    """스태킹 멤버 규칙(팀 확정): ① 판정 pattern이 그룹 pattern과 일치하는 웨이퍼만.

    is_normal 등 fab.db 라벨로 거르면 안 된다(정답 누출) — 반드시 ① CNN 판정으로 거른다.
    """
    member_lots = set(lot_ids)
    return [
        (r["lot_id"], r["wafer_id"])
        for r in vlm_results
        if r["lot_id"] in member_lots and r["pattern"] == pattern
    ]


def _build_observation(
    pattern: str, lot_ids: list[str], vlm_results: list[dict] | None = None
) -> Observation:
    """그룹 1개의 관측. die_map을 읽어 quantitative로 계산, 불가하면 스켈레톤 폴백.

    멤버 규칙을 기본 경로에도 적용한다 — 로트 전체(정상 웨이퍼 포함)를 스태킹하면 신호가
    희석돼 signature가 오염된다(SC-CENTER-01 실측: 전체 192장 random@edge vs 멤버 29장
    cluster@center, 발견문제_로그 #4). vlm_results가 없는 단독 호출은 종전대로 로트 전체.
    """
    keys = _member_keys(pattern, lot_ids, vlm_results or [])
    die_maps = _fetch_die_maps_by_keys(keys) if keys else _fetch_die_maps(lot_ids)
    if not die_maps:
        return _skeleton(pattern)
    try:
        return _observation_from_die_maps(pattern, die_maps)
    except Exception:  # noqa: BLE001 — 계산 실패가 배치를 멈추지 않게, 폴백으로 이어간다
        return _skeleton(pattern)


def observe_groups(state: RCAState) -> dict:
    """groups 각각에 그룹 단위 관측 1건을 붙인다. 그룹당 1건, 집계 없음.

    분기 flag `VLM_LIVE`(KG_LIVE와 같은 관례): 미설정(기본)이면 결정적 관측만
    (quantitative die-matrix 통계, 자연어 빈 값 — 위 기본 경로 그대로), 1/true/yes면
    같은 결정적 관측 위에 **실제 VLM 자연어(location/morphology_text)를 오버레이**한다
    (wafer_reading.vlm.VLMReader — 트랙은 VLM_TRACK open|pty). VLM 실패 시 결정적 관측만
    으로 이어간다(자연어 없이도 signature enum 진입이 성립하므로 배치는 죽지 않는다).
    """
    if os.getenv("VLM_LIVE", "").lower() in ("1", "true", "yes"):
        groups = [_observe_group_live(group, state) for group in state["groups"]]
    else:
        groups = [
            {
                **group,
                "observation": _build_observation(
                    group["pattern"], group["lot_ids"], state.get("vlm_results")
                ),
            }
            for group in state["groups"]
        ]
    return {"groups": groups}


# --- VLM_LIVE 분기 — 기본(결정적) 경로는 위를 그대로 유지, 아래는 opt-in 전용 ---

_vlm_reader = None  # 모델/클라이언트 로드가 무거워 프로세스당 1회만


def _get_vlm_reader():
    global _vlm_reader
    if _vlm_reader is None:
        from wafer_reading.vlm import VLMReader

        _vlm_reader = VLMReader()  # 트랙은 VLM_TRACK 환경변수 (기본 open)
    return _vlm_reader


def _observe_group_live(group: dict, state: RCAState) -> dict:
    """결정적 관측(quantitative) + VLM 자연어 오버레이.

    스태킹 멤버 규칙은 기본 경로와 공통(_member_keys) — 신호 희석 방지.
    VLM 이미지 분기(Scratch 단일)는 어댑터가 처리.
    """
    from wafer_reading.vlm.adapter import VLMCallError

    keys = _member_keys(group["pattern"], group["lot_ids"], state["vlm_results"])
    die_maps = _fetch_die_maps_by_keys(keys)
    if not die_maps:
        return {**group, "observation": _build_observation(group["pattern"], group["lot_ids"])}

    try:
        observation = _observation_from_die_maps(group["pattern"], die_maps)
    except Exception:  # noqa: BLE001 — 기본 경로와 같은 폴백 정책
        observation = _skeleton(group["pattern"])

    try:
        vlm = _get_vlm_reader().describe_group(group["pattern"], die_maps)
    except VLMCallError:
        return {**group, "observation": observation}  # 자연어 없이 결정적 관측만

    observation = {
        **observation,
        "location_text": vlm["location_text"],
        "morphology_text": vlm["morphology_text"],
        "total_description": vlm["total_description"],
        "vlm_track": vlm["vlm_track"],
        "image_mode": vlm["image_mode"],
    }
    return {**group, "observation": observation}


def _fetch_die_maps_by_keys(keys: list[tuple[str, str]]) -> list[np.ndarray]:
    """(lot_id, wafer_id) 목록의 die_map만 로드 — 멤버 규칙 적용판 _fetch_die_maps."""
    db = os.environ.get("FAB_DB")
    if not keys or not db or not os.path.exists(db):
        return []
    con = sqlite3.connect(db)
    try:
        maps: list[np.ndarray] = []
        for lot_id, wafer_id in keys:
            row = con.execute(
                "SELECT die_map FROM wafer WHERE lot_id = ? AND wafer_id = ? AND die_map IS NOT NULL",
                (lot_id, wafer_id),
            ).fetchone()
            if row is None:
                continue
            try:
                maps.append(np.load(io.BytesIO(row[0]), allow_pickle=False))
            except Exception:  # noqa: BLE001 — 손상 맵 한 장이 그룹을 막지 않게
                continue
        return maps
    finally:
        con.close()
