"""⑥ 응답생성. 파이프라인에서 실시간으로 LLM을 호출하는 두 노드 중 하나(다른 하나는 ①VLM).

critic_result + graphrag_candidates(인용 재사용)로 최종 카드를 만든다.
Root Cause "확정"이 아니라 "가설(채택) + 근거"까지가 스코프다(산출물_mvp설계서.md §2).
판단불가/미매핑 패턴 케이스는 일반 결과와 구분되는 형태로 표시한다(UC-2, UC-3).
"""

from __future__ import annotations

from ..state import RCAState


def generate_response(state: RCAState, group_id: str) -> dict:
    """critic_result[group_id]를 바탕으로 final_response[group_id]를 채운다.

    TODO: critic_result.status == "insufficient_evidence" -> 판단불가 카드.
          graphrag_candidates가 애초에 비어있었던 그룹(미매핑 패턴) -> "원인 분석 데이터 없음" 카드.
          그 외 -> accepted hypotheses + 근거를 자연어 카드로 합성(LLM 호출).
    """
    raise NotImplementedError
