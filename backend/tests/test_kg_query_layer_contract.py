"""LiveKGClient ↔ kg_rca/6_ask_graphrag.py 계약 테스트.

LiveKGClient는 순회 로직을 복사하지 않고 kg_rca의 빌드 스크립트를 importlib으로 직접
불러다 쓴다(단일 진실). 대가로 kg_rca 쪽 함수명·인자·상수가 바뀌면 backend가 **조용히**
깨진다 — 배치를 돌려야 비로소 AttributeError/TypeError가 난다.

그래서 "backend가 쓰는 심볼이 여전히 존재하고, 우리가 부르는 방식으로 부를 수 있는가"만
여기서 못 박는다. Neo4j·LLM은 부르지 않으므로 CI(-m "not data")에서 그대로 돈다.
"""

from __future__ import annotations

import inspect

import pytest

from backend.graph_client.live_kg_client import _query_layer
from backend.state import Tier
from typing import get_args


@pytest.fixture(scope="module")
def q():
    """kg_rca/6_ask_graphrag.py 모듈. 로드 자체가 실패하면 여기서 바로 드러난다."""
    return _query_layer()


# LiveKGClient가 실제로 호출하는 함수와 그 호출 형태(위치 인자 개수).
# 값은 bind()에 넣을 더미 인자 — 타입은 안 보고 arity/키워드만 검사한다.
_CALL_SITES = {
    "fetch_hypotheses": ("<graph>", "Center"),                  # 패턴 진입
    "fetch_hypotheses_by_signature": ("<graph>", "ring@edge"),  # 형상 진입
    "fetch_hypotheses_step_direct": ("<graph>", "Center"),      # 패턴 레벨 원인 합류
    "match_mapping": ("Center", "cause_id", "cause name"),      # matched_cause/mapped_process
    "scenario_hint": ({},),                                     # MCP 체인 라우팅 힌트
    "_fallback_sentence": ("Center", {}),                       # 가설 문장(LLM 없이)
}


@pytest.mark.parametrize("name", sorted(_CALL_SITES))
def test_required_function_exists(q, name):
    assert hasattr(q, name), (
        f"kg_rca/6_ask_graphrag.py에 {name}()가 없다 — LiveKGClient._row_to_candidate/"
        f"get_candidates가 이 함수를 부른다. 이름이 바뀌었다면 live_kg_client.py도 같이 고칠 것"
    )
    assert callable(getattr(q, name))


@pytest.mark.parametrize("name", sorted(_CALL_SITES))
def test_call_signature_still_binds(q, name):
    """우리가 넘기는 인자 개수로 호출이 성립하는지 — 실행은 하지 않는다."""
    signature = inspect.signature(getattr(q, name))
    try:
        signature.bind(*_CALL_SITES[name])
    except TypeError as exc:
        pytest.fail(
            f"{name}{signature} 를 live_kg_client.py가 부르는 형태"
            f"{_CALL_SITES[name]!r}로 호출할 수 없다: {exc}"
        )


def test_tier_constants_exist(q):
    """TIER_TAG/TIER_NONE은 함수가 아니라 상수로 참조된다(_row_to_candidate)."""
    assert isinstance(q.TIER_TAG, dict)
    assert q.TIER_NONE in q.TIER_TAG, "TIER_NONE이 TIER_TAG의 키가 아니다"


def test_tier_tag_matches_state_tier_literal(q):
    """TIER_TAG의 값이 state.Tier 3종과 정확히 일치해야 한다.

    ④의 출력 불변식 "tier는 자동/반자동/근거없음 중 하나"를 지탱하는 지점 —
    kg_rca가 등급 이름을 하나라도 바꾸면 ⑤의 tier 분기와 ⑥의 P5 판정이 조용히 어긋난다.
    """
    assert set(q.TIER_TAG.values()) == set(get_args(Tier))


def test_signature_entry_query_shape_unchanged(q):
    """형상 진입 쿼리가 여전히 SpatialSignature를 $signature 파라미터로 받는지.

    test_live_kg_client.py의 FakeGraph 스텁이 'SpatialSignature {id: $signature}' 문자열로
    분기하므로, 쿼리가 바뀌면 그 테스트는 조용히 빈 행을 받고 통과해 버린다(가짜 green).
    """
    assert hasattr(q, "SIGNATURE_ENTRY_QUERY"), "형상 진입 쿼리 상수가 사라졌다"
    assert "SpatialSignature {id: $signature}" in q.SIGNATURE_ENTRY_QUERY, (
        "형상 진입 쿼리의 매칭 형태가 바뀌었다 — "
        "backend/tests/test_live_kg_client.py의 FakeGraph 스텁도 같이 고칠 것"
    )
