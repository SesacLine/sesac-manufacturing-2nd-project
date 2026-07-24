"""kg_rca 테스트 공용 fixture."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.graph_client.kg_client import KGClient

_KG_ROOT = Path(__file__).resolve().parents[1]
_HYPOTHESES = _KG_ROOT / "outputs" / "hypotheses.json"


@pytest.fixture(scope="session")
def matched_causes_by_pattern() -> dict[str, set[str]]:
    """pattern -> 그 pattern의 KG 후보들이 낸 matched_cause 집합.

    실제 파이프라인이 쓰는 KGClient 경로를 그대로 태운다(관측 없이 = 파일 순서).
    coverage/recall(존재 여부)은 순위와 무관하므로 관측·fab.db가 필요 없다 → CI에서 돈다.
    """
    if not _HYPOTHESES.exists():
        pytest.skip("hypotheses.json 없음 — kg_rca 재빌드(6_ask_graphrag.py) 후 활성화")
    client = KGClient(_HYPOTHESES)
    return {
        pattern: {c["matched_cause"] for c in client.get_candidates(pattern)["candidates"]
                  if c.get("matched_cause")}
        for pattern in ("Center", "Scratch", "Edge-Ring")
    }
