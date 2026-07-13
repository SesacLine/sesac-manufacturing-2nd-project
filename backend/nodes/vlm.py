"""① VLM 웨이퍼맵 판독. 파이프라인에서 실시간으로 LLM을 호출하는 두 노드 중 하나.

Qwen-VL 계열 few-shot/파인튜닝 모델로 웨이퍼 1장당 판독 1건을 낸다.
출력 필드는 산출물_기능목록_유스케이스.md §1 정의를 따른다: pattern은 GraphRAG(③) 입력으로
쓰이고, description/confidence/ambiguity는 GraphRAG 매핑이 없는 6개 패턴에서도 사용자에게
그대로 노출된다(왜 VLM이 단순 분류기보다 넓은 출력을 내는지는 qna_0711.md Q7 참고).
"""

from __future__ import annotations

from ..state import RCAState


def read_wafer_maps(state: RCAState) -> dict:
    """target_lot_ids의 웨이퍼 이미지(라벨 미포함)를 판독해 vlm_results를 채운다.

    TODO: fab.db에서 웨이퍼 이미지를 로드(라벨 컬럼은 절대 읽지 않음) -> VLM 호출 ->
          {lot_id, wafer_id, pattern, spatial, description, severity, confidence, ambiguity} 구성.
    """
    raise NotImplementedError
