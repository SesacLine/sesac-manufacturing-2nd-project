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
<<<<<<< Updated upstream
=======


# ── 임베딩 모델 교체 내성 (다른 팀원이 모델만 바꾸고 인덱스 재빌드를 잊는 경우) ──────────
#
# 목표: **에러 없이** 안전하게 축소 동작할 것. 낡은 인덱스로 그럴듯한 점수를 내는 것이
# 가장 나쁘고(조용한 오답), 배치 도중 예외로 죽는 것이 그 다음이다. 둘 다 막는다.

import json

import pytest

from backend.graph_client.semantic_entry import (
    INDEX_FORMAT,
    index_dim,
    load_index,
    load_index_meta,
    save_index,
)


def test_cosine_returns_zero_on_dim_mismatch():
    """차원이 다르면 zip으로 잘라 계산하지 않는다 — 옛 동작은 앞부분만의 무의미한 점수를 냈다."""
    assert _cosine([1.0, 0.0], [1.0, 0.0, 0.0, 0.0]) == 0.0
    assert _cosine([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 1.0


def test_save_load_roundtrip_records_model(tmp_path):
    path = tmp_path / "idx.json"
    save_index(INDEX, path, model="text-embedding-3-small")

    meta = load_index_meta(path)
    assert meta["model"] == "text-embedding-3-small"
    assert meta["format"] == INDEX_FORMAT
    assert meta["dim"] == 3 and meta["count"] == 3
    assert load_index(path).keys() == INDEX.keys()


def test_legacy_flat_index_still_loads(tmp_path):
    """포맷 1(메타 없는 플랫 dict)도 계속 읽힌다 — 포맷을 올렸다고 기존 인덱스가 죽으면 안 된다."""
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(INDEX), encoding="utf-8")

    assert load_index(path).keys() == INDEX.keys()
    assert load_index_meta(path) == {}   # "모른다"는 빈 dict — "다르다"와 구분된다


def test_index_dim_reads_vector_length():
    assert index_dim(INDEX) == 3
    assert index_dim({}) == 0


def test_model_change_disables_matching_instead_of_scoring_garbage():
    """차원이 바뀐 새 모델(예: 3-small 1536 → 3-large 3072)로 질의해도 예외 없이 빈 결과."""
    def wider_embed(text: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]   # 인덱스는 3차원인데 4차원 질의

    sem = SemanticSignatureIndex(INDEX, wider_embed, min_score=0.1)
    assert sem.match("a ring near the edge") == []      # 죽지 않고 빈 결과
    assert sem.disabled_reason is not None
    assert "재빌드" in sem.disabled_reason               # 무엇을 해야 하는지 알려준다


def test_disabled_index_short_circuits_without_embedding_calls():
    """한 번 꺼지면 이후 질의는 임베딩 API를 아예 부르지 않는다(배치 전체가 낭비되지 않게)."""
    calls = []

    def wider_embed(text: str) -> list[float]:
        calls.append(text)
        return [1.0, 0.0, 0.0, 0.0]

    sem = SemanticSignatureIndex(INDEX, wider_embed, min_score=0.1)
    sem.match("first")
    sem.match("second")
    sem.match("third")
    assert len(calls) == 1   # 첫 질의에서만 부르고 그 뒤로는 즉시 반환


def test_embedding_failure_returns_empty_not_raise():
    """임베딩 호출 자체가 실패해도(쿼터·네트워크) 배치를 죽이지 않는다."""
    def boom(text: str) -> list[float]:
        raise RuntimeError("rate limit")

    sem = SemanticSignatureIndex(INDEX, boom)
    assert sem.match("anything") == []


def test_same_dim_different_model_still_matches_but_is_caught_at_load():
    """차원이 같은 모델 교체는 런타임에서 못 잡는다 — 그래서 deps가 메타로 먼저 거른다.

    이 테스트는 그 분업을 고정한다: 런타임 차원 검사는 '차원이 다를 때'만 걸리고,
    같은 차원 교체는 load 단계 모델명 비교(test_deps_semantic)가 책임진다.
    """
    sem = SemanticSignatureIndex(INDEX, _fake_embed, min_score=0.1)
    assert sem.match("ring") != []       # 차원이 같으면 매칭 자체는 계속 된다
    assert sem.disabled_reason is None


def test_reembed_keeps_text_and_replaces_vectors():
    """모델만 바뀐 경우의 경로 — 텍스트는 보존하고 벡터만 새로 만든다(그래프 접속 없음)."""
    from backend.graph_client.semantic_entry import reembed_index

    def new_model_embed(text: str) -> list[float]:
        return [9.0, 9.0, 9.0, 9.0]   # 차원까지 달라진 새 모델을 가정

    out = reembed_index(INDEX, new_model_embed)

    assert out.keys() == INDEX.keys()
    for sig in INDEX:
        assert out[sig]["text"] == INDEX[sig]["text"]        # 재료는 그대로
        assert out[sig]["embedding"] == [9.0, 9.0, 9.0, 9.0]  # 벡터만 교체
    assert index_dim(out) == 4


def test_reembedded_index_matches_again_after_model_change(tmp_path):
    """모델 교체 → 재임베딩 → 다시 정상 매칭되는 전체 흐름."""
    from backend.graph_client.semantic_entry import reembed_index

    # 새 모델: 축 순서가 다른(= 좌표계가 다른) 4차원 임베더
    def new_embed(text: str) -> list[float]:
        t = text.lower()
        return [0.0, float(t.count("center")), float(t.count("line")), float(t.count("ring"))]

    # 1) 낡은 인덱스 + 새 모델 → 차원이 달라 매칭이 꺼진다
    stale = SemanticSignatureIndex(INDEX, new_embed, min_score=0.1)
    assert stale.match("ring at the edge") == []
    assert stale.disabled_reason is not None

    # 2) 재임베딩 후 저장 → 다시 로드 → 정상 매칭
    rebuilt = reembed_index(INDEX, new_embed)
    path = tmp_path / "idx.json"
    save_index(rebuilt, path, model="new-model")
    assert load_index_meta(path)["model"] == "new-model"

    fresh = SemanticSignatureIndex(load_index(path), new_embed, min_score=0.1)
    assert fresh.match("a ring near the edge", k=1)[0][0] == "ring@edge"
    assert fresh.disabled_reason is None
>>>>>>> Stashed changes
