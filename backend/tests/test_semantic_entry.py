"""의미 진입(semantic entry — 자연어 임베딩 매칭) 단위 테스트.

실제 OpenAI/Neo4j 없이 결정적 가짜 임베더 + FakeGraph로 검증한다.
"""

from __future__ import annotations

from backend.graph_client import LiveKGClient
from backend.graph_client.semantic_entry import (
    SemanticSignatureIndex,
    _cosine,
    _signature_text,
)


def _fake_embed(text: str) -> list[float]:
    """키워드 빈도로 만드는 결정적 3차원 임베딩 (ring / center / line 축)."""
    t = text.lower()
    return [float(t.count("ring")), float(t.count("center")), float(t.count("line"))]


INDEX = {
    "ring@edge": {"text": "ring edge ring", "embedding": _fake_embed("ring edge ring")},
    "blob@center": {"text": "center blob", "embedding": _fake_embed("center blob")},
    "line@any": {"text": "line streak", "embedding": _fake_embed("line streak")},
}


def test_cosine_basics():
    assert _cosine([1, 0, 0], [1, 0, 0]) == 1.0
    assert _cosine([1, 0, 0], [0, 1, 0]) == 0.0


def test_signature_text_includes_shape_zone_and_descs():
    row = {"shape": "ring", "zone": "edge",
           "descs": ["링 형상"], "quotelists": [["dense ring"]], "chunktexts": ["ring at the edge"]}
    text = _signature_text(row)
    assert "shape=ring zone=edge" in text
    assert "링 형상" in text and "dense ring" in text


def test_match_ranks_correct_signature_top():
    sem = SemanticSignatureIndex(INDEX, _fake_embed)
    assert sem.match("a broken ring at the edge", k=1)[0][0] == "ring@edge"
    assert sem.match("a solid blob at the center", k=1)[0][0] == "blob@center"
    assert sem.match("a diagonal line across the wafer", k=1)[0][0] == "line@any"


def test_match_is_deterministic_and_topk():
    sem = SemanticSignatureIndex(INDEX, _fake_embed)
    out = sem.match("ring ring center", k=2)
    assert len(out) == 2
    assert out == sem.match("ring ring center", k=2)   # 재현성


def test_min_score_filters_dissimilar():
    sem = SemanticSignatureIndex(INDEX, _fake_embed)
    # 어떤 형상 키워드도 없는 서술 → 전 시그니처와 코사인 0 → 하한 미달 → 빈 결과
    assert sem.match("completely unrelated telemetry noise", k=3) == []
    # 하한을 낮추면 다시 나온다 (하한이 실제로 걸러냈다는 증거)
    loose = SemanticSignatureIndex(INDEX, _fake_embed, min_score=-1.0)
    assert len(loose.match("ring", k=3)) == 3


def test_unknown_with_garbage_description_returns_empty():
    # Unknown + 아무 형상과도 안 닮은 서술 → 진입 0 → candidates=[] (insufficient_evidence 흐름)
    sem = SemanticSignatureIndex(INDEX, _fake_embed)
    client = LiveKGClient(graph=FakeGraph(), semantic_index=sem, semantic_k=3)
    out = client.get_candidates("Unknown", observation={"description": "unrelated noise"})
    assert out["candidates"] == []
    assert "entry_signatures" not in out


def test_known_with_garbage_description_keeps_pattern_level_only():
    # 기지 패턴 + 안 닮은 서술 → 형상 진입은 0이지만 패턴 레벨(step/direct) 원인은 유지
    sem = SemanticSignatureIndex(INDEX, _fake_embed)
    client = LiveKGClient(graph=KnownPatternFakeGraph(), semantic_index=sem, semantic_k=3)
    out = client.get_candidates("Edge-Ring", observation={"description": "unrelated noise"})
    assert "entry_signatures" not in out
    assert {c["step"] for c in out["candidates"]} == {"DEPO"}   # step 경로만 (형상 경로 없음)


# --- LiveKGClient 의미 진입 브랜치 ---

def _sig_row(step, angular, clock):
    return {"signature": "ring@edge", "step": step, "failure_mode": f"fm_{step}",
            "failure_mode_name": step, "cause": f"cause_{step}", "cause_name": step,
            "cause_description": "", "unverifiable_signals": None, "evidence": "p",
            "evidence_name": "p", "evidence_label": "Parameter", "fab_table": "telemetry",
            "consumable": None, "direction": "high", "occurrence_prior": "high",
            "density": "low" if angular == "partial" else "high",
            "continuity": "discontinuous" if angular == "partial" else "continuous",
            "angular_coverage": angular, "clock_positions": clock, "confidence": 3.0,
            "quotes": [], "chunk_ids": [f"doc_H#c_{step}"]}


class FakeGraph:
    def query(self, cypher, params=None):
        if "SpatialSignature {id: $signature}" in cypher:
            return [_sig_row("ETCH", "full", []), _sig_row("CMP", "partial", [5, 6, 7])]
        return []


def test_live_client_semantic_entry_uses_description():
    sem = SemanticSignatureIndex(INDEX, _fake_embed)
    client = LiveKGClient(graph=FakeGraph(), semantic_index=sem, semantic_k=1)
    obs = {"description": "a broken ring at the edge",
           "angular_coverage": "partial", "clock_positions": [5, 6, 7],
           "density": "low", "continuity": "discontinuous"}
    out = client.get_candidates("Unknown", observation=obs)
    assert out["entry_signatures"] == ["ring@edge"]        # NL -> 의미 매칭으로 진입
    steps = {c["step"] for c in out["candidates"]}
    assert "ETCH" not in steps                             # full ring 강한 모순 → 드롭
    assert out["candidates"][0]["step"] == "CMP"            # partial arc -> CMP
    assert out["candidates"][0]["entry_signature"] == "ring@edge"


def test_query_text_combines_location_and_morphology():
    obs = {"location_text": "defects around the entire wafer edge",
           "morphology_text": "dense unbroken circular band"}
    text = LiveKGClient._query_text(obs)
    assert "entire wafer edge" in text and "circular band" in text
    # 둘 다 없으면 description 폴백
    assert LiveKGClient._query_text({"description": "x"}) == "x"
    assert LiveKGClient._query_text({}) is None


def _step_row(step, cause):
    return {"step": step, "failure_mode": f"fm_{step}", "failure_mode_name": step,
            "cause": cause, "cause_name": cause, "cause_description": "",
            "unverifiable_signals": None, "evidence": "p_step", "evidence_name": "p",
            "evidence_label": "Parameter", "fab_table": "telemetry", "consumable": None,
            "direction": "high", "occurrence_prior": "high", "confidence": 3.0,
            "quotes": [], "chunk_ids": [f"doc#c_{step}"]}


class KnownPatternFakeGraph:
    """(A) 기지 패턴 경로: HAS_SIGNATURE 범위 + 형상 진입 + step 경로를 흉내낸다."""

    def query(self, cypher, params=None):
        if "HAS_SIGNATURE" in cypher:
            return [{"sig": "ring@edge"}]               # Edge-Ring이 좁히는 시그니처
        if "SpatialSignature {id: $signature}" in cypher:
            return [_sig_row("ETCH", "full", []), _sig_row("CMP", "partial", [5, 6, 7])]
        if "ARISES_IN" in cypher:                        # HYPOTHESIS_QUERY (step 경로)
            return [_step_row("DEPO", "cause_depo_pattern_level")]
        return []                                        # DIRECT_QUERY 등은 비움


def test_known_pattern_scopes_signatures_and_keeps_pattern_level():
    sem = SemanticSignatureIndex(INDEX, _fake_embed)
    client = LiveKGClient(graph=KnownPatternFakeGraph(), semantic_index=sem, semantic_k=3)
    obs = {"location_text": "defects around the entire wafer edge forming a ring",
           "morphology_text": "a dense circular ring band, broken on one side",
           "angular_coverage": "partial", "clock_positions": [5, 6, 7],
           "density": "low", "continuity": "discontinuous"}
    out = client.get_candidates("Edge-Ring", observation=obs)
    assert out["entry_signatures"] == ["ring@edge"]        # 패턴이 범위 제한 -> ring@edge만
    steps = {c["step"] for c in out["candidates"]}
    assert "ETCH" not in steps                             # full ring 형상 후보 → 강한 모순 드롭
    assert {"CMP", "DEPO"} <= steps                        # partial 형상(CMP) + 패턴 레벨(DEPO) 유지
    assert out["candidates"][0]["step"] == "CMP"           # partial arc -> CMP 최상위
    depo = next(c for c in out["candidates"] if c["step"] == "DEPO")
    assert depo["morphology"] is None                      # 패턴 레벨 경로는 morphology 없음(드롭 대상 아님)


def test_natural_language_takes_priority_over_signature():
    # VLM이 메인 — 관측에 signature(geometry)와 자연어가 둘 다 있으면 자연어(의미 진입)가 우선.
    sem = SemanticSignatureIndex(INDEX, _fake_embed)
    client = LiveKGClient(graph=FakeGraph(), semantic_index=sem, semantic_k=1)
    obs = {"signature": "line@any",                       # geometry가 준 폴백값
           "description": "a broken ring at the edge",     # VLM 자연어(메인)
           "angular_coverage": "partial", "clock_positions": [5, 6, 7]}
    out = client.get_candidates("Unknown", observation=obs)
    assert out["entry_signatures"] == ["ring@edge"]        # 자연어로 진입 — signature(line@any) 무시


def test_signature_used_when_no_natural_language():
    # 자연어가 없으면(VLM 미연동) signature(geometry) 폴백으로 진입.
    sem = SemanticSignatureIndex(INDEX, _fake_embed)
    client = LiveKGClient(graph=FakeGraph(), semantic_index=sem)
    obs = {"signature": "ring@edge", "angular_coverage": "partial", "clock_positions": [5, 6, 7]}
    out = client.get_candidates("Unknown", observation=obs)
    assert out["entry_signatures"] == ["ring@edge"]        # NL 없음 → signature 폴백


def test_exact_signature_on_known_pattern_keeps_pattern_level():
    # quantitative가 signature를 직접 준 경우(die-matrix 규칙 진입). 기지 패턴이면 형상 경로 +
    # 패턴 레벨(ARISES_IN/ATTRIBUTED_TO)을 둘 다 내야 한다(자연어 진입과 대칭 — 비대칭 수정).
    client = LiveKGClient(graph=KnownPatternFakeGraph())   # semantic_index 없이도 동작
    obs = {"signature": "ring@edge", "angular_coverage": "full",
           "clock_positions": [], "density": "high", "continuity": "continuous"}
    out = client.get_candidates("Edge-Ring", observation=obs)
    assert out["entry_signatures"] == ["ring@edge"]
    steps = {c["step"] for c in out["candidates"]}
    assert "DEPO" in steps                                 # 패턴 레벨 원인 유지(비대칭 수정)
    assert "ETCH" in steps                                 # full 관측과 일치하는 형상 후보
    assert "CMP" not in steps                              # partial 형상은 full 관측과 상충 → 드롭
