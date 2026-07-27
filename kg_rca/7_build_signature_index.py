"""7. 의미 진입용 시그니처 임베딩 인덱스 빌드 (backend 라이브 조회의 선택 산출물).

그래프(5_build)가 만든 SpatialSignature 각각의 서술 텍스트(FORMS_IN description+quotes +
언급 청크)를 임베딩해 outputs/signature_index.json에 저장한다. backend의 LiveKGClient가
KG_LIVE + KG_SEMANTIC일 때 이 파일을 읽어 VLM 자연어를 시그니처에 매칭한다.

파이프라인상 위치: 0_reset ~ 6_ask 다음. **그래프를 재빌드하면(문헌 추가·재추출) 이 인덱스도
낡으므로 반드시 다시 돌린다** — 인덱스는 그래프의 파생 스냅샷이다. 안 돌리면 새 시그니처가
매칭 대상에서 빠지거나 옛 서술로 매칭되어 조용히 틀린다.

빌드 로직(SIGNATURE_TEXT_QUERY·임베딩 모델)은 backend와 공유한다 — 여기서 재구현하면
런타임 질의와 벡터 공간이 어긋날 수 있어 backend.graph_client.semantic_entry를 그대로 import한다.

실행:
    python 7_build_signature_index.py
필요: Neo4j 기동 + 그래프 적재 완료, OPENAI_API_KEY (kg_rca/.env).
"""

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
    load_index_meta,
    save_index,
)

OUTPUT_PATH = BASE_DIR / "outputs" / "signature_index.json"


def main() -> None:
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

    print(f"임베딩 모델: {EMBEDDING_MODEL}  (바꾸려면 .env의 KG_EMBEDDING_MODEL)")

    # 모델이 바뀌었는지 먼저 알려준다 — 지금 덮어쓰는 인덱스가 무엇에서 무엇으로 가는지
    # 보이면, 재빌드가 필요한 이유와 하한 재측정 필요성이 같이 인지된다.
    if OUTPUT_PATH.exists():
        try:
            prev = load_index_meta(OUTPUT_PATH).get("model")
            if prev and prev != EMBEDDING_MODEL:
                print(f"  ↳ 모델 교체 감지: '{prev}' → '{EMBEDDING_MODEL}' (인덱스를 새로 만듭니다)")
            elif not prev:
                print("  ↳ 기존 인덱스에 모델 정보 없음(구 포맷) — 이번 빌드부터 기록됩니다")
        except Exception:  # noqa: BLE001 — 안내용이라 실패해도 빌드는 계속
            pass

    embedder = OpenAIEmbeddings(model=EMBEDDING_MODEL)

    index = build_signature_index(graph, embedder.embed_query)
    save_index(index, OUTPUT_PATH, model=EMBEDDING_MODEL)

    dim = len(next(iter(index.values()))["embedding"]) if index else 0
    print(f"\n인덱스 {len(index)}개 시그니처 저장 완료 (모델 {EMBEDDING_MODEL}, 차원 {dim}): {OUTPUT_PATH}")
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
