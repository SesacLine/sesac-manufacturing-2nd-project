"""LiveKGClient (형상 직접 진입 + angular 판별자) 단위 테스트.

실제 Neo4j 없이 FakeGraph로 순회 함수(fetch_hypotheses_by_signature)까지 태워서
row->candidate 매핑 + 재랭킹을 결정적으로 검증한다.
"""

from __future__ import annotations

from backend.graph_client import LiveKGClient


def _row(step, cause, angular, clock, density, continuity):
    """SIGNATURE_ENTRY_QUERY가 낼 법한 평탄한 행 하나."""
    return {
        "signature": "ring@edge",
        "step": step,
        "failure_mode": f"fm_{step.lower()}",
        "failure_mode_name": f"{step} failure",
        "cause": cause,
        "cause_name": cause.replace("_", " "),
        "cause_description": "",
        "unverifiable_signals": None,
        "evidence": "some_param",
        "evidence_name": "some param",
        "evidence_label": "Parameter",
        "fab_table": "telemetry",
        "consumable": None,
        "direction": "high",
        "occurrence_prior": "high",
        "density": density,
        "continuity": continuity,
        "angular_coverage": angular,
        "clock_positions": clock,
        "confidence": 3.0,
        "quotes": [],
        "chunk_ids": [f"doc_H#c_{step.lower()}"],
    }


class FakeGraph:
    """SIGNATURE_ENTRY_QUERY에만 canned 행을 돌려주는 스텁."""

    def __init__(self, sig_rows):
        self._sig_rows = sig_rows

    def query(self, cypher, params=None):
        if "SpatialSignature {id: $signature}" in cypher:
            return [dict(r) for r in self._sig_rows]
        return []


ROWS = [
    _row("ETCH", "etch_nonuniformity", "full", [], "high", "continuous"),
    _row("CMP", "cmp_edge_overpolish", "partial", [5, 6, 7], "low", "discontinuous"),
]

OBS_PARTIAL = {
    "signature": "ring@edge",
    "angular_coverage": "partial",
    "clock_positions": [5, 6, 7],
    "density": "low",
    "continuity": "discontinuous",
}


def test_signature_entry_returns_all_forms_in_edges_with_morphology():
    client = LiveKGClient(graph=FakeGraph(ROWS))
    out = client.get_candidates("Unknown", observation={"signature": "ring@edge"})
    steps = {c["step"] for c in out["candidates"]}
    assert steps == {"ETCH", "CMP"}           # 형상 진입은 두 엣지 모두 노출
    assert all(c["morphology"] is not None for c in out["candidates"])  # morphology 보존


def test_angular_discriminator_drops_contradicting_full_ring():
    # 관측 = partial arc → full-ring(ETCH) 후보는 강한 모순으로 리스트에서 제외, partial(CMP)만.
    client = LiveKGClient(graph=FakeGraph(ROWS))
    out = client.get_candidates("Unknown", observation=OBS_PARTIAL)
    cands = out["candidates"]
    steps = {c["step"] for c in cands}
    assert "ETCH" not in steps                # full ring 후보 드롭됨
    assert cands[0]["step"] == "CMP"
    assert cands[0]["morphology_score"] == 0.0
    assert cands[0]["rank"] == 1              # 재랭킹 후 rank 재부여


def test_unknown_pattern_without_signature_returns_empty():
    client = LiveKGClient(graph=FakeGraph(ROWS))
    out = client.get_candidates("Unknown", observation={})
    assert out == {"pattern": "Unknown", "candidates": []}


def test_candidate_shape_has_required_fields():
    client = LiveKGClient(graph=FakeGraph(ROWS))
    out = client.get_candidates("Unknown", observation=OBS_PARTIAL)
    c = out["candidates"][0]
    for field in ("cause", "step", "signature", "morphology", "tier",
                  "evidence_label", "sentence", "citations", "scenario_hint"):
        assert field in c
    assert c["tier"] == "자동"                # Parameter -> 자동
    assert c["scenario_hint"] == "A3"          # Parameter -> A3
    assert isinstance(c["sentence"], str) and c["sentence"]
