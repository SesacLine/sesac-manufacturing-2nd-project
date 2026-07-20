"""앱 전역 싱글턴 (KGClient · MCPClient).

MCPClient는 모듈 레벨 싱글턴 유지가 필수다(CLAUDE.md — get_tools()가 호출마다 stdio
서브프로세스를 새로 만드는 문제를 session 재사용으로 우회한 패턴. 깨지 말 것).
지연 생성으로 두어 fab.db·환경변수가 없어도 import 자체는 성공하게 한다(테스트 편의).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from .graph_client import KGClient
from .mcp_client import MCPClient

load_dotenv()

_kg_client: KGClient | None = None
_mcp_client: MCPClient | None = None


def kg_client() -> KGClient:
    global _kg_client
    if _kg_client is None:
        _kg_client = KGClient(hypotheses_path=Path(os.environ["KG_HYPOTHESES_PATH"]))
    return _kg_client


def mcp_client() -> MCPClient:
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client
