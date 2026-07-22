"""옵션 2 — 의미(semantic) 진입.

VLM의 자연어 서술(location_text/morphology_text)을 임베딩해 SpatialSignature에 **유사도로**
진입 노드를 고른다. enum 정확일치(shape@zone)를 대체하되, 진입 뒤 순회 본체는 그대로
결정적이다(Text2Cypher 아님 — 환각/비결정 없음).

매칭 대상 텍스트는 각 시그니처의 FORMS_IN 서술 + 원문 quote + 그 시그니처를 언급한 청크 본문을
모아 만든다(빌드타임 1회, 캐시). 시그니처가 8개뿐이라 벡터 인덱스 없이 in-app 코사인으로 충분.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

# 각 시그니처의 매칭용 서술 재료를 그래프에서 모은다.
SIGNATURE_TEXT_QUERY = """
MATCH (sg:SpatialSignature)
OPTIONAL MATCH (sg)-[f:FORMS_IN]->(:ProcessStep)
OPTIONAL MATCH (ch:Chunk)-[:MENTIONS]->(sg)
WITH sg,
     collect(DISTINCT f.description) AS descs,
     collect(DISTINCT f.quotes)      AS quotelists,
     collect(DISTINCT ch.text)       AS chunktexts
RETURN sg.id AS sig, sg.shape AS shape, sg.zone AS zone,
       descs, quotelists, chunktexts
ORDER BY sig
"""


def _signature_text(row: dict) -> str:
    """시그니처 하나의 매칭용 텍스트(형상/구역 + 서술 + 원문 + 언급 청크)."""
    parts = [f"shape={row['shape']} zone={row['zone']}"]
    for desc in (row.get("descs") or []):
        if desc:
            parts.append(desc)
    for quotes in (row.get("quotelists") or []):
        for quote in (quotes or []):
            if quote:
                parts.append(quote)
    for text in (row.get("chunktexts") or []):
        if text:
            parts.append(text[:400])
    seen: set[str] = set()
    deduped = [p for p in parts if not (p in seen or seen.add(p))]
    return "\n".join(deduped)


def build_signature_index(graph, embed_fn) -> dict:
    """SpatialSignature별 {text, embedding} 인덱스를 만든다(빌드타임 1회). embed_fn: str->list[float]."""
    index: dict[str, dict] = {}
    for row in graph.query(SIGNATURE_TEXT_QUERY):
        text = _signature_text(row)
        index[row["sig"]] = {"text": text, "embedding": embed_fn(text)}
    return index


def save_index(index: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")


def load_index(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class SemanticSignatureIndex:
    """빌드된 인덱스 + 임베더로 자연어 질의를 top-k 시그니처로 매칭한다."""

    def __init__(self, index: dict, embed_fn) -> None:
        self._index = index
        self._embed = embed_fn

    def match(self, query_text: str, k: int = 3, allowed: set | None = None) -> list[tuple[str, float]]:
        """(sig_id, cosine) 상위 k개. 결정적(같은 임베딩이면 같은 순서).

        allowed가 주어지면 그 시그니처 집합으로 매칭 범위를 제한한다((A) 방식: pattern_candidate가
        HAS_SIGNATURE 시그니처로 좁힌 범위). None이면 인덱스 전체(미지 패턴).
        """
        query_vec = self._embed(query_text)
        scored = [
            (sig, _cosine(query_vec, entry["embedding"]))
            for sig, entry in self._index.items()
            if allowed is None or sig in allowed
        ]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))  # 유사도 내림차순, 동점은 id로 결정적
        return scored[:k]
