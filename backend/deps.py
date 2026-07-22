"""앱 전역 싱글턴 (KGClient · MCPClient).

MCPClient는 모듈 레벨 싱글턴 유지가 필수다(CLAUDE.md — get_tools()가 호출마다 stdio
서브프로세스를 새로 만드는 문제를 session 재사용으로 우회한 패턴. 깨지 말 것).
지연 생성으로 두어 fab.db·환경변수가 없어도 import 자체는 성공하게 한다(테스트 편의).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from .graph_client import KGClient, LiveKGClient
from .mcp_client import MCPClient

load_dotenv()

_kg_client: KGClient | LiveKGClient | None = None
_mcp_client: MCPClient | None = None
_graph = None


def _neo4j_graph():
    """Neo4j 라이브 핸들(지연 싱글턴). KG_LIVE=1일 때만 생성된다."""
    global _graph
    if _graph is None:
        from langchain_neo4j import Neo4jGraph
        _graph = Neo4jGraph(
            url=os.environ["NEO4J_URI"],
            username=os.environ["NEO4J_USERNAME"],
            password=os.environ["NEO4J_PASSWORD"],
            database=os.getenv("NEO4J_DATABASE", "neo4j"),
        )
    return _graph


def kg_client() -> KGClient | LiveKGClient:
    """KG 조회 클라이언트. KG_LIVE=1이면 Neo4j 라이브 순회(LiveKGClient),
    아니면 hypotheses.json 파일 조회(KGClient, 기본값). 둘 다 get_candidates 인터페이스 동일.
    """
    global _kg_client
    if _kg_client is None:
        if os.getenv("KG_LIVE", "").lower() in ("1", "true", "yes"):
            _kg_client = LiveKGClient(graph=_neo4j_graph())
        else:
            _kg_client = KGClient(hypotheses_path=Path(os.environ["KG_HYPOTHESES_PATH"]))
    return _kg_client


def mcp_client() -> MCPClient:
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client
