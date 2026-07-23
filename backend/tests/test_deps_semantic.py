"""deps의 의미 진입(semantic index) 배선 테스트.

싱글턴 모듈이라 각 테스트 앞에서 로드 상태를 리셋한다. OpenAI API는 부르지 않는다 —
성공 경로는 OpenAIEmbeddings를 가짜로 바꿔 검증한다.
"""

from __future__ import annotations

import json

import pytest

from backend import deps


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch):
    monkeypatch.setattr(deps, "_semantic", None)
    monkeypatch.setattr(deps, "_semantic_loaded", False)


def test_kg_semantic_off_returns_none(monkeypatch):
    monkeypatch.setenv("KG_SEMANTIC", "0")
    assert deps._semantic_index() is None


def test_missing_index_file_returns_none(monkeypatch, tmp_path):
    monkeypatch.delenv("KG_SEMANTIC", raising=False)
    monkeypatch.setenv("KG_SIGNATURE_INDEX_PATH", str(tmp_path / "없는파일.json"))
    assert deps._semantic_index() is None


def test_embedder_failure_degrades_to_none(monkeypatch, tmp_path):
    # 인덱스는 있지만 임베더 초기화가 실패(키 없음 등)해도 기동은 살아야 한다.
    index_path = tmp_path / "signature_index.json"
    index_path.write_text(json.dumps({"ring@edge": {"text": "t", "embedding": [1.0]}}))
    monkeypatch.delenv("KG_SEMANTIC", raising=False)
    monkeypatch.setenv("KG_SIGNATURE_INDEX_PATH", str(index_path))

    import langchain_openai

    def _boom(*a, **k):
        raise RuntimeError("no api key")

    monkeypatch.setattr(langchain_openai, "OpenAIEmbeddings", _boom)
    assert deps._semantic_index() is None


def test_valid_index_wires_semantic(monkeypatch, tmp_path):
    index_path = tmp_path / "signature_index.json"
    index_path.write_text(json.dumps({
        "ring@edge": {"text": "ring at edge", "embedding": [1.0, 0.0]},
        "blob@center": {"text": "blob at center", "embedding": [0.0, 1.0]},
    }))
    monkeypatch.delenv("KG_SEMANTIC", raising=False)
    monkeypatch.setenv("KG_SIGNATURE_INDEX_PATH", str(index_path))

    class _FakeEmbeddings:
        def __init__(self, model):
            assert model == deps.EMBEDDING_MODEL     # 빌드/런타임 모델 일치 강제 확인

        def embed_query(self, text):
            return [1.0, 0.0] if "ring" in text else [0.0, 1.0]

    import langchain_openai
    monkeypatch.setattr(langchain_openai, "OpenAIEmbeddings", _FakeEmbeddings)

    sem = deps._semantic_index()
    assert sem is not None
    assert sem.match("a ring near the edge", k=1)[0][0] == "ring@edge"   # 실제 매칭까지 동작
    assert deps._semantic_index() is sem                                  # 싱글턴 캐시


def test_min_score_env_override(monkeypatch, tmp_path):
    index_path = tmp_path / "signature_index.json"
    index_path.write_text(json.dumps({"ring@edge": {"text": "t", "embedding": [1.0, 0.0]}}))
    monkeypatch.delenv("KG_SEMANTIC", raising=False)
    monkeypatch.setenv("KG_SIGNATURE_INDEX_PATH", str(index_path))
    monkeypatch.setenv("KG_SEMANTIC_MIN_SCORE", "0.99")

    class _FakeEmbeddings:
        def __init__(self, model): ...
        def embed_query(self, text):
            return [0.7, 0.7]   # ring@edge와 코사인 ≈0.707 — 0.99 하한엔 미달

    import langchain_openai
    monkeypatch.setattr(langchain_openai, "OpenAIEmbeddings", _FakeEmbeddings)

    sem = deps._semantic_index()
    assert sem is not None
    assert sem.match("whatever", k=1) == []   # env 하한이 실제로 적용됨


def test_default_index_path_points_to_kg_rca_outputs(monkeypatch):
    monkeypatch.delenv("KG_SIGNATURE_INDEX_PATH", raising=False)
    p = deps._signature_index_path()
    assert p.parts[-3:] == ("kg_rca", "outputs", "signature_index.json")
