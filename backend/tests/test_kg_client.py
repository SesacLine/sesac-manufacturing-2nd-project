import json
from pathlib import Path

from backend.graph_client.kg_client import KGClient

def _client(tmp_path: Path, hypotheses: list[dict]) -> KGClient:
    doc = {"questions": [{"pattern": "Center", "hypotheses": hypotheses}]}
    p = tmp_path / "hypotheses.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return KGClient(p)


def _hyp() -> dict:
    """_to_candidate가 직접 인덱싱하는 필수 키만 갖춘 최소 가설."""
    return {
        "path": {"cause": "c1", "failure_mode": None, "step": "CLEAN",
                "evidence": "flow_rate", "evidence_label": "Parameter"},
        "verification": {"fab_table": "telemetry", "direction": "low"},
        "score": {"occurrence_prior": "high"},
        "tier": "자동",
        "sentence": "...",
    }


def test_matched_cause_extraction(tmp_path):
    # mapping 세 상태: 정상 / 명시적 null / 키 자체 없음 — 전부 안 죽고 값만 갈려야 한다
    hyps = [
        _hyp() | {"mapping": {"matched_cause": "clean_nozzle_clog", "score": 1.0}},
        _hyp() | {"mapping": None},
        _hyp(),
    ]
    candidates = _client(tmp_path, hyps).get_candidates("Center")["candidates"]
    assert [c["matched_cause"] for c in candidates] == ["clean_nozzle_clog", None, None]