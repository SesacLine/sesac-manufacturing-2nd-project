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
from .graph_client.semantic_entry import (
    EMBEDDING_MODEL,
    MIN_MATCH_SCORE,
    SemanticSignatureIndex,
    load_index,
)
from .mcp_client import MCPClient

load_dotenv()

_kg_client: KGClient | LiveKGClient | None = None
_mcp_client: MCPClient | None = None
_graph = None
_semantic: SemanticSignatureIndex | None = None
_semantic_loaded = False   # 결과가 None이어도 유효하므로, "시도했는가"를 따로 기억한다


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


def _signature_index_path() -> Path:
    """의미 진입 인덱스 파일 경로. 기본값은 kg_rca 산출물 위치(hypotheses.json 옆)."""
    env = os.getenv("KG_SIGNATURE_INDEX_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / "kg_rca" / "outputs" / "signature_index.json"


def _semantic_index() -> SemanticSignatureIndex | None:
    """의미 진입 인덱스(지연 싱글턴). KG_LIVE일 때 LiveKGClient에 주입된다.

    실패해도 서버 기동을 막지 않는다 — None이면 LiveKGClient가 의미 진입 없이
    (enum signature/패턴 진입만으로) 동작한다. KG_SEMANTIC=0으로 명시적으로 끌 수 있다.
    """
    global _semantic, _semantic_loaded
    if _semantic_loaded:
        return _semantic
    _semantic_loaded = True

    if os.getenv("KG_SEMANTIC", "1").lower() in ("0", "false", "no"):
        return None

    path = _signature_index_path()
    if not path.exists():
        print(f"[deps] signature index 없음({path}) — 의미 진입 비활성. "
              f"생성: semantic_entry.build_signature_index (그래프 재빌드 후 갱신 필요)")
        return None
    try:
        # 인덱스를 만든 모델과 반드시 동일해야 한다 (semantic_entry.EMBEDDING_MODEL).
        from langchain_openai import OpenAIEmbeddings
        embedder = OpenAIEmbeddings(model=EMBEDDING_MODEL)
        min_score = float(os.getenv("KG_SEMANTIC_MIN_SCORE", MIN_MATCH_SCORE))
        _semantic = SemanticSignatureIndex(load_index(path), embedder.embed_query, min_score=min_score)
    except Exception as exc:   # noqa: BLE001 — 키 미설정 등 어떤 초기화 실패도 기동은 살린다
        print(f"[deps] 의미 진입 초기화 실패({exc!r}) — enum/패턴 진입만 사용")
        _semantic = None
    return _semantic


def kg_client() -> KGClient | LiveKGClient:
    """KG 조회 클라이언트. KG_LIVE=1이면 Neo4j 라이브 순회(LiveKGClient) + 의미 진입
    (signature index가 있으면 자동, KG_SEMANTIC=0으로 끔), 아니면 hypotheses.json
    파일 조회(KGClient, 기본값). 둘 다 get_candidates 인터페이스 동일.
    """
    global _kg_client
    if _kg_client is None:
        if os.getenv("KG_LIVE", "").lower() in ("1", "true", "yes"):
            _kg_client = LiveKGClient(graph=_neo4j_graph(), semantic_index=_semantic_index())
        else:
            _kg_client = KGClient(hypotheses_path=Path(os.environ["KG_HYPOTHESES_PATH"]))
    return _kg_client


def mcp_client() -> MCPClient:
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client


_response_llm = None

# ⑦ description 번역 프롬프트 — VLM 영어 서술 → 한국어. 충실 번역만(추가·삭제·해석 금지).
# faithfulness firewall: 이건 "생성"이 아니라 "옮기기"라 evidence 밖 사실이 새로 생기지 않는다.
_TRANSLATE_PROMPT = (
    "다음은 반도체 웨이퍼 결함 형상을 서술한 영어 문장이다. 사실을 더하거나 빼지 말고, "
    "해석·원인 추정 없이 자연스러운 한국어로만 번역하라. 번역문만 출력하라.\n\n{text}"
)


def response_translator():
    """⑦ 응답노드에 주입할 영어→한국어 번역 콜러블(str→str). RESPONSE_LLM=1일 때만 실체,
    아니면 None(응답노드가 원문 영어를 그대로 운반 — 결정적, LLM 비용 0).

    ChatOpenAI(temperature=0)로 재현성 확보(hypothesis._make_model과 같은 관례).
    """
    if os.getenv("RESPONSE_LLM", "").lower() not in ("1", "true", "yes"):
        return None
    global _response_llm
    if _response_llm is None:
        from langchain_openai import ChatOpenAI
        _response_llm = ChatOpenAI(model=os.environ["OPENAI_MODEL"], temperature=0)
    llm = _response_llm

    def translate(english: str) -> str:
        return llm.invoke(_TRANSLATE_PROMPT.format(text=english)).content.strip()

    return translate
