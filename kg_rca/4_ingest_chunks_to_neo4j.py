import os
import sys
import json
from pathlib import Path

from dotenv import load_dotenv
from langchain_neo4j import Neo4jGraph

# Windows 콘솔(cp949)에서 em-dash 등 유니코드 출력 시 크래시 방지
sys.stdout.reconfigure(encoding="utf-8")


# =========================
# 1. 환경 변수 / 경로 설정
# =========================

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

CHUNKS_PATH = BASE_DIR / "outputs" / "chunks.jsonl"
SEEDS_DIR = BASE_DIR / "data" / "seeds"

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE")


# =========================
# 2. Neo4j 연결
# =========================

def get_graph() -> Neo4jGraph:
    return Neo4jGraph(
        url=NEO4J_URI,
        username=NEO4J_USERNAME,
        password=NEO4J_PASSWORD,
        database=NEO4J_DATABASE,
    )


# =========================
# 3. 제약 조건 생성
# -------------------------
# 모든 노드는 라벨별로 UNIQUE한 `id`를 유일 키로 갖는다 (schema.md §Node Types).
# 시드 앵커 3종 + 문헌에서 뽑는 3종(5번에서 생성) + Document/Chunk.
# MERGE가 중복 노드를 만들지 않도록 하는 안전장치.
# =========================

def create_constraints(graph: Neo4jGraph) -> None:
    statements = [
        "CREATE CONSTRAINT defect_pattern_id IF NOT EXISTS FOR (n:DefectPattern) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT process_step_id   IF NOT EXISTS FOR (n:ProcessStep)   REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT signature_id      IF NOT EXISTS FOR (n:SpatialSignature) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT failure_mode_id   IF NOT EXISTS FOR (n:FailureMode)   REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT cause_id          IF NOT EXISTS FOR (n:Cause)         REQUIRE n.id IS UNIQUE",
        # evidence 3종 (공통 슈퍼라벨 :Evidence 를 함께 갖는다)
        "CREATE CONSTRAINT parameter_id      IF NOT EXISTS FOR (n:Parameter)     REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT maintenance_id    IF NOT EXISTS FOR (n:Maintenance)   REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT recipe_id         IF NOT EXISTS FOR (n:Recipe)        REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT chunk_id_unique    IF NOT EXISTS FOR (c:Chunk)    REQUIRE c.id IS UNIQUE",
        "CREATE CONSTRAINT document_id_unique IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
    ]
    for stmt in statements:
        graph.query(stmt)


# =========================
# 4. 시드 노드 적재 (앵커)
# -------------------------
# DefectPattern / ProcessStep / Parameter 는 문헌에서 뽑는 게 아니라
# 미리 정해진 고정 목록(enum)이다. data/seeds/*.json 을 읽어 그대로 MERGE 한다.
# 문헌이 이 id들을 언급하면 새로 만들지 않고 여기 연결한다(= 앵커).
#
# ProcessStep.id  ↔ fab의 lot_history.step
# Parameter.id    ↔ fab의 telemetry.param   (가설 검증 SQL의 join key)
# =========================

def load_seed(file_name: str) -> list[dict]:
    path = SEEDS_DIR / file_name
    if not path.exists():
        raise FileNotFoundError(f"시드 파일을 찾을 수 없습니다: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["nodes"]


def seed_defect_patterns(graph: Neo4jGraph) -> None:
    nodes = load_seed("defect_patterns.json")
    graph.query(
        """
        UNWIND $nodes AS n
        MERGE (p:DefectPattern {id: n.id})
        SET p.name = n.name,
            p.aliases = n.aliases,
            p.spatial_keywords = n.spatial_keywords,
            p.expected_zone = n.expected_zone,
            p.expected_shape = n.expected_shape
        """,
        params={"nodes": nodes},
    )


def seed_process_steps(graph: Neo4jGraph) -> None:
    nodes = load_seed("process_steps.json")
    graph.query(
        """
        UNWIND $nodes AS n
        MERGE (s:ProcessStep {id: n.id})
        SET s.name = n.name,
            s.aliases = n.aliases
        """,
        params={"nodes": nodes},
    )


def seed_parameters(graph: Neo4jGraph) -> None:
    """
    Parameter만 evidence 중 유일하게 고정 vocabulary다.
    id가 fab telemetry.param 과 문자열이 일치해야 검증 SQL이 붙기 때문.
    Maintenance/Recipe 는 문서에서 추출되므로 시드하지 않는다(5번이 만든다).
    """
    nodes = load_seed("parameters.json")
    graph.query(
        """
        UNWIND $nodes AS n
        MERGE (p:Parameter {id: n.id})
        SET p:Evidence,
            p.name = n.name,
            p.steps = n.steps,
            p.aliases = n.aliases,
            p.fab_table = 'telemetry'
        """,
        params={"nodes": nodes},
    )


def seed_all_anchors(graph: Neo4jGraph) -> None:
    """
    결정적 시딩은 세 앵커뿐: DefectPattern / ProcessStep / Parameter.
    SpatialSignature는 시딩하지 않는다 — 5번이 문서에서 추출해 만든다
    (어휘는 코드의 Shape/Zone enum으로 닫혀 있어 id 파편화는 불가능).
    """
    seed_defect_patterns(graph)
    seed_process_steps(graph)
    seed_parameters(graph)


# =========================
# 5. chunks.jsonl 로드
# =========================

def load_chunks(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"chunks.jsonl 파일을 찾을 수 없습니다: {path}")

    chunks = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            metadata = row.get("metadata", {})
            chunks.append({
                "chunk_id": row["chunk_id"],
                "chunk_index": row["chunk_index"],
                "text": row["page_content"],
                "doc_id": metadata.get("doc_id"),
                "title": metadata.get("title"),
                "source": metadata.get("source"),
                "start_index": metadata.get("start_index"),
                "char_count": metadata.get("char_count"),
            })
    return chunks


# =========================
# 6. Document / Chunk 저장
# -------------------------
# (:Document)-[:HAS_CHUNK]->(:Chunk)
# =========================

def save_chunks(graph: Neo4jGraph, chunks: list[dict]) -> None:
    graph.query(
        """
        UNWIND $chunks AS row

        MERGE (d:Document {id: row.doc_id})
        SET d.title = row.title,
            d.source = row.source

        MERGE (c:Chunk {id: row.chunk_id})
        SET c.text = row.text,
            c.chunk_index = row.chunk_index,
            c.doc_id = row.doc_id,
            c.source = row.source,
            c.start_index = row.start_index,
            c.char_count = row.char_count

        MERGE (d)-[:HAS_CHUNK]->(c)
        """,
        params={"chunks": chunks},
    )


# =========================
# 7. 청크 순서 관계 (문서별)
# -------------------------
# 같은 문서 안에서만 chunk_index 순서대로 NEXT_CHUNK 를 잇는다.
# =========================

def create_next_chunk_relationships(graph: Neo4jGraph) -> None:
    graph.query(
        """
        MATCH (d:Document)-[:HAS_CHUNK]->(c:Chunk)
        WHERE c.chunk_index IS NOT NULL
        WITH d, c
        ORDER BY c.chunk_index ASC
        WITH d, collect(c) AS chunks
        WHERE size(chunks) > 1

        UNWIND range(0, size(chunks) - 2) AS i
        WITH chunks[i] AS cur, chunks[i + 1] AS nxt
        MERGE (cur)-[:NEXT_CHUNK]->(nxt)
        """
    )


# =========================
# 8. 확인용 출력
# =========================

def print_summary(graph: Neo4jGraph) -> None:
    def count(label: str) -> int:
        return graph.query(f"MATCH (n:{label}) RETURN count(n) AS c")[0]["c"]

    print("DefectPattern:", count("DefectPattern"))
    print("ProcessStep:", count("ProcessStep"))
    print("Parameter:", count("Parameter"))
    print("Document:", count("Document"))
    print("Chunk:", count("Chunk"))


# =========================
# 9. 실행
# =========================

def main() -> None:
    graph = get_graph()

    print("제약조건 생성...")
    create_constraints(graph)

    print("시드 앵커 적재...")
    seed_all_anchors(graph)

    chunks = load_chunks(CHUNKS_PATH)
    print("불러온 청크 수:", len(chunks))

    save_chunks(graph, chunks)
    create_next_chunk_relationships(graph)

    graph.refresh_schema()

    print("\n저장 완료")
    print_summary(graph)

    print("\nGraph schema:")
    print(graph.schema)


if __name__ == "__main__":
    main()
