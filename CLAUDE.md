# CLAUDE.md

이 저장소를 처음 여는 Claude가 별도 탐색 없이 맥락을 잡기 위한 요약이다. 수치·세부는 각 절이
가리키는 **정본 문서**가 우선한다 — 정확한 숫자가 필요하면 정본을 다시 확인할 것.
변경 이력은 이 파일이 아니라 `git log`와 `docs/skeleton_kickoff.md`에 있다.

## 한눈에

**지식그래프(KG) × Fab 운영데이터 기반 웨이퍼맵 결함 근본원인분석(RCA) 시스템.** 수율 엔지니어가
"오늘 판독 배치 확인" 버튼을 누르면, 저수율 로트를 골라 결함 패턴을 판독하고, 지식그래프
(문헌 기반 "일반적으로 이런 원인이 있을 수 있다")와 MCP 서버(fab.db 기반 "이번에 실제로
무슨 일이 있었나")를 교차 검증해 근거 있는 원인 후보 카드를 만들어준다. 자유 질의는 없고
**고정 질문 템플릿**(`"{패턴} 결함 패턴이 나타나는 근본 원인은 무엇인가요?"`) 하나로만 돈다.

- 팀 프로젝트(SeSAC 2nd Project). **개인 작업 공간은 이 repo 안의 `personalspace_rca/`**(`.gitignore`
  등록, git 추적 밖). 날짜별 `MMDD work/` 폴더에 그날 노트를 둔다. Claude는 개인 작업/노트를
  항상 여기에 만들 것 — repo 상위의 옛 `Semiconductor/personalspace/`는 폐기된 위치다.
- 진행 중인 미완 배선: grouper가 `normal_lots`를 수집하지만 **저장→API→프론트 노출은 미구현**
  ("판독상 정상 N로트" 카드, status `normal_reading` 신설안 — 판독 담당).
- 정본: `docs/semiconductor_proposal.md`(기획 전체) · `docs/API_명세서_v2.0.md`(API 계약).

### ⚠️ 낡은 문서 주의보 — 아래는 인용하지 말 것

| 출처 | 낡은 부분 | 정본 |
|---|---|---|
| "GraphRAG" 명칭 | v1.5부터 이 시스템을 GraphRAG라 부르지 않는다(동적 커뮤니티 요약 미사용). 단 **코드 식별자에는 옛 이름이 남아 있다** — `nodes/graphrag.py`, `fetch_graphrag_candidates`, `graphrag_candidates` | 기획안 v1.5 |
| 노드 번호 ④/⑤ | 07-23 이전 문서·주석의 "④ Hypothesis / ⑤ Critic"은 구 번호 | 현행 **⑤ Hypothesis / ⑥ Critic** (④는 KG 조회) |
| proposal §6.2 | 가설 125건·`SpatialSignature` 빠진 구버전 스키마 | `kg_rca/STATUS.md` §1 · `docs/KG_schema_v1.3.md` |
| proposal §7.1 | "자동 tier는 즉시 채택/기각" | **⑤ soft / ⑥ hard** (아래 판정 책임 경계) |
| skeleton_kickoff §8.1 | "fine-tuning이 목표" · `pad_usage_hours` 미해결 | 파인튜닝 없음(v1.5 §7·§9) · pad_usage_hours 해소됨 |
| KG 스키마 "v1.4" | repo에 커밋된 적 없음 | `docs/KG_schema_v1.3.md`(없는 변경은 KG 담당자 확인) |
| `POST /batch/run`·`GET /batch/results` | **삭제된 엔드포인트** | `POST /api/v1/batches` · `GET /api/v1/analyses` |
| `docs/API_명세서_v1.0.md` | 이력 보존용, 정본 아님 | `docs/API_명세서_v2.0.md` §2 (§3.1은 계약이 아니라 에러 요약) |

## 다섯 개의 하위 프로젝트

`backend`/`kg_rca`/`secsgem-mcp`는 원래 팀원별 별도 저장소였으나 이 repo 밑으로 물리 이동하고
자체 `.git`을 삭제했다 — 지금은 전부 한 커밋 히스토리다. 파이썬 패키지는 루트 `pyproject.toml`
하나로 통합 관리하고(`uv sync`), `frontend`만 npm으로 따로 관리한다.

| 폴더 | 역할 | 상태 |
|---|---|---|
| `frontend/` | React + Vite 대시보드. 3화면 + 근거 모달 + 차트, dev 서버 `:5173` | API v2.0 정합 구현 |
| `backend/` | FastAPI + LangGraph 오케스트레이션. 파이프라인 ⓪~⑦ + API 10종 | 구현됨, 계속 갱신 중 |
| `wafer_reading/` | 판독 모듈 — `classifier/`(ResNet-18 5클래스), `stacking`(그룹 스택맵), `quantitative`(die-matrix→KG 어휘), `vlm/` | 구현됨. **학습 체크포인트 커밋 금지**(재학습으로 재생성) |
| `kg_rca/` | 지식그래프. 문헌 → Neo4j → LLM KG 추출 → 결정적 순회로 `hypotheses.json` 생성 | 완성, 계속 갱신 중 |
| `secsgem-mcp/` | MCP 서버. 시뮬레이터가 만든 가상 fab 데이터(`fab.db`)를 9종 도구로 조회 | 완성 |

## 파이프라인 (`backend/`) — ⓪~⑦ (기획안 v1.5 구조)

**배치 그래프**(state=`RCAState`) + **그룹 서브그래프**(state=`GroupState`, 그룹당 1회)의 2층
구조다. 바깥 `run_groups` 노드가 groups를 **순차로** 돌며 서브그래프를 호출한다(Send 병렬화는
MCP 싱글턴 세션 제약으로 보류).

```
[배치 그래프]
⓪ select_low_yield_lots  nodes/lowyield.py      저수율 로트 선별 (wafer.die_map 집계 SQL, 임계값 0.8)
① read_wafer_maps        nodes/cnn.py           CNN 5클래스 판정(Center/Edge-Ring/Scratch/Unknown/Normal)
                                                — ResNet-18 실연동, 체크포인트 없으면 "Center" 폴백
② group_by_pattern       nodes/grouper.py       패턴별 그룹화 (Normal은 그룹 미생성 → normal_lots로 수집)
③ observe_groups         nodes/vlm_describe.py  그룹 스택맵 관측(Observation) — die-matrix 실연동
                                                (stacking+quantitative → signature/angular 등 KG 어휘),
                                                VLM 자연어는 미연동
→ run_groups             graph.py               그룹마다 아래 서브그래프 호출 (contextvars로 [패턴] 로그 태그)

[그룹 서브그래프 — 노드 함수가 GroupState를 직접 받는다]
④ fetch_graphrag_candidates nodes/graphrag.py   KG 조회 — get_candidates(pattern, observation)
   ├─(후보 0건)──────────→ ⑦' respond_without_llm     ← route_on_candidates (조건부 엣지)
⑤ build_hypotheses       nodes/hypothesis.py    증거 수집·검증·fab 재랭킹 (자동 tier=LLM 에이전트)
⑥ review_hypotheses      nodes/critic.py        규칙 게이트 — 채택/기각/judge_unknown (결정론)
   ├─(채택 0건)──────────→ ⑦' respond_without_llm     ← route_on_verdicts (조건부 엣지)
⑦ generate_response      nodes/response.py      응답 카드 (실제 LLM 미연동, 템플릿)
```

- **조건부 엣지 2종이 환각 억제를 구조로 보장한다**: 후보 0건(unmapped)·채택 0건(insufficient)이면
  LLM 응답 노드로 가는 경로가 그래프에 아예 없다 — ⑦에 실제 LLM이 붙어도 재료 없이 문장을 쓰는
  경로가 위상적으로 차단된다.
- **재시도 없음**: 채택 0건이면 즉시 `insufficient_evidence`("판단 불가"). 이 가드는 노드 내부
  `if`가 아니라 위 조건부 엣지로 그래프 위상에 박혀 있다.
- **판정 책임 경계**: 최종 채택/기각은 **전부 ⑥ Critic**이 한다. ⑤는 tier 무관하게 증거 수집·검증·
  **랭킹(soft)**만 하고 기각하지 않는다 — 자동 tier도 evidence(drift 등)를 채워 ⑥ 규칙으로 넘긴다.
  ⑤가 LLM이어도 숫자(evidence)는 도구 반환에서 코드가 재구성하고 LLM은 서사(rationale)만 쓴다
  — Critic은 evidence만 읽어 판정한다(faithfulness firewall). 정본은
  `docs/node_langraph_spec/node_spec_05_hypothesis.md`·`node_spec_06_critic.md`.
- **그룹 고장 격리**: 한 그룹의 서브그래프가 노드 폴백이 못 잡는 예외(MCP 재던짐·LLM API 에러·
  Neo4j 끊김 등)를 던지면 `run_groups`가 **그 그룹만 로그+스킵**(배치 로그 `status="error"`)하고
  나머지로 배치를 완료한다 — "한 패턴 실패 ≠ 배치 실패". 실패 그룹은 재시도하지 않는다.
  `run_batch` 최상단의 배치-레벨 `except`는 그룹 루프 밖(⓪~③·저장)만 담당한다. 정본 D18.
- **실시간 모델/LLM 호출**: ①CNN(**비전 모델**, LLM 아님) · **⑤의 자동(Parameter) tier**
  (`create_react_agent` — 반자동·근거없음은 결정론) · ⑦(LLM 예정, 현재 템플릿).
  **⑥ Critic은 규칙 기반으로 LLM을 쓰지 않는다(확정).** ③VLM 자연어는 미연동.
- KG 검색 키: ①CNN 라벨(pattern) + ③관측(signature·angular·자연어)이 ④로 넘어가 진입(enum/의미)과
  판별자 재랭킹(morphology_rank)에 쓰인다. `KG_LIVE=1`이면 Neo4j 라이브 순회(`LiveKGClient` +
  semantic_entry), 기본은 `hypotheses.json` 파일 조회(`KGClient`).
- `state.py`: `RCAState`(cursor → target_lot_ids → cnn_results → groups …) / `GroupState`
  (group_id·pattern·lot_ids·observation → candidates → hypotheses → critic_result →
  final_response, 그룹키 reducer 4종). `graph.py`가 노드 함수를 직접 등록하고 kg_client·mcp는
  `functools.partial`로 조립 시점 주입한다.
- `main.py`는 **앱 조립만** 한다(CORS·라우터 등록·`store.init_db()`). 엔드포인트는 `api/`, 저장
  계층은 `store.py`, 전역 싱글턴(KGClient·MCPClient)은 `deps.py`.
- `store.py`: `app_state.db`(SQLite) 테이블 4종 — `cursor_state` · `batch` · `analysis` ·
  `wafer_reading`. 배치 커서 시작점은 `config.py`의 `DATA_EPOCH = "2026-01-01"`에서 파생된다.

**결함 패턴 처리 범위 (기획안 §6.1 확정)**: 이 프로젝트가 다루는 결함 패턴은
**Center/Edge-Ring/Scratch 3종뿐**이다. CNN은 여기에 **`Unknown`·`Normal`을 더해 판정**한다 —
WM-811K의 나머지 패턴은 전부 `Unknown`(= "새로운 결함 패턴")이고 **`Normal`은 정상 웨이퍼라
그룹을 만들지 않는다.** KG~응답생성 경로는 3종에만 연결된다.

### API 10종 (정본 `docs/API_명세서_v2.0.md` §2)

전부 `/api/v1` prefix, 라우터는 `backend/api/` 하위:

```
GET  /api/v1/yield-summary                                    수율 현황 요약 (화면1)
GET  /api/v1/analyses                                         분석 결과 대기열 (화면1)
POST /api/v1/batches                                          배치 실행 (202 비동기 접수)
GET  /api/v1/batches/{batch_id}                               배치 진행 상태 (화면2)
GET  /api/v1/analyses/{analysis_id}                           분석 결과 상세 (화면3)
GET  /api/v1/analyses/{analysis_id}/evidence/{hypothesis_id}  근거 상세 (모달)
GET  /api/v1/lots/{lot_id}/wafers                             로트 웨이퍼맵 판독
GET  /api/v1/lots/{lot_id}/wafers/{wafer_id}/die-map          웨이퍼맵 이미지
GET  /api/v1/yield-daily                                      일별 수율+이벤트 오버레이 (§2.8)
GET  /api/v1/stats/causes                                     장비·원인·패턴 집계 (§2.9)
GET  /health                                                  (prefix 밖, main.py 직접)
```

v2.0 확장(전부 additive): `status`에 `novel`(CNN Unknown=미지 패턴 OSR, 구 unmapped에서 분리) ·
`confidence`(medium|low — **high 없음**) · `yield_impact`(그룹 수율영향 %p) · `actions`(권장 조치
{type, hold, text}) · 가설 카드 `cluster_id`/`is_primary`(원인군).
**서버의 "오늘"은 `EVENT_DATE`**(기본 2026-04-01, env 오버라이드) — 날짜에 `now()` 금지.

### MCP 연결 시 반드시 알아야 할 것

`MultiServerMCPClient.get_tools()`는 **호출마다 새 stdio 서브프로세스**를 만든다(라이브러리
docstring에 명시된 동작). Hypothesis 노드처럼 다회 호출하는 패턴에서 치명적으로 느려서
(Center 244건 처리 시 타임아웃 실측) `mcp_client/client.py`는 `client.session()`으로 연결을
한 번만 열고 `load_mcp_tools(session, ...)`로 재사용한다. `MCPClient`는 모듈 레벨 싱글턴 유지
(`backend/deps.py`의 `_mcp_client` / `mcp_client()`) — 이 패턴을 깨지 말 것.

## kg_rca (지식그래프)

```
data/raw/ 문헌 → 표 행 단위 청킹 → Neo4j 적재 → LLM KG 추출(+검증규칙 6종) → 결정적 순회 + LLM 문장합성
```

- 스키마(정본 `docs/KG_schema_v1.3.md`): 노드 8종(`DefectPattern`·`SpatialSignature`·`ProcessStep`·
  `FailureMode`·`Cause`·`Parameter`·`Maintenance`·`Recipe`), 관계 7종(`ARISES_IN`/`OCCURS_IN`/
  `CAUSED_BY`/`VERIFIED_BY`/`ATTRIBUTED_TO`/`HAS_SIGNATURE`/`FORMS_IN`). 고정 vocabulary는
  `DefectPattern`(3종)·`ProcessStep`(6종)·`Parameter`(21종)뿐, 나머지는 LLM이 문헌에서 자유 추출.
- **검증등급 3단**이 ⑤에서 "어느 MCP 도구를 부를지"를 결정한다: **`[자동]`**(Parameter, 정상범위
  이탈을 시스템이 계산) / **`[반자동]`**(Maintenance·Recipe, 사람이 텍스트 판단) /
  **`[근거없음]`**(fab 데이터로 확인 불가). 등급 기준은 "fab.db에 데이터가 있느냐"가 **아니라**
  "결정적 조인 키 + 판정 규칙으로 자동 채택/기각까지 갈 수 있느냐"다.
- 출력물 `kg_rca/outputs/hypotheses.json` — backend가 읽는 **유일한** 산출물(Neo4j 없이도 이 파일만
  있으면 backend 동작). **가설 수는 재생성마다 바뀌므로 코드에 하드코딩 금지**(현재 수치는
  `kg_rca/STATUS.md` §1).
- 출력 스키마(정본 `kg_rca/KG_output_명세.md`): `route`/`score.confidence`가 빠지고
  `scenario_hint`(MCP 검증 체인 라우팅 A2/A3/A5/A6/null)와 `score.evidence_docs`/`evidence_chunks`로
  대체됐다. `backend/state.py`의 `GraphRAGCandidate`·`backend/graph_client/kg_client.py`가 이
  스키마를 따라간다 — **kg_rca 산출물을 갱신하면 이 두 파일도 같이 봐야 한다.**
- 실행 스크립트는 `0_reset.py`~`6_ask_graphrag.py`(번호가 실행 순서). **mapping_table 정본은
  `secsgem-mcp/simulator/mapping_table.yaml`** — kg_rca 로컬 사본은 없고 MCP 서버 원본을 직접 읽는다
  (`6_ask_graphrag.py`의 `MAPPING_PATH`). 회귀 테스트는 `kg_rca/tests/`(CI 포함).
- 미해결 문제 P1~P6(Maintenance 쏠림·점수체계 잔여·노드 중복·추출 비결정성·EDS 문헌 공백·
  ProcessStep join 의미필터)은 `kg_rca/STATUS.md` §4가 정본.
- `pad_usage_hours`는 시뮬레이터에 반영 완료 — `secsgem-mcp/simulator/fab_model.yaml` CMP 블록의
  `{normal: [0, 250], unit: h, counter_rate_per_day: 11}`.

## secsgem-mcp (MCP 서버, 9종 도구)

WM-811K 웨이퍼맵 + SECS/GEM 시뮬레이터 합성 fab 데이터(`fab.db`, SQLite, read-only)를 lot/wafer
키로 결합해 제공. **실시간 SECS/GEM 통신은 하지 않는다** — 전부 빌드타임 생성 데이터.
(MixedWM38은 팀 결정으로 제외 — 시뮬레이터 빌드도 WM-811K만 받는다.)

| 도구 | 조회 대상 | 역할 |
|---|---|---|
| `get_wafer_map` | wafer | 웨이퍼 이미지(base64 PNG, 라벨 없음) — VLM 입력용 |
| `get_lot_history` | lot_history | 로트가 지난 장비 이력 |
| `run_commonality_analysis` | lot_history | 불량 로트 공통 장비 — **모든 가설 공통 호출** |
| `get_normal_lot_ratio` | wafer+lot_history | 반대 증거(정상 로트 비율) — **모든 가설 공통 호출** |
| `query_telemetry` | telemetry | 센서값 시계열, `[자동]` 등급 전용 |
| `get_maintenance_history` | maintenance | 정비 이력, `[반자동]` 등급 전용 |
| `get_alarm_history` | alarm | 알람 — `lot_id`가 아닌 **`equipment_id`로 조회**해야 값이 나옴(알람 131건 전부 `lot_id=NULL`) |
| `detect_change_points` | metric_series/event_log | 변화점 탐지 (현재 파이프라인 미사용) |
| `get_lot_timeline` | lot_history+alarm | 시간 정합 검사(Critic 단계) |

모든 응답은 `{data, meta}` 공통 스키마. `meta.coverage.missing`으로 없는 구간을 명시하고,
**웨이퍼 라벨은 어떤 도구도 반환하지 않는다**(정답 누출 차단). fab.db 스키마 7개 테이블 요약은
`secsgem-mcp/README.md` §3.

## 설치 · 실행

```bash
pip install uv
uv venv && uv sync                # 루트 pyproject.toml 하나로 backend/kg_rca/secsgem-mcp 전부 설치
.venv\Scripts\activate             # Windows
cp .env_example .env               # 상대경로 이미 맞춰짐, OPENAI_API_KEY만 채우면 됨
uvicorn backend.main:app --reload  # 터미널 1 → :8000

cd frontend && npm install && npm run dev   # 터미널 2 → :5173
```

브라우저는 `http://localhost:5173`으로 연다(백엔드 단독 확인은 `http://localhost:8000/docs`).
CORS는 `:5173`만 허용된다(`backend/main.py`, 프록시 미사용).
`secsgem-mcp/datasets/fab.db`가 없으면 `secsgem-mcp/README.md` "데이터 준비" 선행 필요.

**⚠️ 환경변수를 추가·변경하면 `.env_example`도 같은 PR에서 고친다.** `.env`는 gitignore라 안 고치면
다른 팀원은 그 변수 없이 돌다 폴백/에러로 샌다.

- 새 키는 `.env_example`에 **한 줄 주석**(용도·기본값)과 함께 넣는다.
- 비밀값(`*_KEY`·`*_SECRET`·`*_PASSWORD`·`*_TOKEN`)은 **값을 비워** `KEY=` 형태로만 — 채우면 그대로 커밋된다.
- 선택 옵션은 기존 `#KG_LIVE=1`처럼 **주석 처리**해서 넣고, 안 쓰는 키는 지운다.
- 셀프체크: diff에 `getenv`/`environ`이 있는데 `.env_example` diff가 없으면 리뷰에서 잡는다.
- 현재 `.env`와 `.env_example`은 이미 어긋나 있다 — **건드리는 키만** 맞추고 전체 정리는 별도 이슈.

테스트(fab.db 빌드 불필요 — CI와 동일 스코프):

```bash
pytest -q -m "not data" backend/tests kg_rca/tests   # 228 passed·2 xfailed (07-26 기준선)
cd secsgem-mcp && pytest -q -m "not data"            # 31건 — 상대경로(cwd) 의존이라 자기 폴더에서
```

⚠️ 루트에서 인자 없이 `pytest`를 돌리면 secsgem-mcp 테스트가 cwd 문제로 실패한다 — 위처럼 나눠 돌 것.

## 알려진 단순화 / TODO (코드에 `# 결정①/②` 또는 `TODO(팀 결정 필요)`로 표시됨)

| 위치 | 지금 선택 | 비고 |
|---|---|---|
| `hypothesis.py` 결정① MCP 호출 단위 | 자동 tier는 step 배치 telemetry 1콜, 반자동·근거없음은 `(step, evidence_label, evidence)` 캐싱 | 후보 단위 호출은 244건에서 타임아웃 실측 |
| `hypothesis.py` 결정② `step=None` 후보 | **mapping.process로 step 폴백**(`_with_step_fallback`, D14) | 신규 산출물에선 step=None이 줄었고 폴백은 잔여분 안전망 |
| `lowyield.py` 저수율 임계값 | `LOW_YIELD_THRESHOLD = 0.8` 고정값 | 동적 임계값 미검토 |
| `grouper.py` 최소 로트수 게이트 | `MIN_LOTS_PER_GROUP = 1`(게이트 없음) | 서브클러스터링 없음 |
| `cnn.py` 체크포인트 부재 | `"Center"` 폴백(CI·미학습 환경 대비) | 폴백 중엔 그룹이 1개만 생긴다 |
| `vlm_describe.py` VLM 자연어 | **미연동** — die-matrix 성분만 실연동, location/morphology_text는 빈 값 | **파인튜닝 없음** 확정, VLM API + few-shot 예정. signature가 있으면 자연어 없어도 KG enum 진입 가능 |
| `response.py` | 실제 LLM 미연동, 결정적 템플릿 | 채택 0건 시 LLM 미호출은 조건부 엣지로 구조화됨 |
| 검증 라운드 상한 | **배치당 에이전트 스텝 상한** `AGENT_RECURSION_LIMIT = 8` — 초과 시 그 배치 미조사 폴백 | 가설별 추적 ID 로깅 미반영. 후보 전량 순회는 유지(함축은 랭킹 담당) |

컴포넌트별 상세 개선 목록(VLM/Hypothesis/Critic/응답생성/E2E평가 5개 표)은
`docs/skeleton_kickoff.md` §8 — 재설계 착수 전 체크리스트로 쓸 것.

## 평가 체계 (정본: `docs/semiconductor_proposal.md` §6.4·§10)

- 데이터 역할: **WM-811K**=결함을 본다(입력) · **KG**=원인 후보를 만든다(지식) ·
  **fab.db**=후보를 검증한다(사실) · **Ground Truth**=성능을 평가한다(평가).
- E2E 정답 대조는 **11개 시나리오 중 1개 완료** — SC-CENTER-01에서 근본원인 top-1 달성
  (정답 193위 rejected → 0위 accepted, 함정 P2 시간역전 44건 명시 기각).
  대조 키는 `matched_cause`(kg cause↔시뮬레이터 어휘 변환표) — **cause 문자열 직접 비교는 표기
  차이로 0%가 나온다.** 스크립트·결과는 `personalspace_rca/0723 work/`(git 밖).
- 미완: 나머지 10개 시나리오 · 단일경로 baseline 비교 · `secsgem-mcp/eval/metrics.py`(스텁) 수리.
- 지표 8종: Latency / 판독 정확도(P·R) / 설명 정확도(BLEU·ROUGE-L) / faithfulness / 경로 정합성 /
  **단일경로 vs 다중가설탐색 RCA 품질**(핵심 비교 실험) / 사용자 만족도 / KG-Fab 어휘 정합성.

## 알려진 버그(수정·재검증 완료 — 재발 방지용 기록)

1. `mcp_client/client.py`의 `_as_dict`가 구조화 출력 없을 때 MCP 표준 콘텐츠 블록 리스트
   (`[{"type": "text", "text": "<json>"}]`)를 못 받았음 — dict/str만 처리하던 버그.
2. MCP 서버 기동 커맨드를 `"command": "python"`으로 두면 PATH 의존적으로 다른 파이썬이 잡혀
   `fastmcp`를 못 찾고 죽음 — `sys.executable`로 고정할 것.
3. Windows에서 `env=`를 통째로 갈아치우면 `SystemRoot` 등이 빠져 불안정 — 부모 환경을 이어받은
   채로 `PYTHONPATH`/`FAB_DB`만 덧붙일 것.
4. `MultiServerMCPClient.get_tools()`가 호출마다 새 세션을 만드는 문제(위 "MCP 연결" 절) —
   가장 치명적이었던 버그(타임아웃 유발).
5. `fab_model.py`가 Windows에서 `fab_model.yaml`을 인코딩 미지정으로 읽어 한글 주석에서
   `UnicodeDecodeError` — **Windows에서 파일 읽을 때는 항상 `encoding="utf-8"` 명시.**

## Git 컨벤션 요약 (정본: `docs/git_convention_v0.2.md`)

- 브랜치: `develop` 없이 **`main` 하나만**. 이슈 기반 브랜치 → PR → `main`. `main` 직접 push 금지.
- 커밋: `[Type] #이슈번호 제목` — Type은 `Feat`/`Fix`/`Refactor`/`Docs`/`Chore`/`Test`.
- 브랜치명: `{type}/#이슈번호-작업내용` — 작업내용은 영어 소문자 + 하이픈으로만(한글 금지).
- PR: 리뷰어 1명 승인 후 **해당 리뷰어가 merge**, 병합 브랜치는 삭제하지 않고 유지.
- 금지: `--force` 푸시, `main` 직접 push, `.env`/API 키/`fab.db` 커밋.

## 막히면 볼 문서 (정본 인덱스)

| 궁금한 것 | 문서 |
|---|---|
| 기획 전체(배경·차별점·기술스택·평가방법·타임라인) | `docs/semiconductor_proposal.md` |
| 백엔드 현재 상태·구조·실행법 | `README.md` |
| 스켈레톤 구축 로그·팀 결정사항·컴포넌트별 개선목록 (가장 자주 갱신) | `docs/skeleton_kickoff.md` |
| LangGraph 골격·노드별 설계(①CNN·③VLM관측·④KG조회·⑤Hypothesis·⑥Critic·⑦Response) | `docs/node_langraph_spec/` |
| 백엔드 내부 정책 결정(D1~D18) | `docs/BACKEND_DECISIONS.md` |
| 프론트↔백엔드 API 계약 10종(정본) | `docs/API_명세서_v2.0.md` |
| KG 스키마 전체 명세 | `docs/KG_schema_v1.3.md` |
| `hypotheses.json` 출력 필드별 상세 명세(정본) | `kg_rca/KG_output_명세.md` |
| KG 진행상황·남은 문제·가설 수 | `kg_rca/STATUS.md` |
| KG↔MCP 정합성 검토(용어 불일치 등) | `kg_rca/MCP_KG_정합성검토.md` |
| 데이터 모델 설계 | `kg_rca/데이터 모델 설계_v2.0.md`, `kg_rca/데이터 모델 설계_v3.0.md` |
| MCP 9종 도구 상세 계약 | `secsgem-mcp/README.md` |
| MCP 시나리오(A0~E4) | `docs/SECS_GEM MCP document.md` |
| Git 컨벤션 | `docs/git_convention_v0.2.md` |
