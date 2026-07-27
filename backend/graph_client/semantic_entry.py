"""의미(semantic) 진입 — VLM 자연어를 임베딩 유사도로 SpatialSignature에 매칭한다.

VLM의 자연어 서술(location_text/morphology_text)을 임베딩해 SpatialSignature에 **유사도로**
진입 노드를 고른다. enum 정확일치(shape@zone)를 대체하되, 진입 뒤 순회 본체는 그대로
결정적이다(Text2Cypher 아님 — 환각/비결정 없음).

매칭 대상 텍스트는 각 시그니처의 FORMS_IN 서술 + 원문 quote + 그 시그니처를 언급한 청크 본문을
모아 만든다(빌드타임 1회, 캐시). 시그니처가 8개뿐이라 벡터 인덱스 없이 in-app 코사인으로 충분.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

# 인덱스 빌드와 런타임 질의는 반드시 같은 임베딩 모델을 써야 한다 —
# 모델이 다르면 벡터 공간이 달라 코사인 비교가 무의미해진다. 양쪽 다 이 상수를 참조할 것
# (빌더 kg_rca/7_build_signature_index.py · 런타임 backend/deps.py).
#
# env로 뺀 이유: 모델 교체를 코드 수정 없이 .env 한 줄로 하게 하려는 것이다. 상수를 직접
# 고치면 빌더와 런타임이 **동시에** 새 모델로 움직이는데, 인덱스 파일은 옛 벡터를 그대로
# 들고 있어서 아무 에러 없이 점수만 조용히 망가진다. env로 두면 교체 사실이 설정에 남고,
# 아래 정합성 검사가 낡은 인덱스를 실제로 잡아낸다.
EMBEDDING_MODEL = os.getenv("KG_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)

# 매칭 하한 — 이보다 덜 닮으면 진입 시그니처로 인정하지 않는다.
# top-k는 "안 닮아도 무조건 k개"를 돌려주므로, 하한 없이는 어떤 형상과도 무관한 관측이
# 그럴듯한 후보를 달고 나온다(환각 억제 원칙 위배). 하한 미달이면 빈 결과를 내고,
# 호출부(LiveKGClient)는 기지 패턴이면 패턴 레벨 원인만, Unknown이면 candidates=[]
# (→ insufficient_evidence 흐름)로 처리한다.
#
# ⚠️ 이 값은 **모델마다 다시 재야 한다**. 코사인 점수 분포가 모델별로 달라서 그대로
# 물려받으면 오답이 문턱을 넘거나 정답이 통째로 잘린다. 실측한 모델만 아래 표에 적고,
# 표에 없는 모델은 DEFAULT를 쓰되 "미보정"임을 로그로 알린다(추측값을 조용히 쓰지 않는다).
DEFAULT_MIN_MATCH_SCORE = 0.4

# 실측 근거(07-23): text-embedding-3-small — 정답 매칭 0.53~0.71, 오답 상위 0.44~0.48.
#   정답/오답 간격이 0.48↔0.53으로 얇다는 점에 유의(모델을 바꾸면 이 간격부터 다시 볼 것).
MIN_MATCH_SCORE_BY_MODEL: dict[str, float] = {
    "text-embedding-3-small": 0.4,
}

MIN_MATCH_SCORE = MIN_MATCH_SCORE_BY_MODEL.get(EMBEDDING_MODEL, DEFAULT_MIN_MATCH_SCORE)

# 인덱스 파일 포맷 버전. 1 = 초기(플랫 dict, 메타 없음) / 2 = {meta, signatures}.
# 1도 계속 읽는다 — 포맷을 올렸다고 이미 빌드된 인덱스가 못 쓰게 되면 안 된다.
INDEX_FORMAT = 2

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


def reembed_index(index: dict, embed_fn) -> dict:
    """기존 인덱스의 **텍스트는 그대로 두고 벡터만** 새 임베더로 다시 만든다.

    임베딩 모델만 바뀐 경우를 위한 경로다. 그때 재료 텍스트(그래프의 FORMS_IN 서술 등)는
    하나도 안 바뀌었고 그 텍스트는 이미 인덱스에 저장돼 있으므로, Neo4j에 다시 붙을 이유가
    없다 — 모델을 바꾸는 사람이 그래프를 안 띄우는 경우가 많아 이 결합을 끊어 둔다.

    ⚠️ **그래프가 바뀐 경우엔 쓰면 안 된다**(문헌 추가·5_build 재실행). 그때는 텍스트 자체가
    달라졌으므로 build_signature_index로 그래프에서 다시 긁어와야 한다. 여기서는 그 사실을
    알 방법이 없다(텍스트만 보고는 최신인지 모른다) — 호출자가 구분해야 한다.
    """
    return {
        sig: {"text": entry["text"], "embedding": embed_fn(entry["text"])}
        for sig, entry in index.items()
    }


def save_index(index: dict, path: str | Path, model: str = EMBEDDING_MODEL) -> None:
    """인덱스를 **어떤 모델로 만들었는지와 함께** 저장한다(포맷 2).

    메타를 같이 적는 게 핵심이다 — 예전 포맷은 벡터만 저장해서, 나중에 모델이 바뀌어도
    이 파일이 낡았다는 걸 아무도 알 수 없었다.
    """
    dim = len(next(iter(index.values()))["embedding"]) if index else 0
    payload = {
        "meta": {"format": INDEX_FORMAT, "model": model, "dim": dim, "count": len(index)},
        "signatures": index,
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def load_index(path: str | Path) -> dict:
    """시그니처 dict를 돌려준다. 포맷 1(플랫)·2(메타 포함) 모두 읽는다."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "signatures" in raw and "meta" in raw:
        return raw["signatures"]
    return raw   # 포맷 1 — 파일 전체가 곧 시그니처 dict


def load_index_meta(path: str | Path) -> dict:
    """인덱스 메타. 포맷 1(메타 없음)이면 빈 dict — "모른다"와 "다르다"는 구분해야 한다."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("meta"), dict):
        return raw["meta"]
    return {}


def index_dim(index: dict) -> int:
    """인덱스 벡터 차원(비어 있으면 0)."""
    for entry in index.values():
        embedding = entry.get("embedding") or []
        return len(embedding)
    return 0


def _cosine(a: list[float], b: list[float]) -> float:
    """코사인 유사도. **차원이 다르면 0.0** — zip으로 잘라 계산하지 않는다.

    예전엔 zip(a, b)가 짧은 쪽에 맞춰 조용히 잘랐다. 그래서 1536차원 인덱스에
    3072차원 질의를 넣어도 예외 없이 "앞 1536차원만의 코사인"이라는 무의미한 점수가
    나왔다. 여기서 0.0을 내면 하한(MIN_MATCH_SCORE)에 걸려 매칭이 안 되고, 호출부는
    이미 정의된 "진입 시그니처 없음" 경로로 안전하게 흘러간다.
    """
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class SemanticSignatureIndex:
    """빌드된 인덱스 + 임베더로 자연어 질의를 top-k 시그니처로 매칭한다.

    임베딩 모델이 바뀌었는데 인덱스를 다시 안 만든 경우를 **런타임에서도** 잡는다. 모델 교체는
    다른 사람이 할 수 있고 인덱스 재빌드는 잊히기 쉬우므로, 설정 검사(deps)만 믿지 않고
    실제 질의 벡터의 차원으로 한 번 더 확인한다. 어긋나면 예외를 던지지 않고 **매칭을 끄고**
    빈 결과를 낸다 — 배치 한복판에서 죽는 것보다, 이미 정의된 "진입 시그니처 없음" 경로로
    흘러가는 편이 안전하다(파일이 아예 없을 때와 같은 동작).
    """

    def __init__(self, index: dict, embed_fn, min_score: float = MIN_MATCH_SCORE) -> None:
        self._index = index
        self._embed = embed_fn
        self._min_score = min_score
        self._index_dim = index_dim(index)
        self._disabled_reason: str | None = None   # 차원 불일치 감지 시 채워진다(1회 경고용)

    @property
    def disabled_reason(self) -> str | None:
        """차원 불일치로 매칭이 꺼졌다면 그 사유. 정상이면 None."""
        return self._disabled_reason

    def _check_dim(self, query_vec: list[float]) -> bool:
        """질의 벡터가 인덱스와 같은 차원인지. 다르면 매칭을 영구히 끄고 1회만 경고한다."""
        if self._index_dim and len(query_vec) != self._index_dim:
            if self._disabled_reason is None:
                self._disabled_reason = (
                    f"임베딩 차원 불일치(인덱스 {self._index_dim} ≠ 질의 {len(query_vec)}) — "
                    f"모델이 바뀌었는데 인덱스가 낡았습니다. "
                    f"python kg_rca/7_build_signature_index.py 로 재빌드하세요. "
                    f"그때까지 의미 진입은 꺼진 채로 동작합니다(enum/패턴 진입만)."
                )
                print(f"[semantic_entry] {self._disabled_reason}")
            return False
        return True

    def match(self, query_text: str, k: int = 3, allowed: set | None = None) -> list[tuple[str, float]]:
        """(sig_id, cosine) 상위 k개 — 단 min_score 미달은 제외라 k개 미만·빈 리스트일 수 있다.
        결정적(같은 임베딩이면 같은 순서).

        allowed가 주어지면 그 시그니처 집합으로 매칭 범위를 제한한다(기지 패턴일 때 —
        CNN 패턴의 HAS_SIGNATURE 시그니처로 좁힌 범위). None이면 인덱스 전체(미지 패턴).

        임베딩 호출이 실패하거나(네트워크·쿼터) 차원이 어긋나면 빈 리스트를 낸다 — 어느
        경우도 예외를 밖으로 내보내지 않는다.
        """
        if self._disabled_reason is not None:
            return []
        try:
            query_vec = self._embed(query_text)
        except Exception as exc:   # noqa: BLE001 — 임베딩 API 실패로 배치를 죽이지 않는다
            print(f"[semantic_entry] 임베딩 호출 실패({exc!r}) — 이번 질의는 의미 진입 생략")
            return []
        if not self._check_dim(query_vec):
            return []
        scored = [
            (sig, score)
            for sig, entry in self._index.items()
            if (allowed is None or sig in allowed)
            and (score := _cosine(query_vec, entry["embedding"])) >= self._min_score
        ]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))  # 유사도 내림차순, 동점은 id로 결정적
        return scored[:k]
