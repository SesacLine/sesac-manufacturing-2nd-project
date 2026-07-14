import os
import sys
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_neo4j import Neo4jGraph, GraphCypherQAChain
from langchain_core.prompts import PromptTemplate

# Windows 콘솔(cp949)에서 em-dash 등 유니코드 출력 시 크래시 방지
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")

graph = Neo4jGraph(
    url=NEO4J_URI,
    username=NEO4J_USERNAME,
    password=NEO4J_PASSWORD,
    database=NEO4J_DATABASE,
)
graph.refresh_schema()

llm = ChatOpenAI(
    model=OPENAI_MODEL,
    temperature=0,
)


# ============================================================
# Cypher 생성 프롬프트
# ------------------------------------------------------------
# RCA 그래프 구조(schema.md)를 LLM에게 알려줘서 Cypher를 더 잘 만들게 한다.
#   (:DefectPattern)-[:ARISES_IN]->(:ProcessStep)
#   (:FailureMode)-[:OCCURS_IN]->(:ProcessStep)
#   (:FailureMode)-[:CAUSED_BY]->(:Cause)
#   (:Cause)-[:INVOLVES_PARAMETER]->(:Parameter)
#   (:Equipment)-[:PART_OF]->(:ProcessStep)
#   (:Chunk)-[:MENTIONS]->(:FailureMode|:Cause|:Equipment)
#
# ProcessStep이 문서 A(패턴→공정)와 문서 B(고장→원인→변수)를 잇는 join 노드다.
# ============================================================

CYPHER_GENERATION_TEMPLATE = """
당신은 Neo4j Cypher 전문가입니다.
반도체 웨이퍼 불량 원인분석(RCA) 지식그래프에 대한 질문에 답하기 위한 Cypher만 생성하세요.

그래프 핵심 구조:
- (:DefectPattern)-[:ARISES_IN]->(:ProcessStep)      이 불량 패턴이 어느 공정을 의심케 하는가
- (:FailureMode)-[:OCCURS_IN]->(:ProcessStep)        이 고장 모드가 어느 공정에서 일어나는가
- (:FailureMode)-[:CAUSED_BY]->(:Cause)              고장 모드의 원인
- (:Cause)-[:INVOLVES_PARAMETER]->(:Parameter)       원인에 관여하는 공정 변수 (direction: high/low)
- (:Equipment)-[:PART_OF]->(:ProcessStep)            장비가 속한 공정군
- (:Chunk)-[:MENTIONS]->(:FailureMode|:Cause|:Equipment)   근거 문헌 조각

ProcessStep은 join 노드입니다. 불량 패턴에서 원인까지 가려면 반드시 ProcessStep을 거칩니다.

노드 식별 규칙 (매우 중요):
- 모든 노드의 유일 키는 `id` 입니다. 이름으로 찾을 때는 `id` 또는 `name`을 쓰세요.
- DefectPattern.id에는 불량 패턴 3종만 옵니다: 'Center', 'Scratch', 'Edge-Ring'.
  이 셋이 아닌 이름(예: post_etch_residue, high_etch_rate)을 DefectPattern으로 매칭하지 마세요.
- ProcessStep.id에는 공정 6종만 옵니다: 'LITHO', 'ETCH', 'DEPO', 'CMP', 'CLEAN', 'EDS'.
- 고장 모드(잔류물, 부식, 스크래치 등 증상) 이름은 FailureMode.id / FailureMode.name 으로 매칭하세요.
- 원인 이름(high_etch_rate 등)은 Cause.id / Cause.name 으로 매칭하세요.
- 공정 변수 이름(rf_power, etch_rate 등)은 Parameter.id 로 매칭하세요.

규칙:
- 읽기 전용 쿼리만 생성하세요. CREATE, MERGE, DELETE, SET, REMOVE 금지.
- "근본 원인/root cause"을 물으면 FailureMode-[:CAUSED_BY]->Cause 를 따라가세요.
  CAUSED_BY는 FailureMode에서 Cause로 한 단계입니다. 가변 길이(*1..2)를 쓰지 마세요.
- "어떻게 검증/확인"을 물으면 Cause-[:INVOLVES_PARAMETER]->Parameter 를 반환하세요.
  Parameter.id가 fab 계측 데이터의 param 이름이고, 그것이 검증 종착점입니다.
- 반환 결과는 최대 10개로 제한하세요.
- 백틱(`)을 사용하지 마세요.
- Cypher 코드만 출력하세요. 설명하지 마세요.

예시:
# 질문: Edge-Ring 불량의 가능한 원인은?
MATCH (p:DefectPattern {{id: 'Edge-Ring'}})-[:ARISES_IN]->(s:ProcessStep)
MATCH (fm:FailureMode)-[:OCCURS_IN]->(s)
MATCH (fm)-[:CAUSED_BY]->(c:Cause)
RETURN s.id AS step, fm.name AS failure_mode, c.name AS cause LIMIT 10

# 질문: post_etch_residue는 어떤 변수로 검증해?
MATCH (fm:FailureMode {{id: 'post_etch_residue'}})-[:CAUSED_BY]->(c:Cause)
MATCH (c)-[r:INVOLVES_PARAMETER]->(p:Parameter)
RETURN c.name AS cause, p.id AS param, r.direction AS direction LIMIT 10

스키마:
{schema}

질문:
{question}
"""

cypher_prompt = PromptTemplate(
    input_variables=["schema", "question"],
    template=CYPHER_GENERATION_TEMPLATE,
)

chain = GraphCypherQAChain.from_llm(
    llm=llm,
    graph=graph,
    cypher_prompt=cypher_prompt,
    verbose=True,
    validate_cypher=True,
    allow_dangerous_requests=True,
    top_k=10,
)


questions = [
    "Edge-Ring 불량은 어느 공정을 의심해야 해?",
    "Edge-Ring 불량의 가능한 근본 원인(root cause)은 뭐야?",
    "ETCH 공정에서 일어나는 고장 모드에는 뭐가 있어?",
    "Edge-Ring 불량 가설을 검증하려면 어떤 공정 변수를 봐야 해?",
    "Scratch 불량과 관련된 공정 변수는 뭐야?",
]

for question in questions:
    print("=" * 80)
    print("질문:", question)

    try:
        result = chain.invoke({"query": question})
        print("\n답변:")
        print(result["result"])
    except Exception as e:
        print("\n에러 발생:")
        print(type(e).__name__)
        print(e)
