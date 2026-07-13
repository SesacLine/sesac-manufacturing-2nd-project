# 스켈레톤 구축 가이드 — SesacLine_SemiRCA

이 문서는 Hypothesis/Critic 연결 레이어의 스켈레톤 코드를 짜기 전에, **무엇을 어느 순서로 건드릴지**와 **KG·fab.db 쪽 전문용어**를 팀 전체가 같은 이해로 시작할 수 있게 정리한 것이다. 0711에 처음 썼고, 이후 진행 상황에 맞춰 계속 갱신한다 — 지금 보는 버전이 항상 최신 상태를 반영한다(누적된 수정 로그는 §7에 따로 모아뒀다).

---

## 1. 지금 상태 한눈에

| 조각 | 상태 | 위치 |
|---|---|---|
| KG(지식그래프) 원인 탐색 | 완성, 계속 갱신 중(v2.3). 재생성될 때마다 가설 건수가 바뀐다 — 정확한 값은 항상 `kg_rca/STATUS.md` §1에서 확인 | `SesacLine_SemiRCA/kg_rca/` |
| MCP 서버(9개 조회 도구) | 완성, fab.db 조회 함수 9개 전부 구현됨 | `SesacLine_SemiRCA/secsgem-mcp/` |
| 연결 코드(Hypothesis/Critic 등) | **스텝0~9 전부 구현 완료, end-to-end 실행 검증까지 끝남**(아래 §4) — 단 Walking Skeleton이라 여러 곳을 단순화했다(§5) | `SesacLine_SemiRCA/backend/` |

- **Walking Skeleton이 실제로 끝까지 돈다**: 2026-03-04 배치로 돌려서 저수율 로트 선별(`SVLOT-009`) → VLM(하드코딩) → 그룹화 → GraphRAG 후보 244건 조회 → Hypothesis 검증(MCP 실호출) → Critic 심사(136건 채택/108건 기각) → 응답 카드 생성까지 전부 확인했다. 채택된 가설 중엔 fab.db에 실제로 주입된 `Center/DEPO/chamber_pressure` drift도 정확히 잡아냈다(§4 스텝9).
- 세 조각 다 `SesacLine_SemiRCA/` 밑에 있다(0713에 물리적으로 합침 — 공동작업 편하게 하려는 목적). `kg_rca`, `secsgem-mcp`가 원래 갖고 있던 각자의 `.git`은 팀 결정으로 삭제했다 — 이제 `SesacLine_SemiRCA`에서 `git init`하면 안의 파일까지 전부 하나의 히스토리로 잡힌다.
- 가상환경은 루트 `SesacLine_SemiRCA/.venv` 하나만 쓴다(`pyproject.toml` 하나로 세 곳 의존성 통합, `uv sync`로 설치). `.gitignore`도 루트 하나로 병합, `.env`는 `./kg_rca`·`./secsgem-mcp` 상대경로로 이미 맞춰져 있다.
- KG는 "이 결함 패턴이면 일반적으로 어떤 원인이 있을 수 있는지"를 문헌에서 찾아주고, MCP 서버는 "이번에 실제로 문제가 된 로트가 어느 장비를 지났고 그 장비에서 무슨 일이 있었는지"를 조회해준다. Hypothesis 노드는 KG가 준 원인 후보 하나하나를 MCP 서버로 실제로 확인해보는 역할이고, Critic 노드는 그 확인 결과가 믿을 만한지 다시 한번 점검하는 역할이다.
- Hypothesis·Critic은 자유롭게 판단하는 LLM이 아니라 **정해진 규칙대로 동작하는 함수**로 만든다(2026-07-09 팀 결정). 파이프라인에서 LLM을 실시간 호출하는 노드는 ①VLM과 ⑥응답생성 둘뿐이고, ③~⑤는 전부 결정적 함수다.

---

## 2. 배경지식 — KG 쪽 전문용어

### 2.1 "노드"와 "관계"란

그래프는 점(노드)과 그 점들을 잇는 선(관계)으로 이루어진다. 노드 하나는 구체적인 개념 하나(예: "Edge-Ring이라는 결함 패턴 하나", "ETCH라는 공정 하나")를 가리키고, 관계 하나는 두 노드 사이의 연결(예: "이 결함 패턴은 이 공정에서 나타난다")을 나타낸다. 그래프를 읽는다는 건, 결함 패턴 노드에서 출발해서 관계를 따라가며 원인 노드까지 도달하는 것이다.

### 2.2 노드 8종류 (v2.3, `SpatialSignature` 포함)

| 노드 이름 | 뜻 | 예시 | 어디서 오는가 |
|---|---|---|---|
| `DefectPattern` (결함패턴) | 웨이퍼맵에 나타난 결함 모양의 종류 | `Edge-Ring`, `Center`, `Scratch` | 미리 정해진 3종만 사용 |
| `SpatialSignature` (형상시그니처) | (형상, 구역) 쌍 — 결함 모양을 패턴 이름 대신 "생김새"로 표현 | `ring@edge`, `cluster@center` | 미리 정해진 3종만 사용 |
| `ProcessStep` (공정단계) | 반도체를 만드는 6개 공정 단계 중 하나 | `ETCH`(식각), `DEPO`(증착) 등 | 미리 정해진 6종만 사용 |
| `FailureMode` (고장모드) | 특정 공정에서 발생한 구체적인 이상 현상 | "식각 속도가 잘못됨" | 문헌에서 자동으로 뽑음 |
| `Cause` (원인) | 그 고장모드를 일으킨 근본 원인 | "RF 파워가 변함" | 문헌에서 자동으로 뽑음 |
| `Parameter` (센서변수) | 장비가 실시간으로 측정하는 값의 이름 | `rf_power`, `chamber_pressure` | 미리 정해진 20종만 사용 |
| `Maintenance` (정비기록) | 원인을 검증할 수 있는 정비 행위 | "챔버 습식 세정" | 문헌에서 자동으로 뽑음 |
| `Recipe` (레시피) | 원인을 검증할 수 있는 공정 설정값 | "공정 레시피" | 문헌에서 자동으로 뽑음 |

`Parameter`·`Maintenance`·`Recipe` 셋은 "증거"라는 공통 이름(`Evidence`)으로도 묶인다 — 이 셋이 바로 MCP 서버로 실제 데이터를 조회하는 지점이기 때문이다.

`DefectPattern`·`SpatialSignature`·`ProcessStep`·`Parameter`는 **미리 정해진 목록 안에서만 고른다.** 나머지 넷(`FailureMode`·`Cause`·`Maintenance`·`Recipe`)은 문헌을 읽고 AI가 자동으로 새로 만들어낸 것이라, 문헌마다·실행마다 다른 이름으로 나올 수 있다.

`SpatialSignature`가 왜 필요한가: 문헌 중에는 "패턴 이름"이 아니라 "형상"으로 원인을 서술하는 것들이 있다(예: "링 모양 결함은 보통 세정 공정 문제를 반영한다"). 이걸 억지로 `Center`/`Edge-Ring`/`Scratch` 중 하나에 끼워 맞추지 않고 형상 층위에 그대로 담아두는 노드다. VLM이 3종 밖의 패턴(예: `Donut`)을 만났을 때도 "형상만 보고" 가설 경로를 탈 수 있게 해주는 미지 패턴 대응의 발판이기도 하다. 단, 지금 데이터에서는 형상 경유 경로(`route="signature"`)가 전부 공정 경유 경로와 중복돼 대표로 안 남기 때문에 실제 출력엔 0건이다.

### 2.3 관계 7종류

| 관계 이름 | 어디서 어디로 | 뜻 |
|---|---|---|
| `ARISES_IN` | 결함패턴 → 공정단계 | 이 결함 패턴이 어느 공정에서 나타나는가 |
| `OCCURS_IN` | 고장모드 → 공정단계 | 이 고장이 어느 공정에서 발생하는가 |
| `CAUSED_BY` | 고장모드 → 원인 | 이 고장의 원인이 무엇인가 |
| `VERIFIED_BY` | 원인 → 증거 | 이 원인을 어떤 데이터로 확인할 수 있는가 |
| `ATTRIBUTED_TO` | 결함패턴 → 원인 | 공정을 특정할 수 없을 때, 결함 패턴에서 원인으로 바로 연결 |
| `HAS_SIGNATURE` | 결함패턴 → 형상시그니처 | 이 패턴은 어떤 형상으로 정의되는가 (시드에서 결정적으로 연결) |
| `FORMS_IN` | 형상시그니처 → 공정단계 | 이 형상은 주로 어느 공정에서 생기는가 |

가설 하나는 이 관계들을 따라간 경로 하나다. 예: "`Edge-Ring` 결함은 → `ETCH` 공정에서 → `incorrect_etch_rate`라는 고장이 → `improper_maintenance`라는 원인으로 → `chamber_wet_clean`이라는 정비 기록으로 확인 가능하다."

### 2.4 검증등급 — `[자동]` / `[반자동]` / `[근거없음]`

| 등급 | 증거 종류 | 실제로 무슨 일이 일어나는가 |
|---|---|---|
| `[자동]` | `Parameter`(센서값) | 정상범위라는 숫자 기준이 있어서, 값이 그 범위를 벗어났는지 계산만 하면 된다. 사람 없이 시스템이 채택/기각까지 결론 낼 수 있다 |
| `[반자동]` | `Maintenance`(정비기록) 또는 `Recipe`(레시피) | 데이터는 조회할 수 있지만 "이 값이면 이상하다"는 기준이 없다. 정비 기록은 자유 텍스트라서, 이 결함과 관련 있는 정비인지는 사람이 읽고 판단해야 한다 |
| `[근거없음]` | 없음 | 문헌에만 나오는 원인이고, fab 데이터로 확인할 방법 자체가 없다 |

이 등급 구분이 §4에서 "어떤 MCP 함수를 부를지"를 결정하는 기준이 된다.

---

## 3. 배경지식 — fab.db / MCP 툴

fab.db는 실제 공장 데이터가 아니라, 시뮬레이터가 만들어 둔 가상의 공장 운영 기록이다.

| 표 이름 | 무엇이 들어있나 | 언제 한 줄씩 생기나 |
|---|---|---|
| `lot_history` | 로트 하나가 어느 장비를, 몇 시부터 몇 시까지 지났는지 | 로트가 공정 6단계를 지날 때마다(로트당 6줄) |
| `telemetry` | 장비가 계속 내보내는 센서 측정값 | 2시간에 한 번씩 |
| `maintenance` | 정비 기록(정기/돌발, 교체 부품) | 정기 주기마다, 또는 고장 났을 때 |
| `alarm` | 장비에서 울린 경보 | 확률적으로, 또는 특정 상황에서 |
| `metric_series` | 장비별 하루 단위 수율 집계 | 매일 |
| `event_log` | `maintenance`와 같은 사건을 더 뭉뚱그려서 기록 | `maintenance`와 같은 시각 |
| `wafer` | 웨이퍼 한 장의 최종 검사 결과(양품/불량, 위치) | 로트가 마지막 공정(웨이퍼 테스트)을 끝냈을 때 |

**`maintenance`가 왜 `[반자동]`인지**: `parts` 칸에 "무슨 부품을 교체했다"는 문장이 그대로 들어있다. `telemetry`처럼 숫자 기준이 없어서, 이 정비가 지금 결함과 실제로 관련 있는지는 시간(정비 시각이 결함 발생 시각보다 앞서는가)과 사람의 판단으로 확인해야 한다.

### 3.1 MCP 서버 9개 함수

| 함수 이름 | 어느 표를 보는가 | 언제 부르는가 |
|---|---|---|
| `get_wafer_map` | `wafer` | 웨이퍼 이미지가 필요할 때(① VLM 단계) |
| `get_lot_history` | `lot_history` | 이 로트가 어느 장비들을 지났는지 확인할 때 |
| `run_commonality_analysis` | `lot_history` | 불량 로트들이 공통으로 지난 장비를 찾을 때 — **모든 가설에 항상 사용** |
| `get_normal_lot_ratio` | `wafer` + `lot_history` | 그 장비를 지난 정상 로트 비율(반대 증거) — **모든 가설에 항상 사용** |
| `query_telemetry` | `telemetry` | 증거가 `Parameter`(센서값)일 때만 |
| `get_maintenance_history` | `maintenance` | 증거가 `Maintenance`(정비기록)일 때만 |
| `get_alarm_history` | `alarm` | 보조 확인용 |
| `detect_change_points` | `metric_series`/`event_log` | 수율이 언제부터 나빠졌는지 찾을 때 |
| `get_lot_timeline` | `lot_history` + `alarm` | 시간 순서가 맞는지 확인할 때(Critic 단계) |

---

## 4. 빌드 순서 — 스텝별 상태

`SesacLine_SemiRCA/backend/` 기준. 각 스텝은 의존관계와 완료 기준을 같이 적었다.

### ✅ 스텝 0. 환경 준비 — 완료

- `kg_rca`, `secsgem-mcp`는 `SesacLine_SemiRCA/` 밑에 있다.
- 가상환경: `pip install uv && uv venv && uv sync` (루트 `pyproject.toml` 하나로 세 곳 의존성 통합됨). 완료 확인됨 — `.venv`에서 `fastapi`/`langgraph`/`langchain_mcp_adapters`/`dotenv` 전부 import 성공.
- `.env`는 `.env_example`을 복사해 이미 채워져 있다(`OPENAI_API_KEY`도 채움).
- `secsgem-mcp/datasets/fab.db` 존재 확인됨.

### ✅ 스텝 1. `graph_client/kg_client.py` — 완료

`KGClient.get_candidates(pattern)` 구현 완료. `kg_rca/outputs/hypotheses.json`의 `questions[].hypotheses[]`를 `GraphRAGCandidate`(state.py) 모양으로 매핑한다.

| hypotheses.json 필드 | GraphRAGCandidate 필드 |
|---|---|
| `path.cause` | `cause` |
| `path.failure_mode` | `failure_mode` |
| `path.step` | `step` |
| `path.signature` | `signature` |
| `route` | `route` |
| `tier` | `tier` |
| `path.evidence_label` | `evidence_label` |
| `path.evidence` | `evidence` |
| `verification.fab_table` | `fab_table` |
| `verification.direction` | `direction` |
| `score.occurrence_prior` | `occurrence_prior` |
| `score.confidence` | `confidence` |
| `sentence` | `sentence` |

실제 데이터로 검증됨(2026-07-13): `Donut`처럼 미매핑 패턴은 `candidates=[]`로 정상 처리. `state.py`의 `Route` 타입에 `"signature"`도 추가 완료.

> 가설 건수는 kg_rca 재생성마다 바뀐다 — 하드코딩하지 말 것. 최근 확인값(참고용): Center 244 / Edge-Ring 74 / Scratch 50.

### ✅ 스텝 2. `mcp_client/client.py` — 완료

`MultiServerMCPClient`로 `secsgem-mcp`를 stdio 연결, 9개 메서드 전부 바인딩. 실제 서버로 검증 완료 — `get_lot_history`를 호출해 받은 6단계(LITHO/ETCH/DEPO/CMP/CLEAN/EDS) 결과가 `fab.db` 직접 조회 결과와 100% 일치 확인.

구현 중 발견해서 고친 버그 2개(둘 다 실제로 재현·수정·재검증함):
1. **`_as_dict`가 실제 MCP 응답 모양을 못 받음** — `langchain-mcp-adapters`는 구조화 출력이 없으면 MCP 표준 콘텐츠 블록 리스트(`[{"type": "text", "text": "<json>"}]`)를 그대로 돌려주는데, `dict`/`str`만 처리하고 있었음. 텍스트 블록을 파싱하도록 수정.
2. **`"command": "python"`이 PATH에 뭐가 잡히느냐에 따라 흔들림** — PATH 순서상 프로젝트 venv가 아닌 다른 파이썬이 먼저 잡히면 `fastmcp` 못 찾고 죽음. `sys.executable`로 고정. 겸사겸사 `env`도 통째로 안 갈아치우고 부모 환경에 `PYTHONPATH`/`FAB_DB`만 덧붙이게 수정(Windows에서 env 통째 교체 시 `SystemRoot` 등이 빠져 불안정해질 수 있음).

### ✅ 스텝 3. `nodes/hypothesis.py` — 완료 (Walking Skeleton, 단순화 3곳 포함)

`_verify_candidate`(tier별 MCP 호출 분기) + `_verify_unit`(검증단위 하나당 MCP 호출 묶음) + `build_hypotheses`(그룹의 candidate 전체 순회) 구조로 구현. 팀 결정이 필요하다고 했던 3가지는 전부 **가장 단순한 선택으로 하드코딩**하고 코드에 `# 결정①/②/③` 주석으로 표시해뒀다(§5에 상세, 나중에 팀과 다시 짤 지점):

- **결정①(MCP 호출 단위)**: 원래 "가설 단위로 단순하게" 짰다가, 실제로 Center 244건으로 돌려보니 **타임아웃**이 났다(§5에서 걱정했던 게 실측으로 확인됨). 그래서 `(step, evidence_label, evidence)`가 같으면 결과를 재사용하는 캐싱(`verify_cache`)만 최소로 얹었다 — "검증 단위로 제대로 설계"까지는 아니고 응급 처치 수준.
- **결정②(route="direct" 의심 장비)**: A안 그대로 — `step=None`을 `run_commonality_analysis`에 그냥 넘긴다.
- **결정③(direction=null)**: A안 그대로 — `candidate.direction`은 아예 안 보고, `[자동]` 후보는 전부 "정상범위 이탈이면 `drift_detected=True`"로 통일 판정.

완료 기준 통과 확인(2026-03-04 배치, Center 그룹): 244개 후보 전부 처리됨, 그중 `high_film_stress`(cause) 후보가 `DEPO-03`의 `chamber_pressure`에서 실제로 정상범위(`[2.0, 3.0]`) 이탈을 잡아냄(`drift_detected=True`) — 이게 fab.db에 실제로 주입된 유일한 Center 자동판정 시나리오다.

### ✅ 스텝 4. `nodes/critic.py` — 완료

문서에 적힌 순서(①시간정합 ②반대근거 ③faithfulness ④KG메커니즘) 그대로 구현. `_check_time_consistency`는 `get_lot_timeline`으로 EDS(결함 발생) 이벤트 시각과 `maintenance_ts`를 비교한다.

완료 기준 통과 확인: 같은 배치에서 Center 244건 중 **136건 채택, 108건 기각**. 기각 사유는 반대증거 미수행/faithfulness 위반/KG 메커니즘 없음(근거없음 등급) 조합.

### ✅ 스텝 5. `graph.py`의 `_run_per_group`, `main.py` — 완료

- `_run_per_group`: `groups`를 순차 loop로 돌며 `node_fn(state, group_id, ...)` 호출, 반환된 partial state를 병합. `build_hypotheses`/`review_hypotheses`(async)와 `generate_response`(sync)를 둘 다 받아야 해서 `inspect.isawaitable`로 분기한다.
- **구현하다 발견한 구조적 문제**: `graph.py`가 원래 `lambda state: _run_per_group(state, ..., mcp)` 형태였는데, `_run_per_group`가 내부에서 `await`를 써야 하는 async 함수라 **람다로는 못 감싼다**(파이썬 람다는 `await`를 못 담음 — 람다로 감싸면 코루틴 객체만 돌아오고 실제로 실행이 안 됨). `fetch_graphrag_candidates`/`build_hypotheses`/`review_hypotheses`/`generate_response` 4개를 람다 대신 진짜 `async def` 내부함수로 바꿨다.
- `main.py`: `app_state.db`에 `cursor_state`(현재 커서 날짜 1행), `batch_group_result`(그룹별 최종 응답 JSON) 두 테이블 생성. `run_daily_batch`가 커서를 하루씩 전진시키고 그래프를 실행, 결과를 저장한다. 최초 커서 날짜는 `2026-03-04`로 하드코딩(TODO — fab.db 실제 데이터 범위 기준 시작일 정책 미정).
- **결정④(가설 참조 키)는 아직 실제로 안 부딪혔다** — 지금은 그룹의 `final_response` 전체를 그날 스냅샷으로 통째로 저장하기만 해서, 개별 가설을 `rank`나 튜플로 참조할 일이 아직 없다. 나중에 "어제 그 가설, 오늘도 같은 건가?" 같은 비교 기능이 생기면 그때 결정④가 실제로 필요해진다.

완료 기준 통과 확인: `graph.ainvoke(initial_state)`가 에러 없이 끝까지 실행됨(FastAPI 서버로 띄워서 `POST /batch/run` HTTP 호출까지는 아직 안 해봤고, 그래프 직접 호출로 확인함 — uvicorn 기동 확인은 남은 일).

### ✅ 스텝 6. `nodes/lowyield.py`, `nodes/grouper.py` — 완료

- `lowyield.py`: `wafer` 테이블을 `lot_history`(EDS 스텝)와 조인해서 `cursor_date`에 완료된 로트만 골라, 수율(정상 웨이퍼 비율)이 `LOW_YIELD_THRESHOLD = 0.8`(하드코딩, TODO) 미만인 로트를 선별. fab.db는 read-only라 MCP를 거치지 않고 직접 SQL로 접근(내부 배치 단계라 에이전트용 MCP 계약과 무관).
- `grouper.py`: 로트별 대표 패턴을 웨이퍼 다수결로 정하고, 같은 대표 패턴끼리 그룹으로 묶는다. `MIN_LOTS_PER_GROUP = 1`(하드코딩, TODO — 게이트 없음, 서브클러스터링도 안 함).

완료 기준 통과 확인: 2026-03-04 기준 `SVLOT-009` 1건이 저수율로 선별되고, `Center-2026-03-04` 그룹 1개로 묶임.

### ✅ 스텝 7. `nodes/vlm.py`, `nodes/response.py` — 완료 (Walking Skeleton, 실제 LLM 미연동)

- `vlm.py`: 실제 Qwen-VL 호출 없이, fab.db에서 `target_lot_ids`의 `wafer_id` 목록만 가져와 `pattern="Center"`를 고정으로 붙인다(`_HARDCODED_PATTERN`). 나머지 필드(`description` 등)도 "Walking Skeleton 임시값"이라고 명시된 더미값.
- `response.py`: LLM 없이 결정적 템플릿 문자열로 `summary`를 조립. UC-3(그래프RAG 후보 자체가 없는 미매핑 패턴)와 UC-2(후보는 있었지만 Critic이 전부 기각)를 구분해서 다른 문구를 낸다.

완료 기준 통과 확인: `final_response["Center-2026-03-04"]["summary"]`가 "Center 패턴 — 가설 136건 채택:"으로 시작하는 카드로 정상 생성됨.

### ✅ 스텝 8. 예외 상황 처리 — 코드는 반영됨, UC-2/UC-3 개별 테스트는 아직

- UC-3(미매핑 패턴): `graphrag.py`가 KGClient의 빈 `candidates=[]`를 그대로 전달하고, `response.py`가 이를 감지해 "원인 분석 데이터 없음" 카드로 분기하는 코드는 있다.
- UC-2(판단 불가): `critic_result.status == "insufficient_evidence"`일 때 `response.py`가 "판단 불가" 카드로 분기하는 코드도 있다.
- 이번 end-to-end 실행은 Center 패턴(매핑 있음) + 채택 136건(판단 불가 아님) 케이스라, 이 두 분기는 **코드는 존재하지만 실제로 타보지는 못했다** — 다른 패턴(9종 중 6종 미매핑)이나 전부 기각되는 그룹으로 별도 확인해볼 필요.

### ✅ 스텝 9. end-to-end 확인 — 완료

2026-03-04 배치, Center 그룹으로 ⓪~⑥ 전체를 실행해 결과 카드까지 나오는 것 확인. MVP 필수 기준 1번(Center 패턴 1개 그룹으로 ⓪~⑥ 전체가 자동 실행되어 근거 기반으로 원인 후보를 좁혀 보여줌)을 스켈레톤 수준에서 통과.

**실행 중 발견한 버그 2개**(스텝2 때 찾은 2개에 이어 추가로 발견·수정):

1. **`MultiServerMCPClient.get_tools()`가 호출마다 새 세션(=새 stdio 서브프로세스)을 만듦** — 라이브러리 자체 docstring에 "A new session will be created for each tool call"이라고 명시돼 있었다. 가설 하나 검증하는 데도 MCP를 여러 번 부르는 우리 패턴에서는 호출마다 프로세스 재기동이라 치명적으로 느려서(Center 244건 처리가 2분 넘게 걸려 타임아웃), `client.session()`으로 연결을 한 번만 열고 `load_mcp_tools(session, ...)`로 그 세션을 재사용하도록 `mcp_client/client.py`를 수정했다. 이 수정 하나로 타임아웃 나던 게 정상 완료로 바뀜.
2. **`secsgem-mcp/simulator/fab_model.py`가 Windows에서 `fab_model.yaml`을 못 읽음** — `YAML_PATH.read_text()`가 인코딩을 안 지정해서 Windows 기본 코드페이지(cp949)로 읽으려다, 파일 안 한글 주석에서 `UnicodeDecodeError`. `encoding="utf-8"`을 명시해서 수정(이 파일이 `query_telemetry`의 정상범위 조회에 쓰여서, `[자동]` 등급 검증 자체가 막혀 있었다).

### 의존관계 한눈에 (전부 완료)

```
스텝 0 ✅ → 스텝 1 ✅ ─┐
           스텝 2 ✅ ─┼─→ 스텝 3 ✅ → 스텝 4 ✅ → 스텝 5 ✅ → 스텝 9 ✅
           스텝 6 ✅ ─┘         스텝 7 ✅(하드코딩) · 스텝 8 코드는 있으나 개별 검증 남음
```

---

## 5. 아직 결정 안 된 것

### `hypothesis.py`에 임시로 반영된 단순화 — 팀과 재검토 필요 (우선순위 높음)

코드가 이미 있어서 더 이상 스텝3을 "막고" 있지는 않지만, 셋 다 가장 단순한 선택으로 하드코딩돼 있다(코드에 `# 결정①/②/③` 주석 표시). 나중에 팀원과 다시 설계할 때 이 순서로 보면 된다.

**① MCP 호출: 가설 단위 vs 검증 단위 — 실측으로 결론이 반쯤 남**
가설이 많아질수록(최근 Center 244건) 후보 하나하나마다 MCP를 부르면 중복이 심하다. `(step, evidence_label, evidence)` 기준 Center는 244건이 92개 조합으로, Scratch는 50건이 19개로, Edge-Ring은 74건이 33개로 줄어든다. **가설 단위(A안)로 실제로 짜서 돌려봤더니 타임아웃이 났다** — 그래서 지금은 검증단위 캐싱을 최소로만 넣은 상태(§4 스텝3). 즉 "A안은 이 규모에서 안 된다"는 것까지는 실측으로 확인됐고, "B안을 얼마나 제대로 설계할지"(캐시를 그룹 단위로 유지할지, MCP 호출 자체를 배치로 묶을지 등)는 여전히 열려있다. 이건 KG팀원도 `kg_rca/MCP_KG_정합성검토.md`(X3)에서 같은 문제를 지적했다.

**② `route="direct"` 후보의 의심 장비 선정 방식 — A안으로 구현, 재검토 여지 있음**
문헌이 공정을 특정 안 하는 경우(`path.step`이 `null`) — 최근 기준 Center 12건, Scratch 12건, Edge-Ring 13건. 지금은 A안(그냥 `step=None`으로 `run_commonality_analysis` 호출)으로 구현돼 있다. B)이런 후보는 의심 장비 좁히기 자체를 생략 C)1차 구현 범위에서 제외 — 둘 다 아직 시도 안 해봄. A안이 신호를 얼마나 흐리는지 정량적으로는 아직 안 봤다.

**③ `direction: null`인 `[자동]` 후보의 판정 규칙 — A안으로 구현**
"어느 방향이 이상인지" 문헌에 안 나온 경우(최근 기준 Center 1건, Edge-Ring 3건). A안(방향 무시, 정상범위 이탈이면 `drift_detected=True`)으로 구현 완료. 건수가 적어서(4건) 지금 규모에선 큰 영향 없음 — B)`[반자동]`처럼 사람 판단으로 넘기기 C)통계적 변화점 탐지 대체는 아직 안 해봄.

### `main.py`/`app_state.db` 설계에서 아직 안 부딪힌 것

**④** `app_state.db`에 가설을 저장할 때 참조 키를 `rank`가 아니라 `(step, failure_mode, cause, evidence)` 튜플로 쓸지 — kg_rca 재생성마다 `rank`가 가리키는 대상이 바뀌므로 사실상 필수. 단, 지금 구현(§4 스텝5)은 `final_response` 전체를 그날 스냅샷으로 통째로 저장하기만 해서 개별 가설 참조가 아직 필요 없었다 — "어제 그 가설, 오늘도 같은가"류 비교 기능이 생기면 그때 실제로 결정해야 한다.

### 우리 스켈레톤과 무관하게 남은 것

**⑤** 저수율 임계값, 그룹 팬아웃 방식(순차 loop vs LangGraph Send API), 정비기록 마스킹 — 스텝3·6에서 가장 단순한 기본값으로 가정하고 TODO 표시.
**⑥** `semiconductor_proposal.md` 제목의 "multi-agent" 표현을 바꿀지 — 문서 작업, 코드와 무관.

### KG팀원이 정리해 둔, 우리 쪽에도 영향 있는 결정 (`kg_rca/MCP_KG_정합성검토.md` §3)

**⑦ [Q1]** 파라미터 어휘의 정본을 어디로 할지 — fab.db 시뮬레이터에 파라미터를 추가할지, MCP 문서 예시를 KG의 20종에 맞출지. 아직 답은 안 나왔지만, KG팀원이 임시 완화책을 하나 넣었다 — `6_ask_graphrag.py`에 `[근거없음]` 가설을 `mapping_table.yaml`(fab 시나리오)과 유사도 매칭해서, 맞으면 `[자동]`으로 승격시키는 로직(`apply_mapping_fill`)이 추가됨. 실제로 Scratch `[자동]` 건수가 3→10건으로 늘었다(2026-07-13 확인). 다만 매칭 대상이 `mapping_table.yaml`의 9개 항목뿐이라 전체 커버리지 문제가 풀린 건 아니고, cause 문자열 자체가 통일되는 것도 아니라서(§Q1 근본 질문은 그대로) — 완화책이지 정답 확정은 아니다.
**⑧ [Q2]** MCP `mapping_table.yaml`의 클래스×원인 매핑표를 "정답 시나리오"로 볼지 "예시"로만 볼지.
**⑨ [Q6]** KG 조회 방식 — 지금처럼 배치 생성된 `hypotheses.json`을 읽을지, 패턴 단건 질의나 Neo4j 직접 질의로 바꿀지. 스켈레톤은 배치 방식을 전제하고 있어서, 바뀌면 `kg_client.py` 재작성 필요.

### 참고로만 알아둘 것 (차단급 아님)

- Scratch는 파라미터 어휘 불일치로 `[자동]` 판정 가능한 후보가 원래 적었는데, 위 ⑦의 매핑 완화책 이후 3건→10건으로 늘었다 — 그래도 다른 패턴(Center 36건)보다는 여전히 적다.
- CLEAN 공정은 KG에 근거 문헌이 없어서 후보 자체가 안 나온다.
- `Alarm` evidence 노드가 KG에 없어서, 알람 관련 근거는 Critic의 "KG 메커니즘 연결" 체크를 항상 통과 못 한다.
- **알람 관련 정리(0713 회의에서 나온 질문)**: KG는 Alarm evidence 타입이 없어서 Hypothesis가 알람을 근거로 가설을 만드는 일은 구조적으로 없다. 알람을 쓰려면 Critic 쪽에 로직을 추가하는 게 맞는 방향인데, **`get_lot_timeline`의 알람 통합은 지금 데이터로는 항상 비어있다** — 그 SQL이 `alarm.lot_id = ?`로 조인하는데, 실제 `fab.db`엔 알람 131건 전부 `lot_id`가 `NULL`이다(시뮬레이터의 `alarm_lot_resolver()`가 "장비 유휴 중 알람"으로 전부 분류해버림). 그래서 `get_lot_timeline`으로는 알람을 볼 수 없고, **알람을 실제로 조회하려면 `get_alarm_history(equipment_id, time_range)`가 유일한 통로**다(lot_id가 아니라 equipment_id로 직접 조회하므로). 즉 두 툴은 기능이 안 겹친다 — `get_alarm_history`는 대체 불가.
- Maintenance id와 fab `parts` 필드(자유 텍스트) 자동 대조 불가 — `[반자동]` 정의와 원래 일치하는 부분이라 문제라기보다는 특성.
- `hypotheses.json`의 가설마다 `mapping` 필드가 새로 생겼다(위 ⑦ 매핑 완화책의 부산물) — 매칭된 fab 시나리오 정보(점수·확률·인용문헌)가 들어있다. 매칭 안 됐으면 `null`. `kg_client.py`는 아직 이 필드를 안 읽는다 — 나중에 "이 근거가 fab 시나리오와 이만큼 비슷해서 자동 승격됐다"를 화면에 보여주고 싶어지면 그때 `GraphRAGCandidate`에 필드 추가하면 된다. 지금 당장은 불필요.

---

## 6. 막히면 볼 문서

| 궁금한 것 | 어디를 보면 되는가 |
|---|---|
| KG 스키마 전체 명세 (정본, v2.3) | `kg_rca/schema_v2.md` |
| KG 진행 상황·남은 문제·다음 액션 (정본, KG팀원 작성) | `kg_rca/STATUS.md` |
| KG가 실제로 뽑은 가설 원본(건수는 계속 바뀜) | `kg_rca/outputs/hypotheses.json` |
| MCP 9개 함수 상세 계약 | `SesacLine_SemiRCA/secsgem-mcp/README.md` |
| MCP 시나리오(A0~E4) 최신판 | `kg_rca/SECS GEM MCP 문서_v0 1.md` |
| **KG 출력 ↔ MCP 문서 정합성 검토 (X1~X10, Q1~Q7) — KG팀원 작성, §5 참고** | `kg_rca/MCP_KG_정합성검토.md` |
| fab.db 표·파라미터 전체 정리 | `personalspace/0710 work/metadata.md` |
| RCAState(데이터가 오가는 모양) 전체 정의 | `personalspace/0708 work/산출물_데이터모델설계.md` §3 |
| KG cause 어휘와 fab.db cause 어휘가 왜 안 맞는지 | `personalspace/0711 work/kg_mapping_vocabulary.md` |
| 0711에 나눈 질문/답 전체(노드화, agent vs node 등) | `personalspace/0711 work/qna_0711.md` |

---

## 7. 진행 로그 (날짜순, 간단히)

- **0711**: 문서 최초 작성. 노드화 결정(Hypothesis/Critic을 룰베이스 함수로) 배경 정리, 건드릴 순서(스텝0~9) 최초 확정.
- **0713 오전**: KG가 v2.3(형상 레이어)까지 진행됨 확인, 문서 숫자 최신화. `kg_rca`/`secsgem-mcp`를 `SesacLine_SemiRCA/` 하위로 이동(공동작업 목적), 각자의 `.git`은 팀 결정으로 삭제. `.gitignore`·`pyproject.toml`을 루트로 통합. `state.py`(`Route`에 `signature` 추가), `kg_client.py`(스텝1) 구현·검증, `mcp_client.py`(스텝2) 구현.
- **0713 오후**: venv 설치 완료. `mcp_client.py`를 실제 서버로 검증하다 버그 2개 발견·수정(`_as_dict` 콘텐츠 블록 미처리, `command` PATH 의존) — 수정 후 `get_lot_history` 결과가 `fab.db` 직접 조회와 100% 일치 확인. 스텝3 착수 전 결정 필요 사항 3가지 정리(§5).
- **0713 저녁**: KG팀원이 `[근거없음]` 가설을 `mapping_table.yaml`과 유사도 매칭해 조건부로 `[자동]` 승격시키는 `apply_mapping_fill` 로직을 `6_ask_graphrag.py`에 추가한 것 확인 — Scratch `[자동]` 건수 3→10건으로 개선(Q1 완화책, §5 ⑦). `hypotheses.json`에 `mapping` 필드 신규 추가됨(현재 `kg_client.py` 미사용, 필요 시 나중에 반영).
- **0713 밤**: 팀 결정이 필요하다던 스텝3(`hypothesis.py`)을 포함해 **나머지 전체(스텝3~9)를 Walking Skeleton으로 구현**. 3가지 결정은 전부 가장 단순한 선택으로 하드코딩(§5, §4 스텝3). 구현한 파일: `nodes/lowyield.py`(fab.db 직접 SQL 집계), `nodes/grouper.py`(다수결 그룹화), `nodes/vlm.py`(Center 하드코딩), `nodes/graphrag.py`(kg_client 호출 묶기), `nodes/hypothesis.py`(검증단위 캐싱 포함), `nodes/critic.py`(4규칙), `nodes/response.py`(결정적 템플릿), `graph.py`(`_run_per_group` 구현 + 람다 4개를 실제 `async def`로 교체 — 람다는 `await`를 못 담아서 원래 구조로는 실행 자체가 안 됐음), `main.py`(`app_state.db` 스키마 생성 + `run_daily_batch`/`get_batch_results`).
  실제로 2026-03-04 배치로 end-to-end 돌리는 과정에서 버그 2개를 더 발견·수정함(스텝2 때 찾은 2개에 이어 총 4개째, 5개째):
  1. `MultiServerMCPClient.get_tools()`가 **호출마다 새 stdio 서브프로세스를 띄우는 설계**(라이브러리 docstring에 명시)라, 244건 가설 검증 중 타임아웃 발생 → `client.session()`으로 연결을 한 번만 열고 재사용하도록 `mcp_client/client.py` 재구성. 이 수정 하나로 타임아웃이 정상 완료로 바뀜.
  2. `secsgem-mcp/simulator/fab_model.py`가 `fab_model.yaml`을 인코딩 지정 없이 읽어서 Windows(cp949)에서 한글 주석 때문에 `UnicodeDecodeError` — `encoding="utf-8"` 명시로 수정.
  최종 결과: Center 그룹 1개, 후보 244건 → 채택 136건/기각 108건, 그중 fab.db에 실제로 주입된 `Center/DEPO/chamber_pressure` drift를 정확히 잡아낸 것까지 확인(§4 스텝9). 스텝8(UC-2/UC-3 예외 카드)은 코드는 있으나 이번 실행에서 실제로 타보진 못해서 별도 확인이 남아있음.

---

## 8. 컴포넌트별 개선 목록 (Walking Skeleton → 실제 구현)

§5가 "착수 전 결정할 것" 위주였다면, 이 표는 **지금 코드가 정확히 뭘 안 하고 있는지**를 컴포넌트별로 모은 것이다. 팀원과 다시 짤 때 체크리스트로 쓰면 된다.

### 8.1 VLM (① `nodes/vlm.py`)

| # | 지금 상태 | 실제로 필요한 것 |
|---|---|---|
| 1 | `pattern="Center"` 완전 하드코딩. 실제 모델 호출 자체가 없음 | Qwen3-VL-4B-Instruct 연동. `semiconductor_proposal.md` §7 결정: **fine-tuning이 목표, few-shot은 차선**(병행) |
| 2 | `mcp.get_wafer_map(lot_id, wafer_id)`를 아예 안 부르고, fab.db `wafer` 테이블에서 SQL로 `wafer_id` 목록만 직접 읽음 | 실제로는 MCP 도구로 이미지(base64 PNG, 라벨 미포함)를 받아와서 모델에 넣어야 함 — 지금은 이미지 자체를 한 번도 안 읽는다 |
| 3 | 출력이 `pattern` 하나뿐(나머지 필드는 고정 더미 문자열) | `{pattern, spatial, description, severity, confidence, ambiguity}` 6개 필드를 실제로 생성해야 함. `description`/`confidence`/`ambiguity`는 GraphRAG 매핑 없는 6/9패턴에서 사용자에게 그대로 노출되는 필드라 특히 중요(`qna_0711.md` Q7) |
| 4 | 프롬프트(system/user 메시지) 없음 | instruction-tuned 모델이라 학습 때 쓴 것과 **정확히 동일한** system/user 문자열이 필요(`qna_0708.md` Q3) — VLM 파인튜닝 담당 팀원에게서 원문 그대로 받아야 함 |
| 5 | 근거 없음(모델 자체가 없으니) | 왜 사전학습 모델을 그냥 못 쓰는지 정량 근거: Cosmos Reason 리포트(zero-shot 14.37%→SFT 96.8%), WaferSAGE(Qwen3-4B 기준 base 4.0→SFT 6.484, LLM-Judge) — `document/fine-tunning/` 참고 |
| 6 | 팀원이 이미 실제 VLM 출력 샘플을 만들어 둠(`personalspace/0707 work/qna.md` Q7, `wm811k_929` 예시) — LLaVA류 데이터 포맷 + `<think>` 안에 `radius_mean`/`edge_ratio`/`cluster_count` 등 정밀 수치 | 이 수치가 VLM이 즉흥적으로 낸 게 아니라 별도 결정적 피처 추출 결과일 가능성이 높음 — 그 계산 코드가 있는지, `<think>` 자연어 대신 구조화 `features` 필드로 노출 가능한지 팀원에게 확인 필요. **코드/데이터는 이 저장소엔 없음**, 표준화도 아직 안 끝남 |
| 7 | 온프레미스 배포 목표만 확정, 인프라(GPU 사양·클라우드 여부) 미문서화 | 배포 환경 결정 필요 |

### 8.2 Hypothesis (④ `nodes/hypothesis.py`)

| # | 지금 상태 | 실제로 필요한 것 |
|---|---|---|
| 1 | `verify_cache`가 `(step, evidence_label, evidence)` 키로만 캐싱 — 응급 처치 | 검증 단위를 제대로 설계(§5 ①). Q5(가설 단위 vs 검증 단위)와 직결 |
| 2 | `_top_equipment`가 commonality 1등을 임계값 없이 무조건 채택 | 비율이 낮으면(예: 30% 미만) "의심 장비 특정 실패"로 처리하는 하한선 필요 |
| 3 | `_detect_drift`가 `candidate["direction"]`을 아예 무시(§5 ③) | 문헌이 제시한 방향(high/low)과 실제 이탈 방향이 일치하는지까지 봐야 진짜 지지 증거 |
| 4 | `_group_time_range`가 그룹의 **첫 로트 하나만** 봄 | 그룹 내 모든 로트의 처리 구간을 합쳐서(또는 대표값 선정 기준을 정해서) 시간창을 잡아야 함 |
| 5 | Maintenance 분기: 시간대 안에 정비 기록이 "있기만 하면" `maintenance_hit=True` — `parts` 텍스트가 candidate의 cause와 관련 있는지 전혀 확인 안 함 | 키워드 매칭이라도 필요(`kg_rca/MCP_KG_정합성검토.md` X7 — Maintenance id ↔ fab `parts` 자동 대조 불가 문제와 같은 이슈) |
| 6 | Recipe 분기: MCP 호출 자체를 안 하고 `recipe_match=None` 고정 | KG에 기대 레시피가 없다는 스키마 한계는 맞지만, 최소한 `get_lot_history`로 실제 사용된 recipe_id는 조회해서 사람이 볼 수 있게는 해야 함(지금은 그 조회조차 안 함) |
| 7 | `get_alarm_history` 어디서도 안 씀 | 알람은 Critic 쪽에 추가하는 게 맞다고 결론 냄(8.3 참고) — Hypothesis에서는 손 안 대도 됨 |
| 8 | `detect_change_points` 안 씀 | 지금은 "정상범위 벗어난 포인트 있음=drift"로 판정. 실제 드리프트 시작점을 잡으려면 이 툴 필요(변화점 탐지) |
| 9 | `route="direct"` 후보 처리(§5 ②) | 그대로 |

### 8.3 Critic (⑤ `nodes/critic.py`)

| # | 지금 상태 | 실제로 필요한 것 |
|---|---|---|
| 1 | **`_check_time_consistency`가 `maintenance_ts`가 있을 때만 작동** — Parameter(`[자동]`) 후보는 `maintenance_ts`가 절대 안 채워지므로 **시간정합 검사를 아예 안 받고 무조건 통과**함(오늘 코드 재검토 중 발견) | "①시간정합" 규칙을 drift(Parameter) 후보에도 적용할 방법 필요 — 예: `query_telemetry`가 이탈을 감지한 첫 시점과 결함 발생 시점 비교(`detect_change_points`와 연결하면 자연스러움) |
| 2 | `_check_faithfulness`가 사실상 자리표시자 — `[자동]`이고 `drift_detected is None`인 경우만 체크 | 진짜 faithfulness(응답 카드 문장이 실제 조회값과 일치하는지)는 ⑥ 응답생성이 자연어를 실제로 만들기 전까진 의미가 없음 — 8.4와 함께 재설계 |
| 3 | 그룹의 **첫 로트만** 시간정합 검사에 씀(hypothesis.py와 같은 단순화) | 그룹 전체 로트를 고려하는 기준 필요 |
| 4 | 알람 기반 체크가 없음 | `get_alarm_history(equipment_id, time_range)`로 "의심 장비에 결함 시점 근처 알람이 있었나" 추가 가능 — 단 fab.db의 알람은 대부분 배경 노이즈로 설계돼 있어(방금 회의에서 확인) 지지 증거보다는 "혹시 이게 교란인지" 걸러내는 회의적 체크로 쓰는 게 맞음 |
| 5 | 4규칙 다 통과하면 그냥 채택 — 규칙 간 우선순위/점수화 없음 | 지금은 이진 accept/reject뿐이라, 나중에 "얼마나 확실한 가설인가" 랭킹이 필요해지면 규칙별 가중치 설계 필요 |

### 8.4 LLM — 응답생성 (⑥ `nodes/response.py`)

| # | 지금 상태 | 실제로 필요한 것 |
|---|---|---|
| 1 | LLM 호출 없음, 결정적 템플릿 문자열(`f"- {cause} (등급: {tier}, 의심 장비: {equipment})"`) | `산출물_mvp설계서.md`상 VLM(Qwen-VL-4B-Instruct)이 응답생성까지 겸용하기로 돼 있음 — 실제 자연어 합성 붙여야 함 |
| 2 | **KG가 만들어 둔 `sentence`(사람이 읽을 가설 문장)와 `provenance`(인용 근거·문헌)가 파이프라인 중간에서 사라짐** — `state.py`의 `Hypothesis` TypedDict에 `sentence`/`provenance` 필드 자체가 없음(오늘 재확인). `hypothesis.py`가 `GraphRAGCandidate`에서 `cause`/`tier`/`equipment`/`evidence`만 뽑고 `sentence`는 안 옮김 | 응답 카드에 "왜 이 원인이 의심되는지"(KG 문장 + 인용 근거)를 보여주려면 `Hypothesis`에 `sentence`/`provenance` 필드 추가하고 `build_hypotheses`에서 그대로 옮겨야 함 — 지금 구조로는 절대 화면에 못 보여줌 |
| 3 | UC-1/UC-2/UC-3 카드 문구가 전부 고정 템플릿 1개씩 | 실제 서비스라면 사람이 읽었을 때 자연스러운 문장이 필요 — 이 부분이 LLM이 실제로 필요한 지점 |
| 4 | `mapping` 필드(kg_rca의 fab 시나리오 매칭 정보, §5 참고)도 응답에 노출 안 됨 | "이 근거가 fab 시나리오와 이만큼 비슷해서 자동 승격됐다" 같은 설명에 쓰면 좋음(선택사항) |

### 8.5 E2E 평가

| # | 지금 상태 | 실제로 필요한 것 |
|---|---|---|
| 1 | 수동으로 딱 1번 실행(2026-03-04, Center 그룹)해서 눈으로 결과 확인한 게 전부 | 반복 가능한 평가 스크립트 필요(여러 cursor_date, 3개 매핑 패턴 전부) |
| 2 | UC-2(판단불가)·UC-3(미매핑 패턴) 카드는 코드는 있으나 한 번도 실제로 안 타봄 | Edge-Ring/Scratch 그룹, 그리고 전부 기각되는 그룹을 별도로 만들어서 확인 |
| 3 | `secsgem-mcp/eval/metrics.py`의 `rca_topk_accuracy`가 cause 문자열을 직접 비교해서, kg_rca 출력을 그대로 넣으면 0%가 나오는 문제(예전부터 알려진 이슈) — **아직 손 안 댐** | 평가 파이프라인을 실제로 돌리기 전에 반드시 해결 필요. 평가 기준을 cause 문자열이 아니라 `(step, evidence, tier)` 같은 구조화 키로 바꾸는 방향이 유력 |
| 4 | `secsgem-mcp/datasets/ground_truth/`(정답 카드, 평가 전용)를 우리 파이프라인이 아직 한 번도 참조 안 함 | 배치 실행 결과를 ground truth와 자동 대조하는 평가 스크립트 필요 |
| 5 | `app_state.db`에 같은 그룹을 재실행하면 어떻게 되는지(멱등성) 테스트 안 함 | `INSERT OR REPLACE`로 짜여 있어 덮어쓰기는 되지만, "어제와 오늘의 같은 가설을 비교"하는 로직은 없음(§5 ④ 참고) |
| 6 | uvicorn으로 실제 서버 기동 + HTTP 경로(`/batch/run`, `/batch/results`) 확인 안 됨 | `README.md` "남은 일" 참고 — 그래프 직접 호출로만 검증됨 |
| 7 | 성능(응답 시간) 측정 안 됨 — 세션 재사용 버그 고친 뒤로는 빨라졌지만 정확한 수치 없음 | 그룹당/패턴당 소요 시간 벤치마크 필요, 특히 검증단위 dedup(§5 ①) 전후 비교 |
