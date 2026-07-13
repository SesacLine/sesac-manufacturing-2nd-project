"""③ GraphRAG 원인후보 조회. 결정적 조회, 그룹당 1회. LLM 호출 없음(kg_rca가 빌드타임에 이미 순회 완료).

DefectPattern이 Center/Edge-Ring/Scratch 3종 밖이면 candidates가 빈 리스트로 남고,
이 그룹은 ④~⑥을 건너뛴다(UC-3, 미매핑 패턴 흐름).
"""

from __future__ import annotations

from ..graph_client import KGClient
from ..state import RCAState


def fetch_graphrag_candidates(state: RCAState, kg_client: KGClient) -> dict:
    """groups의 각 pattern으로 kg_client.get_candidates를 호출해 graphrag_candidates를 채운다.

    TODO: group_id별로 KGClient.get_candidates(pattern) 호출 -> GraphRAGResult로 저장.
          Center/Edge-Ring/Scratch가 아닌 패턴은 candidates=[]로 두고 status만 표시.
    """
    raise NotImplementedError
