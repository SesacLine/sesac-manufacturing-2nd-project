"""옵션 2 — 의미 진입(semantic entry) 단위 테스트.

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
    assert out["candidates"][0]["step"] == "CMP"            # partial arc -> CMP 위로
    assert out["candidates"][0]["entry_signature"] == "ring@edge"
    assert out["candidates"][-1]["step"] == "ETCH"          # full ring 강등
