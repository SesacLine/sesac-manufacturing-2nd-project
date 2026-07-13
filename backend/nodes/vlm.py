"""① VLM 웨이퍼맵 판독. 파이프라인에서 실시간으로 LLM을 호출하는 두 노드 중 하나.

Qwen-VL 계열 few-shot/파인튜닝 모델로 웨이퍼 1장당 판독 1건을 낸다.
출력 필드는 산출물_기능목록_유스케이스.md §1 정의를 따른다: pattern은 GraphRAG(③) 입력으로
쓰이고, description/confidence/ambiguity는 GraphRAG 매핑이 없는 6개 패턴에서도 사용자에게
그대로 노출된다(왜 VLM이 단순 분류기보다 넓은 출력을 내는지는 qna_0711.md Q7 참고).
"""

from __future__ import annotations

import os
import sqlite3

from ..state import RCAState

# TODO(Walking Skeleton, 스텝7에서 교체 대상): 실제 Qwen-VL 호출 대신 "Center" 고정 반환.
# ⓪~⑥ 전체 배선을 LLM 비용 없이 먼저 검증하기 위한 임시값이다(qna_0711.md Q7, 산출물_mvp설계서.md §4 슬라이스0).
_HARDCODED_PATTERN = "Center"


def read_wafer_maps(state: RCAState) -> dict:
    """target_lot_ids의 웨이퍼 이미지(라벨 미포함)를 판독해 vlm_results를 채운다.

    지금은 실제 이미지 판독 없이 fab.db에서 wafer_id 목록만 가져와 고정 패턴을 붙인다.
    """
    lot_ids = state["target_lot_ids"]
    if not lot_ids:
        return {"vlm_results": []}

    con = sqlite3.connect(os.environ["FAB_DB"])
    con.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(lot_ids))
    rows = con.execute(
        f"SELECT lot_id, wafer_id FROM wafer WHERE lot_id IN ({placeholders})", lot_ids
    ).fetchall()
    con.close()

    vlm_results = [
        {
            "lot_id": row["lot_id"],
            "wafer_id": row["wafer_id"],
            "pattern": _HARDCODED_PATTERN,
            "spatial": "cluster@center",
            "description": "Walking Skeleton 임시값 — 실제 VLM 미연동",
            "severity": "unknown",
            "confidence": 0.5,
            "ambiguity": True,
        }
        for row in rows
    ]
    return {"vlm_results": vlm_results}
