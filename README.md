# SesacLine SemiRCA — 백엔드

FastAPI + LangGraph로 웨이퍼맵 결함 근본원인분석(RCA) ⓪~⑥ 파이프라인을 오케스트레이션하는 백엔드.
`kg_rca`(GraphRAG, 문헌 기반 원인 후보)와 `secsgem-mcp`(MCP 9종 도구, fab.db 실측 데이터 조회)를 잇는 자리다.
둘 다 이 repo 밑의 평범한 하위 폴더로 들어와 있다(공동작업 편하게 하려고 0713에 옮기면서
각자 갖고 있던 `.git`은 지웠다 — 이 repo를 git init하면 안의 파일까지 그대로 하나의 히스토리로 잡힌다).

## 지금 상태: Walking Skeleton 완성 (2026-07-13)

⓪~⑥ 전체가 실제로 end-to-end로 돈다 — `raise NotImplementedError`는 다 없어졌다. 단,
**아직 "제대로 설계"가 아니라 "일단 돌아가게 가장 단순한 선택으로 채운" 상태**다. 정확히 뭐가
단순화됐는지는 아래 [Walking Skeleton 단순화 목록](#walking-skeleton-단순화-목록-팀-재검토-필요)을,
전체 배경·설계 논의·진행 로그는 `personalspace/0713 work/skeleton_kickoff.md`를 본다(이 README는
"지금 코드가 뭘 하는지" 요약이고, 그 문서가 "왜 이렇게 됐는지"의 정본이다).

실제로 돌려서 확인한 결과(2026-03-04 배치, Center 그룹):

```
저수율 로트 선별 → SVLOT-009 (수율 0.0)
그룹화          → Center-2026-03-04 그룹 1개
GraphRAG 후보   → 244건
Hypothesis 검증 → 244건 전부 MCP 실호출로 확인
Critic 심사     → 136건 채택 / 108건 기각
응답 카드       → "Center 패턴 — 가설 136건 채택"
```

채택된 가설 중 `high_film_stress`(cause) 후보가 `DEPO-03` 장비의 `chamber_pressure`에서
정상범위(`[2.0, 3.0]`) 이탈을 실제로 잡아냈다 — fab.db 시뮬레이터에 진짜로 주입된 유일한
Center 자동판정 시나리오라, 파이프라인이 제대로 동작한다는 증거로 쓸 수 있다.

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
    hypothesis.py        # ④ Hypothesis 노드 — MCP 실호출, 검증단위 캐싱 포함(아래 참고)
    critic.py            # ⑤ Critic 노드 — 시간정합/반대증거/faithfulness/KG메커니즘 4규칙
    response.py          # ⑥ 응답생성 — 실제 LLM 미연동, 결정적 템플릿 문자열
  mcp_client/           # secsgem-mcp 9종 도구 클라이언트 (지속 세션 재사용, 아래 참고)
  graph_client/         # kg_rca 결과(hypotheses.json) 조회 클라이언트
kg_rca/                 # GraphRAG (0713부터 하위 폴더, 평범한 폴더 — 자체 .git 없음)
secsgem-mcp/            # MCP 서버 9종 도구 + fab.db (0713부터 하위 폴더, 평범한 폴더 — 자체 .git 없음)
```

파이프라인에서 LLM을 실시간 호출하는 노드는 ①VLM과 ⑥응답생성 둘뿐이다(2026-07-09 노드화 결정 —
상세는 `semiconductor_proposal.md` §2/§7 참고). **지금은 이 둘조차 LLM을 안 쓴다** — Walking
Skeleton이라 하드코딩/템플릿으로 대체돼 있다. 나머지(③~⑤)는 원래부터 결정적 함수다.

## 의존 관계

- `kg_rca/`가 미리 계산해 둔 `outputs/hypotheses.json`을 읽는다(③). 배치 스크립트 결과물이라
  Neo4j가 없어도 이 파일만 있으면 스켈레톤이 돌아간다.
- `secsgem-mcp/`의 MCP 서버를 stdio로 붙여 9종 도구를 호출한다(④⑤). 서버는 미리 띄워둘 필요
  없음 — 첫 도구 호출 시점에 자동으로 서브프로세스를 띄운다(아래 [MCP 연결](#mcp-연결-지속-세션) 참고).
- 둘 다 `.git`이 없는 평범한 폴더라, 이 repo에서 `git init` 후 `git add -A`하면 두 폴더 안
  파일까지 전부 하나의 커밋 히스토리로 들어간다(`kg_rca`/`secsgem-mcp` 각자의 이전 커밋 기록은
  더 이상 로컬에 없음, 필요하면 원본 repo에서 따로 백업 확인).

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
  최초 실행 시 커서는 `2026-03-04`로 시작한다(하드코딩, `backend/main.py`의 `_FIRST_CURSOR_DATE`).
- `GET /batch/results` — 지금까지 쌓인 배치 결과를 그룹별로 반환.
- `GET /health` — 상태 확인용.

**아직 uvicorn으로 직접 띄워서 HTTP 호출까지는 확인 안 했다** — 지금까지의 end-to-end 검증은
`backend.graph.build_graph(...).ainvoke(initial_state)`를 파이썬에서 직접 호출하는 방식으로 했다.
FastAPI 경로(특히 `app_state.db` 파일 생성 위치, 여러 요청에 걸친 MCP 세션 유지)는 별도 확인 필요.

### MCP 연결 (지속 세션)

`MultiServerMCPClient.get_tools()`는 편의 API라 **호출마다 새 stdio 서브프로세스를 띄운다**
(라이브러리 자체 docstring에 명시돼 있음). 가설 하나 검증하는 데도 MCP를 여러 번 부르는
Hypothesis 노드 패턴에서는 이게 치명적으로 느려서(실측: Center 244건 처리 시 타임아웃),
`mcp_client/client.py`는 `client.session()`으로 연결을 한 번만 열고 `load_mcp_tools(session, ...)`로
그 세션을 계속 재사용한다. `MCPClient` 인스턴스를 여러 개 만들지 말 것 — `backend/main.py`처럼
모듈 레벨 싱글턴으로 두고 앱 생명주기 동안 재사용하는 게 맞다.

## Walking Skeleton 단순화 목록 (팀 재검토 필요)

전부 코드에 `# 결정①/②/③` 주석 또는 "TODO(팀 결정 필요)"로 표시돼 있다.

| # | 위치 | 지금 선택 | 왜 단순화했는지 / 재검토 포인트 |
|---|---|---|---|
| 1 | `hypothesis.py` — MCP 호출 단위 | 가설 단위로 짜되, `(step, evidence_label, evidence)`가 같으면 캐싱해서 재사용 | 처음엔 캐싱도 없이 짰다가 244건 처리 중 실제로 타임아웃 나서, 최소한의 캐싱만 응급으로 추가함. "검증 단위로 제대로 설계"까지는 아님 |
| 2 | `hypothesis.py` — `route="direct"` 의심 장비 | `step=None`을 그냥 `run_commonality_analysis`에 넘김 | 전체 공정이 뭉뚱그려져 신호가 흐려지는 걸 감수한 선택. 다른 대안(장비 좁히기 생략, 1차 범위 제외) 안 써봄 |
| 3 | `hypothesis.py` — `direction: null`인 `[자동]` 후보 | `candidate.direction` 안 보고, 정상범위 이탈이면 무조건 `drift_detected=True` | 해당 건수가 적어서(전체 패턴 합쳐 4건) 지금 규모엔 영향 작음 |
| 4 | `lowyield.py` — 저수율 임계값 | `LOW_YIELD_THRESHOLD = 0.8` 고정값 | mean - k*std 같은 동적 임계값도 검토 대상 |
| 5 | `grouper.py` — 최소 로트수 게이트 | `MIN_LOTS_PER_GROUP = 1` (게이트 없음) | 서브클러스터링도 안 함 |
| 6 | `vlm.py` | 실제 VLM 미연동, `pattern="Center"` 고정 | 스텝9(end-to-end)까지 LLM 비용 없이 먼저 확인하려는 목적(Walking Skeleton) |
| 7 | `response.py` | 실제 LLM 미연동, 결정적 템플릿 문자열 | 위와 같음 |
| 8 | `main.py` — 배치 시작 커서 날짜 | `2026-03-04` 하드코딩 | fab.db 실제 데이터 범위 기준 시작일 정책 미정 |

## 알려진 버그 (전부 발견·수정·재검증 완료)

end-to-end로 실제로 돌려보면서 5개를 찾았다 — 코드로만 보고는 안 드러나던 것들이라 참고용으로 남긴다.

1. **`mcp_client.py`의 `_as_dict`가 MCP 응답 모양을 못 받음** — 구조화 출력이 없으면 MCP 표준 콘텐츠 블록 리스트(`[{"type": "text", "text": "<json>"}]`)로 오는데 `dict`/`str`만 처리하고 있었음.
2. **`"command": "python"`이 PATH 의존적** — 시스템에 다른 파이썬이 먼저 잡히면 `fastmcp` 못 찾고 죽음. `sys.executable`로 고정.
3. **`env=`를 통째로 갈아치우면 Windows에서 불안정** — `SystemRoot` 등 필수 환경변수가 빠짐. 부모 환경을 이어받은 채로 `PYTHONPATH`/`FAB_DB`만 덧붙이게 수정.
4. **`MultiServerMCPClient.get_tools()`가 호출마다 새 세션(서브프로세스)을 만듦** — 위 [MCP 연결](#mcp-연결-지속-세션) 참고. 가장 치명적이었던 버그(타임아웃 유발).
5. **`secsgem-mcp/simulator/fab_model.py`가 Windows에서 `fab_model.yaml`을 못 읽음** — `read_text()`에 인코딩 지정이 없어 cp949로 읽으려다 한글 주석에서 `UnicodeDecodeError`. `encoding="utf-8"` 명시로 수정. (이 파일이 `query_telemetry`의 정상범위 조회에 쓰여서, 고쳐지기 전엔 `[자동]` 등급 검증 자체가 막혀 있었음.)

## 남은 일

- uvicorn으로 실제 서버 띄워서 `/batch/run`·`/batch/results` HTTP 호출 확인
- 스텝8 예외 카드(UC-2 판단불가, UC-3 미매핑 패턴) — 코드는 있지만 이번 end-to-end 실행에서 실제로 타보지 못함. Center 외 패턴이나 전부 기각되는 그룹으로 별도 확인 필요
- 위 [단순화 목록](#walking-skeleton-단순화-목록-팀-재검토-필요) 팀과 재설계
- 전체 배경·미결정 사항·문서 인덱스는 `personalspace/0713 work/skeleton_kickoff.md` §5·§6 참고
