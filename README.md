# SesacLine SemiRCA — 백엔드

FastAPI + LangGraph 기반 웨이퍼맵 결함 근본원인분석(RCA) ⓪~⑥ 파이프라인. `kg_rca`(GraphRAG,
문헌 기반 원인 후보)와 `secsgem-mcp`(MCP 9종 도구, fab.db 조회)를 연결한다. 둘 다
`SesacLine_SemiRCA/` 하위의 일반 폴더다(자체 `.git` 없음 — 이 repo를 git init하면 두 폴더
내용도 함께 커밋 히스토리에 포함된다).

## 상태: Walking Skeleton 완성 (2026-07-13, kg_rca v2.4 갱신 반영 재검증 2026-07-14)

⓪~⑥ 전체가 end-to-end로 동작한다. 단순화된 부분은 [단순화 목록](#단순화-목록) 참고. 배경·설계
논의·진행 로그는 `docs/skeleton_kickoff.md`.

kg_rca가 07-13에 schema v2.4로 갱신되면서 `hypotheses.json`의 `route`/`score.confidence` 필드가
빠지고 `scenario_hint`/`score.evidence_docs`/`evidence_chunks`로 바뀌었다. `backend/state.py`·
`backend/graph_client/kg_client.py`를 이 스키마에 맞춰 수정하고(07-14) 아래 실행 결과로 재검증했다
(상세 필드 매핑은 `kg_rca/KG_output_명세.md` 참고).

실행 결과(2026-03-04 배치, Center 그룹, kg_rca v2.4 기준):

```
저수율 로트 선별 → SVLOT-009 (수율 0.0)
그룹화          → Center-2026-03-04 그룹 1개
GraphRAG 후보   → 297건
Hypothesis 검증 → 297건 MCP 실호출로 확인
Critic 심사     → 163건 채택 / 134건 기각
```

채택된 가설 중 `DEPO-03`의 `chamber_pressure` 정상범위(`[2.0, 3.0]`) 이탈을 여전히 실제로 검출 —
fab.db에 주입된 Center 자동판정 시나리오와 일치. (kg_rca 갱신 전 수치는 244건 후보 → 136건 채택 /
108건 기각이었다 — kg_rca는 재생성마다 건수가 바뀌므로 이 숫자도 다음 갱신 때 다시 바뀔 수 있다.)

## 구조

```
backend/
  state.py             # RCAState — 파이프라인 전체가 공유하는 상태 타입
  main.py              # FastAPI 진입점. app_state.db(커서·배치결과) 생성 + /batch/run, /batch/results
  graph.py             # LangGraph StateGraph 조립 (⓪~⑥ 노드 연결) + _run_per_group(그룹 순회)
  nodes/
    lowyield.py         # ⓪ 저수율 로트 선별 — fab.db 직접 SQL, 임계값 0.8 하드코딩
    vlm.py               # ① VLM 웨이퍼맵 판독 — 실제 LLM 미연동, pattern="Center" 하드코딩
    grouper.py           # ② 패턴별 그룹화 — 로트별 다수결 대표패턴, 최소 로트수 게이트 없음
    graphrag.py          # ③ kg_rca 원인후보 조회 — group_id별 KGClient.get_candidates 호출
    hypothesis.py        # ④ Hypothesis 노드 — MCP 실호출, 검증단위 캐싱 포함
    critic.py            # ⑤ Critic 노드 — 시간정합/반대증거/faithfulness/KG메커니즘 4규칙
    response.py          # ⑥ 응답생성 — 실제 LLM 미연동, 결정적 템플릿 문자열
  mcp_client/           # secsgem-mcp 9종 도구 클라이언트 (지속 세션 재사용, 아래 참고)
  graph_client/         # kg_rca 결과(hypotheses.json) 조회 클라이언트
kg_rca/                 # GraphRAG
secsgem-mcp/            # MCP 서버 9종 도구 + fab.db
```

LLM을 실시간 호출하는 노드는 ①VLM과 ⑥응답생성 둘뿐이다(2026-07-09 결정, `semiconductor_proposal.md`
§2/§7). 지금은 이 둘도 하드코딩/템플릿으로 대체돼 있다(Walking Skeleton). 나머지(③~⑤)는 원래부터
결정적 함수다.

## 의존 관계

- `kg_rca/outputs/hypotheses.json`을 읽는다(③). Neo4j 없이도 이 파일만 있으면 동작한다.
- `secsgem-mcp` MCP 서버를 stdio로 호출한다(④⑤). 첫 도구 호출 시 자동 기동, 미리 띄워둘 필요 없음.
- `kg_rca`/`secsgem-mcp` 모두 자체 `.git`이 없다 — 이전 커밋 기록은 로컬에 없음.

## 설치

```bash
pip install uv
uv venv
uv sync                # 루트 pyproject.toml 하나로 backend/kg_rca/secsgem-mcp 의존성 전부 설치
.venv\Scripts\activate  # Windows. macOS/Linux: source .venv/bin/activate
cp .env_example .env    # 이미 ./kg_rca, ./secsgem-mcp 상대경로로 맞춰져 있음. OPENAI_API_KEY만 채우면 됨
```

`secsgem-mcp/datasets/fab.db`가 없으면 `secsgem-mcp/README.md`의 "데이터 준비" 절차를 먼저 돌린다.

## 실행

```bash
uvicorn backend.main:app --reload
```

- `POST /batch/run` — 커서를 하루 전진시키고 ⓪~⑥ 전체를 1회 실행, 결과를 `app_state.db`에 저장.
  최초 실행 시 커서는 `2026-03-04`로 시작한다(`backend/main.py`의 `_FIRST_CURSOR_DATE`, 하드코딩).
- `GET /batch/results` — 지금까지 쌓인 배치 결과를 그룹별로 반환.
- `GET /health` — 상태 확인용.

지금 구현된 건 위 3개 엔드포인트가 전부다. 프론트엔드가 실제로 붙을 때 필요한 목표 API 설계는
`docs/API_명세서_v0.1.md`(엔드포인트 7종, 요청/응답 예시, 에러코드, 데이터 모델) 참고 — 아직
미결정 사항(§4)이 남아있는 초안이고, 위 3개 엔드포인트와는 별개로 "이후에 이렇게 확장한다"는
설계 문서다.

지금까지의 end-to-end 검증은 `backend.graph.build_graph(...).ainvoke(initial_state)` 직접 호출로
했다. uvicorn 기동 후 HTTP 경로(특히 `app_state.db` 파일 생성 위치, 여러 요청에 걸친 MCP 세션
유지)는 별도 확인 필요.

### MCP 연결 (지속 세션)

`MultiServerMCPClient.get_tools()`는 호출마다 새 stdio 서브프로세스를 생성한다(라이브러리
docstring에 명시된 동작). Hypothesis 노드처럼 다회 호출하는 패턴에서는 이게 치명적으로 느려서
(실측: Center 244건 처리 시 타임아웃), `mcp_client/client.py`는 `client.session()`으로 연결을
한 번만 열고 `load_mcp_tools(session, ...)`로 그 세션을 재사용한다. `MCPClient`는 모듈 레벨
싱글턴으로 유지할 것 — `backend/main.py` 참고.

## 단순화 목록

코드에 `# 결정①/②/③` 주석 또는 "TODO(팀 결정 필요)"로 표시돼 있다.

| # | 위치 | 지금 선택 | 비고 |
|---|---|---|---|
| 1 | `hypothesis.py` — MCP 호출 단위 | 가설 단위 + `(step, evidence_label, evidence)` 캐싱 | 캐싱 없이는 244건에서 타임아웃 발생 확인. 캐싱은 응급 처치 수준, 검증 단위로 제대로 설계는 안 함 |
| 2 | `hypothesis.py` — `route="direct"` 의심 장비 | `step=None`을 그대로 `run_commonality_analysis`에 전달 | 전체 공정이 뭉뚱그려져 신호가 흐려짐 |
| 3 | `hypothesis.py` — `direction: null`인 `[자동]` 후보 | 방향 무시, 정상범위 이탈이면 `drift_detected=True` | 전체 패턴 합쳐 4건뿐이라 영향 작음 |
| 4 | `lowyield.py` — 저수율 임계값 | `LOW_YIELD_THRESHOLD = 0.8` 고정값 | 동적 임계값(mean - k*std 등) 미검토 |
| 5 | `grouper.py` — 최소 로트수 게이트 | `MIN_LOTS_PER_GROUP = 1` (게이트 없음) | 서브클러스터링 없음 |
| 6 | `vlm.py` | 실제 VLM 미연동, `pattern="Center"` 고정 | |
| 7 | `response.py` | 실제 LLM 미연동, 결정적 템플릿 문자열 | |
| 8 | `main.py` — 배치 시작 커서 날짜 | `2026-03-04` 하드코딩 | fab.db 데이터 범위 기준 시작일 정책 미정 |

## 알려진 버그 (발견·수정·재검증 완료)

1. `mcp_client.py`의 `_as_dict`가 MCP 응답 모양을 못 받음 — 구조화 출력이 없으면 MCP 표준 콘텐츠 블록 리스트(`[{"type": "text", "text": "<json>"}]`)로 오는데 `dict`/`str`만 처리하고 있었음.
2. `"command": "python"`이 PATH 의존적 — 다른 파이썬이 먼저 잡히면 `fastmcp` 못 찾고 죽음. `sys.executable`로 고정.
3. `env=`를 통째로 갈아치우면 Windows에서 불안정 — `SystemRoot` 등 필수 환경변수가 빠짐. 부모 환경을 이어받은 채로 `PYTHONPATH`/`FAB_DB`만 덧붙이도록 수정.
4. `MultiServerMCPClient.get_tools()`가 호출마다 새 세션(서브프로세스)을 만듦 — [MCP 연결](#mcp-연결-지속-세션) 참고. 가장 치명적이었던 버그(타임아웃 유발).
5. `secsgem-mcp/simulator/fab_model.py`가 Windows에서 `fab_model.yaml`을 못 읽음 — `read_text()`에 인코딩 지정이 없어 cp949로 읽으려다 한글 주석에서 `UnicodeDecodeError`. `encoding="utf-8"` 명시로 수정. `query_telemetry`의 정상범위 조회에 쓰이는 파일이라, 고쳐지기 전엔 `[자동]` 등급 검증 자체가 막혀 있었음.

## 남은 일

- uvicorn으로 실제 서버 띄워서 `/batch/run`·`/batch/results` HTTP 호출 확인
- 스텝8 예외 카드(UC-2 판단불가, UC-3 미매핑 패턴) — 코드는 있지만 이번 end-to-end 실행에서 실제로 타보지 못함. Center 외 패턴이나 전부 기각되는 그룹으로 별도 확인 필요
- [단순화 목록](#단순화-목록) 팀과 재설계
- 전체 배경·미결정 사항·문서 인덱스는 `docs/skeleton_kickoff.md` §5·§6 참고
