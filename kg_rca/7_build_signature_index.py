"""7. 의미 진입용 시그니처 임베딩 인덱스 빌드 (backend 라이브 조회의 선택 산출물).

그래프(5_build)가 만든 SpatialSignature 각각의 서술 텍스트(FORMS_IN description+quotes +
언급 청크)를 임베딩해 outputs/signature_index.json에 저장한다. backend의 LiveKGClient가
KG_LIVE + KG_SEMANTIC일 때 이 파일을 읽어 VLM 자연어를 시그니처에 매칭한다.

파이프라인상 위치: 0_reset ~ 6_ask 다음. **그래프를 재빌드하면(문헌 추가·재추출) 이 인덱스도
낡으므로 반드시 다시 돌린다** — 인덱스는 그래프의 파생 스냅샷이다. 안 돌리면 새 시그니처가
매칭 대상에서 빠지거나 옛 서술로 매칭되어 조용히 틀린다.

빌드 로직(SIGNATURE_TEXT_QUERY·임베딩 모델)은 backend와 공유한다 — 여기서 재구현하면
런타임 질의와 벡터 공간이 어긋날 수 있어 backend.graph_client.semantic_entry를 그대로 import한다.

인덱스가 낡는 경로는 둘이고, **둘 다 이 스크립트로 고친다**:
  A. 그래프가 바뀜(문헌 추가·5_build 재실행)  → 재료 텍스트가 달라짐  → 기본 모드
  B. 임베딩 모델이 바뀜(KG_EMBEDDING_MODEL) → 벡터 좌표계가 달라짐 → --reembed 로 충분
B는 텍스트가 그대로라 그래프에 다시 붙을 필요가 없다(텍스트는 인덱스에 저장돼 있다).
모델을 바꾸는 사람이 Neo4j를 안 띄우는 경우가 많아 그 결합을 끊어 뒀다.

실행:
    python 7_build_signature_index.py              # A: 그래프에서 다시 긁어와 임베딩
    python 7_build_signature_index.py --reembed    # B: 저장된 텍스트로 벡터만 갱신(Neo4j 불필요)
필요: 기본 모드는 Neo4j 기동 + 그래프 적재 완료. 두 모드 모두 OPENAI_API_KEY (kg_rca/.env).
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Windows 콘솔(cp949)에서 유니코드 출력 크래시 방지
sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
# backend 패키지를 import하기 위해 저장소 루트를 경로에 추가 (kg_rca 안에서 실행되므로)
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()  # kg_rca/.env (NEO4J_*, OPENAI_API_KEY)

from langchain_neo4j import Neo4jGraph
from langchain_openai import OpenAIEmbeddings

from backend.graph_client.semantic_entry import (
    EMBEDDING_MODEL,
    MIN_MATCH_SCORE_BY_MODEL,
    build_signature_index,
    load_index,
    load_index_meta,
    reembed_index,
    save_index,
)

OUTPUT_PATH = BASE_DIR / "outputs" / "signature_index.json"


def _report_previous_model() -> None:
    """지금 덮어쓰는 인덱스가 무슨 모델로 만들어졌는지 알린다.

    '무엇에서 무엇으로' 가는지가 보이면 재빌드가 필요한 이유와 하한 재측정 필요성이
    같이 인지된다 — 이 스크립트를 왜 돌리는지 모르고 돌리는 경우를 줄이려는 것.
    """
    if not OUTPUT_PATH.exists():
        return
    try:
        prev = load_index_meta(OUTPUT_PATH).get("model")
    except Exception:  # noqa: BLE001 — 안내용이라 실패해도 빌드는 계속
        return
    if prev and prev != EMBEDDING_MODEL:
        print(f"  ↳ 모델 교체 감지: '{prev}' → '{EMBEDDING_MODEL}'")
    elif prev:
        print(f"  ↳ 기존 인덱스와 같은 모델('{prev}') — 그래프가 바뀐 경우에만 의미가 있습니다")
    else:
        print("  ↳ 기존 인덱스에 모델 정보 없음(구 포맷) — 이번 빌드부터 기록됩니다")


def _build_from_graph(embed_fn) -> dict:
    """A: 그래프에서 서술 텍스트를 다시 긁어와 임베딩(기본 모드)."""
    graph = Neo4jGraph(
        url=os.environ["NEO4J_URI"],
        username=os.environ["NEO4J_USERNAME"],
        password=os.environ["NEO4J_PASSWORD"],
        database=os.getenv("NEO4J_DATABASE", "neo4j"),
    )
    # 그래프에 시그니처가 있는지 먼저 확인 (5_build 미실행 시 빈 인덱스 방지)
    count = graph.query("MATCH (g:SpatialSignature) RETURN count(g) AS n")[0]["n"]
    if count == 0:
        print("SpatialSignature 노드가 0개입니다. 먼저 0_reset ~ 5_build를 실행하세요.")
        sys.exit(1)
    return build_signature_index(graph, embed_fn)


def _reembed_existing(embed_fn) -> dict:
    """B: 저장된 텍스트로 벡터만 갱신(Neo4j 불필요)."""
    if not OUTPUT_PATH.exists():
        print(
            f"--reembed는 기존 인덱스의 텍스트를 재사용하는 모드인데 파일이 없습니다: {OUTPUT_PATH}\n"
            f"처음 만드는 것이라면 Neo4j를 띄우고 옵션 없이 실행하세요."
        )
        sys.exit(1)
    index = load_index(OUTPUT_PATH)
    if not index:
        print(f"인덱스가 비어 있습니다({OUTPUT_PATH}) — 옵션 없이 그래프에서 다시 빌드하세요.")
        sys.exit(1)
    print(
        f"  ↳ 저장된 텍스트 {len(index)}건을 재사용합니다(그래프 접속 없음).\n"
        f"     ⚠️ 그래프를 바꿨다면(문헌 추가·5_build 재실행) 이 모드는 옛 텍스트를 그대로 쓰므로\n"
        f"        틀립니다. 그때는 옵션 없이 실행하세요."
    )
    return reembed_index(index, embed_fn)


def main() -> None:
    parser = argparse.ArgumentParser(description="의미 진입용 시그니처 임베딩 인덱스 빌드")
    parser.add_argument(
        "--reembed",
        action="store_true",
        help="기존 인덱스의 텍스트로 벡터만 다시 만든다(Neo4j 불필요). "
             "임베딩 모델만 바뀐 경우용 — 그래프가 바뀌었다면 쓰지 말 것.",
    )
    args = parser.parse_args()

    print(f"임베딩 모델: {EMBEDDING_MODEL}  (바꾸려면 .env의 KG_EMBEDDING_MODEL)")
    _report_previous_model()

    embedder = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    embed_fn = embedder.embed_query

    index = _reembed_existing(embed_fn) if args.reembed else _build_from_graph(embed_fn)
    save_index(index, OUTPUT_PATH, model=EMBEDDING_MODEL)

    dim = len(next(iter(index.values()))["embedding"]) if index else 0
    mode = "벡터만 갱신" if args.reembed else "그래프에서 재빌드"
    print(f"\n인덱스 {len(index)}개 시그니처 저장 완료 ({mode} · 모델 {EMBEDDING_MODEL} · 차원 {dim})")
    print(f"  → {OUTPUT_PATH}")
    for sig in sorted(index):
        print(f"  - {sig}")

    if EMBEDDING_MODEL not in MIN_MATCH_SCORE_BY_MODEL:
        print(
            f"\n⚠️ '{EMBEDDING_MODEL}'은 매칭 하한(MIN_MATCH_SCORE)이 실측되지 않은 모델입니다.\n"
            f"   코사인 점수 분포는 모델마다 달라서 기존 하한을 그대로 쓰면 오답이 문턱을 넘거나\n"
            f"   정답이 통째로 잘립니다. 정답/오답 점수를 재측정한 뒤\n"
            f"   semantic_entry.MIN_MATCH_SCORE_BY_MODEL에 등록하거나 KG_SEMANTIC_MIN_SCORE로 주세요."
        )


if __name__ == "__main__":
    main()
