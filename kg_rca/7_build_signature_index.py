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
    build_signature_index,
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

    print(f"임베딩 모델: {EMBEDDING_MODEL}")
    embedder = OpenAIEmbeddings(model=EMBEDDING_MODEL)

    index = build_signature_index(graph, embedder.embed_query)
    save_index(index, OUTPUT_PATH)

    dim = len(next(iter(index.values()))["embedding"]) if index else 0
    print(f"\n인덱스 {len(index)}개 시그니처 저장 완료 (차원 {dim}): {OUTPUT_PATH}")
    for sig in sorted(index):
        print(f"  - {sig}")


if __name__ == "__main__":
    main()
