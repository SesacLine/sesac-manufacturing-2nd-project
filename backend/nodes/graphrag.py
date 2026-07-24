"""④ KG 원인후보 조회. 결정적 조회, 그룹당 1회. LLM 호출 없음(kg_rca가 빌드타임에 이미 순회 완료).

DefectPattern이 Center/Edge-Ring/Scratch 3종 밖이면 candidates가 빈 리스트로 남고,
이 그룹은 ⑤~⑦을 건너뛴다(UC-3, 미매핑 패턴 흐름).
"""

from __future__ import annotations

from ..graph_client import KGClient
from ..state import RCAState


def fetch_graphrag_candidates(state: RCAState, kg_client: KGClient) -> dict:
    """groups의 각 pattern으로 kg_client.get_candidates를 호출해 graphrag_candidates를 채운다.

    Center/Edge-Ring/Scratch가 아닌 패턴은 KGClient가 이미 candidates=[]를 돌려준다
    (kg_client.py 참고) — 여기서 따로 걸러낼 필요 없이 그대로 저장하면 route_on_candidates가
    빈 리스트를 보고 UC-3(미매핑 패턴) 처리를 한다.
    """
    graphrag_candidates = {
        group["group_id"]: kg_client.get_candidates(
            group["pattern"],
            # 그룹 단위 관측(state.Observation) — ③ observe_groups가 채운다(현재는 패턴별
            # 스켈레톤 템플릿, 실제 VLM/스택맵 die-matrix 연동 시 교체. 웨이퍼별 집계 없음).
            # location/morphology_text는 의미 진입에, angular 등 구조화는 판별자 재정렬에 쓰인다.
            observation=group.get("observation"),
        )
        for group in state["groups"]
    }
    return {"graphrag_candidates": graphrag_candidates}
