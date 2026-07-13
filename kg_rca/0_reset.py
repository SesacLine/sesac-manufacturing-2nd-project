"""
Neo4j 데이터베이스 전체 초기화.

이 DB는 이제 RCA 그래프 전용이다. 노드/관계/제약/인덱스를 전부 지운다.

스키마를 바꾼 뒤에는 반드시 먼저 돌려야 한다.
Neo4j의 UNIQUE 제약은 null 값을 무시하므로, `id`가 없는 옛 앵커 노드가 남아 있으면
`MERGE (p:DefectPattern {id: 'Edge-Ring'})` 가 기존 노드를 찾지 못하고 중복 노드를 새로 만든다.
"""

import os
import sys

from dotenv import load_dotenv
from langchain_neo4j import Neo4jGraph

# Windows 콘솔(cp949)에서 em-dash 등 유니코드 출력 시 크래시 방지
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE")


def get_graph() -> Neo4jGraph:
    return Neo4jGraph(
        url=NEO4J_URI,
        username=NEO4J_USERNAME,
        password=NEO4J_PASSWORD,
        database=NEO4J_DATABASE,
    )


def summarize(graph: Neo4jGraph) -> tuple[int, int]:
    nodes = graph.query("MATCH (n) RETURN count(n) AS c")[0]["c"]
    rels = graph.query("MATCH ()-[r]->() RETURN count(r) AS c")[0]["c"]
    return nodes, rels


def print_label_counts(graph: Neo4jGraph) -> None:
    rows = graph.query(
        """
        MATCH (n)
        UNWIND labels(n) AS label
        RETURN label, count(*) AS c
        ORDER BY c DESC
        """
    )
    for row in rows:
        print(f"  {row['label']}: {row['c']}")


def delete_all_nodes(graph: Neo4jGraph) -> None:
    # 한 트랜잭션에 다 담으면 큰 그래프에서 메모리가 터진다. 배치로 지운다.
    while True:
        rows = graph.query(
            """
            MATCH (n)
            WITH n LIMIT 10000
            DETACH DELETE n
            RETURN count(*) AS deleted
            """
        )
        deleted = rows[0]["deleted"] if rows else 0
        if deleted == 0:
            break
        print(f"  ...{deleted}개 삭제")


def drop_constraints_and_indexes(graph: Neo4jGraph) -> None:
    for row in graph.query("SHOW CONSTRAINTS YIELD name RETURN name"):
        graph.query(f"DROP CONSTRAINT {row['name']} IF EXISTS")

    # 제약이 만든 인덱스는 위에서 함께 사라진다. 남은 것만 지운다.
    # LOOKUP 인덱스는 DB 내장이라 지우지 않는다.
    for row in graph.query("SHOW INDEXES YIELD name, type RETURN name, type"):
        if row["type"] == "LOOKUP":
            continue
        graph.query(f"DROP INDEX {row['name']} IF EXISTS")


def main() -> None:
    graph = get_graph()

    nodes, rels = summarize(graph)
    if nodes == 0 and rels == 0:
        print("DB가 이미 비어 있습니다.")
        return

    print(f"현재 DB: 노드 {nodes}개, 관계 {rels}개")
    print_label_counts(graph)

    answer = input(f"\nDB '{NEO4J_DATABASE}' 를 통째로 비웁니다. 계속할까요? [y/N] ").strip().lower()
    if answer != "y":
        print("취소했습니다.")
        return

    print("\n노드 삭제 중...")
    delete_all_nodes(graph)

    print("제약/인덱스 삭제 중...")
    drop_constraints_and_indexes(graph)

    nodes, rels = summarize(graph)
    print(f"\n초기화 완료. 노드 {nodes}개, 관계 {rels}개")


if __name__ == "__main__":
    main()
