"""step 3 — ④~⑦ 시그니처 평탄화 (#33) 테스트.

정본 스펙: personalspace_rca/sdd/specs/langgraph-skeleton-step3-2026-07-24.md

⚠️ AC 번호는 **이 스펙 기준**이다. 같은 파일의 다른 테스트들(test_skeleton_graph.py 등)에는
선행 스펙(langgraph-skeleton-2026-07-23.md)의 번호가 박혀 있어 겹친다 — 그래서 이 스펙의
`covers:` 태그는 **이 파일에만** 둔다(스펙 "테스트 파일 배치").

핵심: ④⑤⑥⑦은 이제 그룹 1개짜리 좁은 상태(GroupState)를 직접 받는다. 배치 상태(RCAState)의
`groups` 목록을 뒤지거나 `dict[group_id]`로 파고들지 않고, 반환도 중첩 없이 납작하다.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from backend import graph as graph_module
from backend.batch_runner import process_stream_item
from backend.nodes import critic, graphrag, hypothesis, response
from backend.schemas import NODE_TO_STEP_INDEX

GID = "Center-2026-01-01"


def _gstate(**over) -> dict:
    """서브그래프가 실제로 받는 GroupState — `groups` 키가 없다는 게 이 단계의 핵심."""
    base = {
        "group_id": GID,
        "pattern": "Center",
        "lot_ids": ["L1", "L2"],
        "cursor_date": "2026-01-01",
        "cursor_end": "2026-01-31",
        "observation": {"signature": "cluster@center"},
        "candidates": [],
        "hypotheses": [],
    }
    base.update(over)
    return base


_HYP = {
    "cause": "슬러리 유량 불안정",
    "tier": "자동",
    "stage": "CMP",
    "equipment": "CMP-01",
    "citations": [],
    "sentence": "...",
    "evidence": {},
}


class _CapturingKG:
    """get_candidates 호출 인자를 붙잡는 fake KGClient."""

    def __init__(self, candidates: list | None = None) -> None:
        self.calls: list[tuple] = []
        self._candidates = candidates or []

    def get_candidates(self, pattern, observation=None):
        self.calls.append((pattern, observation))
        return {"pattern": pattern, "candidates": list(self._candidates)}


# --- 시그니처 평탄화 (AC-1~6) ---


# covers: AC-1
def test_fetch_kg_candidates_consumes_group_state_and_returns_flat_candidates():
    kg = _CapturingKG([{"cause": "c1"}])
    out = graphrag.fetch_graphrag_candidates(_gstate(), kg)      # groups 키 없는 GroupState

    assert out == {"candidates": [{"cause": "c1"}]}, "중첩 {gid: {...}} 없이 candidates만 돌려줘야 한다"
    (pattern, observation), = kg.calls
    assert pattern == "Center"
    assert observation == {"signature": "cluster@center"}, "③ 관측이 그대로 ④로 도달해야 한다"
    # 리네임(graphrag→kg)은 step 8 — 이름은 아직 유지한다.
    assert hasattr(graphrag, "fetch_graphrag_candidates")


# covers: AC-2
def test_build_hypotheses_takes_group_state_without_group_id():
    assert list(inspect.signature(hypothesis.build_hypotheses).parameters) == ["state", "mcp"]

    out = asyncio.run(hypothesis.build_hypotheses(_gstate(candidates=[]), mcp=None))
    assert out == {"hypotheses": []}, "후보 0건이면 납작한 빈 리스트 (mcp는 안 불린다)"


# covers: AC-3
def test_review_hypotheses_takes_group_state_and_returns_single_critic_result():
    assert list(inspect.signature(critic.review_hypotheses).parameters) == ["state", "mcp"]

    out = asyncio.run(critic.review_hypotheses(_gstate(hypotheses=[]), mcp=None))
    assert out == {
        "critic_result": {"status": "insufficient_evidence", "accepted": [], "rejected": []}
    }, "critic_result가 {gid: ...} 중첩 없이 단건이어야 한다"


# covers: AC-4
def test_generate_response_takes_group_state_only():
    assert list(inspect.signature(response.generate_response).parameters) == ["state"]

    state = _gstate(
        candidates=[{"cause": "c1"}],
        critic_result={"status": "accepted", "accepted": [dict(_HYP)], "rejected": []},
    )
    out = response.generate_response(state)

    assert set(out) == {"final_response"}
    card = out["final_response"]
    assert card["group_id"] == GID and card["pattern"] == "Center"
    assert card["lot_ids"] == ["L1", "L2"] and card["lot_count"] == 2
    assert card["status"] == "reviewed"
    assert card["hypotheses"][0]["hypothesis_id"] == "h0"      # §2.5 정렬 불변식 유지


# covers: AC-5
def test_respond_without_llm_takes_group_state_only_for_both_statuses():
    assert list(inspect.signature(response.respond_without_llm).parameters) == ["state"]

    unmapped = response.respond_without_llm(_gstate(candidates=[], critic_result=None))
    assert unmapped["final_response"]["status"] == "unmapped"
    assert unmapped["final_response"]["hypotheses"] == []

    rejected = {**_HYP, "reject_token": "TIME_ORDER", "reject_reason": "시간 정합 실패"}
    insufficient = response.respond_without_llm(_gstate(
        candidates=[{"cause": "c1"}],
        critic_result={"status": "insufficient_evidence", "accepted": [], "rejected": [rejected]},
    ))
    card = insufficient["final_response"]
    assert card["status"] == "insufficient"
    # 근거 모달(§2.7)이 hypothesis_id로 열리므로 h0부터 채워져 있어야 한다.
    assert card["hypotheses"][0]["hypothesis_id"] == "h0"
    assert card["hypotheses"][0]["verdict"] == "rejected"


# covers: AC-6
def test_no_flattened_node_reaches_into_batch_groups():
    """다섯 함수 어느 것도 배치 목록을 뒤지지 않는다 — 도달 불가 폴백도 같이 사라진다."""
    for fn in (
        graphrag.fetch_graphrag_candidates,
        hypothesis.build_hypotheses,
        critic.review_hypotheses,
        response.generate_response,
        response.respond_without_llm,
    ):
        src = inspect.getsource(fn)
        assert 'state["groups"]' not in src, f"{fn.__name__}이 아직 배치 groups를 뒤진다"
        assert 'else "unknown"' not in src, f"{fn.__name__}에 도달 불가 pattern 폴백이 남아있다"

    assert "if group is None" not in inspect.getsource(hypothesis.build_hypotheses)


# --- 어댑터 제거 (AC-7~9) ---


# covers: AC-7
def test_group_adapters_and_group_for_node_are_gone():
    assert not hasattr(graph_module, "_group_for_node"), "_group_for_node가 아직 남아있다"

    src = inspect.getsource(graph_module._build_group_subgraph)
    assert "fake" not in src, "어댑터가 만들던 가짜 RCAState 재구성이 남아있다"
    assert "async def" not in src, "서브그래프 조립부에 어댑터 클로저가 남아있다(노드 함수를 직접 등록해야 한다)"

    backend_dir = Path(graph_module.__file__).resolve().parent
    for path in backend_dir.rglob("*.py"):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        assert "_group_for_node" not in path.read_text(encoding="utf-8"), f"{path}에 참조가 남았다"


# covers: AC-8
def test_group_subgraph_topology_unchanged():
    """평탄화는 노드 '내용물'만 바꾼다 — 이름·엣지·조건부 분기는 그대로여야 한다(회귀 가드)."""
    sub = graph_module._build_group_subgraph(_CapturingKG(), object())

    for node in (
        "fetch_graphrag_candidates", "build_hypotheses", "review_hypotheses",
        "generate_response", "respond_without_llm",
    ):
        assert node in sub.nodes, f"서브그래프에 {node} 노드가 없다"

    edges = {(e.source, e.target) for e in sub.get_graph().edges}
    for pair in (
        ("__start__", "fetch_graphrag_candidates"),             # 진입점 (set_entry_point)
        ("fetch_graphrag_candidates", "build_hypotheses"),      # 후보 있음
        ("fetch_graphrag_candidates", "respond_without_llm"),   # 후보 0건 컷
        ("build_hypotheses", "review_hypotheses"),
        ("review_hypotheses", "generate_response"),             # 채택 ≥1
        ("review_hypotheses", "respond_without_llm"),           # 채택 0건 컷(환각 억제)
    ):
        assert pair in edges, f"엣지 {pair[0]} -> {pair[1]}가 없다"


class _StubGroupGraph:
    """run_groups가 호출하는 컴파일된 서브그래프 대역 — 넘어온 GroupState를 기록한다."""

    def __init__(self) -> None:
        self.seen: list[dict] = []

    async def ainvoke(self, gstate):
        self.seen.append(gstate)
        return {
            "candidates": [{"cause": "c1"}],
            "hypotheses": [dict(_HYP)],
            "critic_result": {"status": "accepted", "accepted": [dict(_HYP)], "rejected": []},
            "final_response": {"group_id": gstate["group_id"], "status": "reviewed"},
        }


# covers: AC-9
def test_run_groups_batch_accumulation_contract_unchanged():
    """바깥(run_groups)의 누적 계약은 평탄화와 무관하게 그대로다(회귀 가드)."""
    state = {
        "cursor_date": "2026-01-01",
        "cursor_end": "2026-01-31",
        "groups": [
            {"group_id": GID, "pattern": "Center", "lot_ids": ["L1", "L2"], "status": "",
             "observation": {"signature": "cluster@center"}},
            {"group_id": "Normal-x", "pattern": "Normal", "lot_ids": ["L9"], "status": "",
             "observation": None},
        ],
    }
    stub = _StubGroupGraph()
    merged = asyncio.run(graph_module.run_groups(state, stub))

    assert list(merged["graphrag_candidates"]) == [GID], "Normal 그룹은 서브그래프에 안 태운다(§6.3 가드)"
    assert merged["graphrag_candidates"][GID] == {"pattern": "Center", "candidates": [{"cause": "c1"}]}
    assert merged["hypotheses"][GID] == [dict(_HYP)]
    assert merged["critic_result"][GID]["status"] == "accepted"
    assert merged["final_response"][GID]["status"] == "reviewed"
    assert stub.seen[0]["observation"] == {"signature": "cluster@center"}, "③ 관측이 서브그래프 입력으로 전달"
    assert "groups" not in stub.seen[0], "서브그래프에 배치 목록을 넘기지 않는다"


# --- 알고리즘 불변 (AC-10) ---


# covers: AC-10
def test_verify_cache_stays_function_local_and_response_helper_shared():
    """골격설계 §9.3 — 평탄화가 MCP 캐시 범위(그룹당 1개)를 바꾸지 않는다."""
    assert not hasattr(hypothesis, "verify_cache"), "캐시가 모듈 전역으로 새면 그룹 간 공유가 된다"
    assert "verify_cache" in inspect.getsource(hypothesis.build_hypotheses)

    assert "_ordered_hypotheses" in inspect.getsource(response.generate_response)
    assert "_ordered_hypotheses" in inspect.getsource(response.respond_without_llm)


# --- 진행 표시 인덱스 3 복원 (AC-11~12) ---


# covers: AC-11
def test_node_to_step_index_has_no_gap_and_maps_observe_groups_to_3():
    assert NODE_TO_STEP_INDEX["observe_groups"] == 3
    assert set(NODE_TO_STEP_INDEX.values()) == set(range(8)), "0~7에 빈칸이 있으면 진행표시가 건너뛴다"
    # 키는 9개 — ⑦ generate_response와 ⑦' respond_without_llm이 같은 7을 공유하기 때문(§8.2c).
    assert len(NODE_TO_STEP_INDEX) == 9


# covers: AC-12
def test_observe_groups_completion_reaches_step_3():
    new_step, delta = process_stream_item((), {"observe_groups": {"groups": []}}, current_step=2)

    assert new_step == 3, "③ 완료인데 current_step이 2에 머물면 진행표시가 2→4로 건너뛴다"
    assert delta == {"groups": []}, "바깥 노드이므로 부분상태를 누적한다"


# --- 행위 보존 2차 게이트 (AC-13, data) ---

# 직전 main(971323b)에서 캡처한 골든의 rationale 제외 SHA256.
# ⑤가 LLM 에이전트를 쓰면서 rationale(자유서사)만 매 실행 달라지므로 그 필드를 빼고 비교한다
# (같은 코드 2회 캡처 실측: 차이 46곳이 전부 rationale이었다).
BASELINE_MASKED_SHA = "1c758107412ccf071eead4d79f94dc39d29d7d5085e716dd8f082c447ad99828"
AFTER_GOLDEN = (
    Path(__file__).resolve().parents[2]
    / "personalspace_rca" / "sdd" / "verify" / "golden_step3_after.json"
)
MASK_FIELDS = ("rationale",)


def _strip(obj):
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if k not in MASK_FIELDS}
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    return obj


# covers: AC-13
@pytest.mark.data
def test_post_refactor_golden_matches_pre_refactor_masked_sha():
    """2차 게이트. 평탄화 후 캡처본이 있어야 실질 비교를 한다(없으면 skip — 로컬 수동 대상).

    캡처 절차: PYTHONPATH=repo루트 python personalspace_rca/sdd/verify/capture_golden.py \
               personalspace_rca/sdd/verify/golden_step3_after.json
    """
    if not AFTER_GOLDEN.exists():
        pytest.skip(f"평탄화 후 골든 없음({AFTER_GOLDEN}) — capture_golden.py로 캡처 후 재실행")

    after = json.loads(AFTER_GOLDEN.read_text(encoding="utf-8"))
    canon = json.dumps(_strip(after), ensure_ascii=False, sort_keys=True, indent=2)
    sha = hashlib.sha256(canon.encode("utf-8")).hexdigest()

    assert after["n_target_lots"] == 67 and after["n_groups"] == 1
    assert len(after["wafer_readings"]) == 1377
    assert sha == BASELINE_MASKED_SHA, "평탄화가 결과를 바꿨다(행위 보존 위반)"
