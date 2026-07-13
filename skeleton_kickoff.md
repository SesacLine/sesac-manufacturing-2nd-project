# 스켈레톤 구축 Kickoff (0711 작성, 0713 최신화)

이 문서는 Hypothesis/Critic 연결 레이어(지금 `secsgem-mcp/agent/hypothesis_plan.py`·`critic.py`에 18~27줄짜리 의사코드로만 있는 부분)의 스켈레톤 코드를 짜기 전에, **무엇을 어느 순서로 건드릴지**와 **KG·정비데이터 쪽 전문용어**를 팀 전체가 같은 이해로 시작할 수 있게 정리한 것이다. 아직 코드는 짜지 않았고, 이 문서는 착수 전 정리 단계다.

> **0713 최신화 노트**: 0711 작성 이후 KG팀원(kg_rca)이 v2.3(형상 레이어 추가)까지 진행했고, MCP 문서와의 자체 정합성 검토(`kg_rca/MCP_KG_정합성검토.md`)도 마쳤다. 이 문서의 숫자·결론 중 구버전(0711) 스냅샷 기준으로 쓰인 부분을 최신 상태로 고쳤다 — 바뀐 지점은 §8에 모아뒀다.

---

## 1. 지금 우리가 가진 것 — 현황판

세 조각이 이미 따로따로 완성돼 있다. 오늘 할 일은 이 세 조각을 잇는 코드를 만드는 것이다.

| 조각 | 상태 | 위치 |
|---|---|---|
| KG(지식그래프) 원인 탐색 | 완성, 계속 갱신 중(v2.3). 문헌 5편에서 가설 **381건**(2026-07-12 기준, `kg_rca/STATUS.md` §1) 추출. 재생성될 때마다 건수가 바뀌므로 정확한 값은 항상 `STATUS.md`에서 확인 | `SesacLine_SemiRCA/kg_rca/` (0713부터 평범한 하위 폴더, 자체 `.git` 삭제됨) |
| MCP 서버(9개 조회 도구) | 완성. fab 데이터를 조회하는 9개 함수가 이미 다 구현돼 있다 | `SesacLine_SemiRCA/secsgem-mcp/` (0713부터 평범한 하위 폴더, 자체 `.git` 삭제됨) |
| 이 둘을 잇는 코드(Hypothesis/Critic) | **스켈레톤 완료, 실제 로직은 전부 `NotImplementedError`** — 함수 시그니처·타입·데이터 흐름만 잡혀 있음 | `SesacLine_SemiRCA/backend/` (통합 레포, 오늘 신설) |

> **0713 추가 갱신**: `kg_rca`, `secsgem-mcp`(구 `dataset/secsgem_mcp/secsgem-mcp-main`)를 실제로 `SesacLine_SemiRCA/` 밑으로 옮겼다(공동작업 편하게 하려는 목적). 아래 문서의 경로 참조도 이에 맞춰 갱신했다. `.env`/`.env_example`도 `./kg_rca`, `./secsgem-mcp` 상대경로로 이미 맞춰져 있고, `kg_client.py`/`mcp_client.py` 양쪽 다 새 경로로 동작 확인함(§8.5). 두 폴더 각자 갖고 있던 `.git`은 팀 결정으로 삭제했다 — `SesacLine_SemiRCA`를 git init하면 안의 파일까지 그대로 하나의 히스토리로 잡힌다(각 폴더의 이전 커밋 기록은 로컬에 더 이상 없음).

KG는 "이 결함 패턴이면 일반적으로 어떤 원인이 있을 수 있는지"를 문헌에서 찾아주고, MCP 서버는 "이번에 실제로 문제가 된 로트가 어느 장비를 지났고 그 장비에서 무슨 일이 있었는지"를 조회해준다. Hypothesis 노드는 KG가 준 원인 후보 하나하나를 MCP 서버로 실제로 확인해보는 역할이고, Critic 노드는 그 확인 결과가 믿을 만한지 다시 한번 점검하는 역할이다.

Hypothesis·Critic은 자유롭게 판단하는 LLM이 아니라 **정해진 규칙대로 동작하는 함수**로 만든다(2026-07-09 팀 결정). 이 점이 스켈레톤의 인터페이스를 단순하게 만들어준다 — "이럴 땐 이 함수를 부른다"는 규칙표만 정확히 세우면 되고, LLM이 알아서 판단하게 맡기는 부분이 없다.

---

## 2. KG 쪽 전문용어 풀어쓰기

### 2.1 "노드"와 "관계"란

그래프는 점(노드)과 그 점들을 잇는 선(관계)으로 이루어진다. 노드 하나는 구체적인 개념 하나(예: "Edge-Ring이라는 결함 패턴 하나", "ETCH라는 공정 하나")를 가리키고, 관계 하나는 두 노드 사이의 연결(예: "이 결함 패턴은 이 공정에서 나타난다")을 나타낸다. 우리 시스템에서 그래프를 읽는다는 건, 결함 패턴 노드에서 출발해서 관계를 따라가며 원인 노드까지 도달하는 것이다.

### 2.2 우리 그래프에 있는 노드 8종류 (0713: `SpatialSignature` 추가, v2.3)

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

`DefectPattern`·`SpatialSignature`·`ProcessStep`·`Parameter`는 **미리 정해진 목록 안에서만 고른다.** 나머지 넷(`FailureMode`·`Cause`·`Maintenance`·`Recipe`)은 문헌을 읽고 AI가 자동으로 새로 만들어낸 것이다. 그래서 이 넷은 문헌마다, 실행마다 다른 이름으로 나올 수 있다.

`SpatialSignature`가 왜 필요한가: 문헌 중에는 "패턴 이름"이 아니라 "형상"으로 원인을 서술하는 것들이 있다(예: "링 모양 결함은 보통 세정 공정 문제를 반영한다"). 이걸 억지로 `Center`/`Edge-Ring`/`Scratch` 중 하나에 끼워 맞추지 않고 형상 층위에 그대로 담아두는 노드다. 또한 VLM이 3종 밖의 패턴(예: `Donut`)을 만났을 때도 "형상만 보고" 가설 경로를 탈 수 있게 해주는 **미지 패턴 대응의 발판**이기도 하다.

### 2.3 노드를 잇는 관계 7종류 (0713: `HAS_SIGNATURE`/`FORMS_IN` 추가, v2.3)

| 관계 이름 | 어디서 어디로 | 뜻 |
|---|---|---|
| `ARISES_IN` | 결함패턴 → 공정단계 | 이 결함 패턴이 어느 공정에서 나타나는가 |
| `OCCURS_IN` | 고장모드 → 공정단계 | 이 고장이 어느 공정에서 발생하는가 |
| `CAUSED_BY` | 고장모드 → 원인 | 이 고장의 원인이 무엇인가 |
| `VERIFIED_BY` | 원인 → 증거 | 이 원인을 어떤 데이터로 확인할 수 있는가 |
| `ATTRIBUTED_TO` | 결함패턴 → 원인 | 공정을 특정할 수 없을 때, 결함 패턴에서 원인으로 바로 연결 |
| `HAS_SIGNATURE` | 결함패턴 → 형상시그니처 | 이 패턴은 어떤 형상으로 정의되는가 (시드에서 결정적으로 연결, AI 추출 아님) |
| `FORMS_IN` | 형상시그니처 → 공정단계 | 이 형상은 주로 어느 공정에서 생기는가 |

가설 하나는 이 관계들을 따라간 경로 하나다. 예를 들어 "`Edge-Ring` 결함은 → `ETCH` 공정에서 → `incorrect_etch_rate`라는 고장이 → `improper_maintenance`라는 원인으로 → `chamber_wet_clean`이라는 정비 기록으로 확인 가능하다"가 가설 하나다. `HAS_SIGNATURE`/`FORMS_IN`을 타는 경로(형상 경유, route=`signature`)도 있지만, 지금 데이터에서는 같은 결론에 도달하는 공정 경유(route=`step`) 경로가 항상 대표로 남아 실제 출력에는 0건이다(§8.2 참고).

### 2.4 검증등급 — `[자동]` / `[반자동]` / `[근거없음]`

가설마다 증거(`Evidence`)의 종류가 다르고, 종류에 따라 확인 가능한 정도가 다르다.

| 등급 | 증거 종류 | 실제로 무슨 일이 일어나는가 |
|---|---|---|
| `[자동]` | `Parameter`(센서값) | 센서값에는 "정상범위"라는 숫자 기준이 있다. 값이 그 범위를 벗어났는지 계산만 하면 되므로, 사람 없이 시스템이 채택/기각까지 결론 낼 수 있다 |
| `[반자동]` | `Maintenance`(정비기록) 또는 `Recipe`(레시피) | 데이터는 조회할 수 있지만 "이 값이면 이상하다"는 기준이 없다. 예를 들어 정비 기록은 "언제 무엇을 교체했다"는 자유 텍스트라서, 그게 이 결함과 관련 있는 정비인지는 사람이 읽고 판단해야 한다 |
| `[근거없음]` | 없음 | 문헌에만 나오는 원인이고, fab 데이터로 확인할 방법 자체가 없다 |

이 등급 구분이 4장(건드리는 순서)에서 그대로 "어떤 MCP 함수를 부를지"를 결정하는 기준이 된다.

---

## 3. 정비 데이터(fab.db) 쪽 용어 풀어쓰기

fab.db는 실제 공장 데이터가 아니라, 시뮬레이터가 미리 만들어 둔 가상의 공장 운영 기록이다. 표가 7개 있는데, 이 중 정비 데이터와 직접 관련된 것부터 본다.

| 표 이름 | 무엇이 들어있나 | 언제 한 줄씩 생기나 |
|---|---|---|
| `lot_history` | 웨이퍼 묶음(로트) 하나가 어느 장비를, 몇 시부터 몇 시까지 지났는지 | 로트 하나가 공정 6단계를 지날 때마다 (로트당 6줄) |
| `telemetry` | 장비가 계속 내보내는 센서 측정값 | 2시간에 한 번씩, 장비가 살아있는 한 계속 |
| `maintenance` | 장비를 정비한 기록(정기정비 또는 돌발정비, 교체한 부품) | 정기 주기마다, 또는 고장 났을 때 |
| `alarm` | 장비에서 울린 경보 | 확률적으로 발생, 또는 특정 상황에서 발생 |
| `metric_series` | 장비별 하루 단위 수율 집계 | 매일 |
| `event_log` | `maintenance`와 같은 사건을 더 뭉뚱그려서 기록한 것 | `maintenance`와 같은 시각 |
| `wafer` | 웨이퍼 한 장의 최종 검사 결과(양품/불량, 불량 위치) | 로트가 마지막 공정(웨이퍼 테스트)을 끝냈을 때 |

**`maintenance`가 왜 `[반자동]`으로 취급되는지**: 이 표의 `parts` 칸에는 "무슨 부품을 교체했다"는 문장이 그대로 들어있다. `telemetry`처럼 "정상범위 몇~몇"이라는 숫자 기준이 없어서, 이 정비가 지금 조사 중인 결함과 실제로 관련 있는지는 시간(정비 시각이 결함 발생 시각보다 앞서는가)과 사람의 판단으로 확인해야 한다. `telemetry`는 숫자라서 기계적으로 비교 가능하니 `[자동]`이고, `maintenance`는 문장이라서 그게 안 되니 `[반자동]`이다 — 이게 등급을 가르는 유일한 기준이다.

### 3.1 MCP 서버 9개 함수 — 뭘 조회하는지

| 함수 이름 | 어느 표를 보는가 | 언제 부르는가 |
|---|---|---|
| `get_wafer_map` | `wafer` | 웨이퍼 이미지가 필요할 때(① VLM 단계) |
| `get_lot_history` | `lot_history` | 이 로트가 어느 장비들을 지났는지 확인할 때 |
| `run_commonality_analysis` | `lot_history` | 불량 로트들이 공통으로 지난 장비를 찾을 때 — **모든 가설에 항상 사용** |
| `get_normal_lot_ratio` | `wafer` + `lot_history` | 그 장비를 지난 정상 로트 비율을 확인할 때(반대 증거) — **모든 가설에 항상 사용** |
| `query_telemetry` | `telemetry` | 증거가 `Parameter`(센서값)일 때만 |
| `get_maintenance_history` | `maintenance` | 증거가 `Maintenance`(정비기록)일 때만 |
| `get_alarm_history` | `alarm` | 보조 확인용 |
| `detect_change_points` | `metric_series`/`event_log` | 수율이 언제부터 나빠졌는지 찾을 때 |
| `get_lot_timeline` | `lot_history` + `alarm` | 시간 순서가 맞는지 확인할 때(Critic 단계) |

---

## 4. 건드리는 순서 — 상세 스텝

`SesacLine_SemiRCA/backend/` 스켈레톤이 이미 있다. 모든 함수가 `raise NotImplementedError`로 비어있는 상태이고, 아래는 그걸 하나씩 채우는 순서다. 파일 경로는 전부 `SesacLine_SemiRCA/backend/` 기준이다.

각 스텝은 "무엇이 끝나야 다음으로 갈 수 있는가"(의존관계)와 "이게 됐다는 걸 어떻게 확인하는가"(완료 기준)를 같이 적었다. 의존관계가 없는 스텝은 팀원끼리 나눠서 동시에 진행해도 된다.

### 스텝 0. 환경 준비

1. `kg_rca`, `secsgem-mcp` 두 repo가 `SesacLine_SemiRCA/` 밑에 있는지 확인한다(`SesacLine_SemiRCA/kg_rca/`, `SesacLine_SemiRCA/secsgem-mcp/` — 0713부터 하위 폴더, 이미 있으면 스킵).
2. **가상환경 구성 (0713 갱신: `requirements.txt` 3개 산재 → 루트 `pyproject.toml` 하나로 통합됨).** `SesacLine_SemiRCA` 루트에서 아래 둘 중 하나로 진행한다.

   **방법 A — uv (권장, 빠르고 `uv.lock`으로 버전 고정됨)**
   ```powershell
   pip install uv        # uv 자체가 없으면 먼저
   uv venv                # .venv 생성
   uv sync                 # pyproject.toml 읽어서 설치 + uv.lock 생성
   .venv\Scripts\activate
   ```

   **방법 B — pip + venv (표준 도구만)**
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -e .        # pyproject.toml 기준 editable install
   ```

   기존 하위 폴더 `venv`(`secsgem-mcp/.venv` 등)는 이미 삭제했다 — 가상환경은 이제 루트 `SesacLine_SemiRCA/.venv` 하나만 쓴다. 각 하위 폴더에 따로 있던 `.gitignore`/`pyproject.toml`도 루트로 병합 완료(§8.6 참고).
3. `.env_example`을 `.env`로 복사한다 — 이미 `./kg_rca`, `./secsgem-mcp` 상대경로로 맞춰져 있어 그대로 쓰면 된다(`OPENAI_API_KEY`만 채우면 됨).
4. `secsgem-mcp/datasets/fab.db`가 이미 있는지 확인한다. 없으면 `secsgem-mcp/README.md`의 "데이터 준비" 절차를 먼저 돌려야 한다.
- **완료 기준**: `python -c "import server, backend, agent; print('OK')"`가 에러 없이 `OK`를 출력한다(= `backend`뿐 아니라 `secsgem-mcp`의 `server`/`agent` 등도 같은 가상환경에서 import된다는 뜻).
- 의존관계 없음 — 아무나 제일 먼저 해도 됨.

### 스텝 1. `graph_client/kg_client.py` — 제일 쉬움, 아무 서버도 필요 없음

`KGClient.get_candidates(pattern)`을 채운다. 할 일은 파일 하나 읽고 필드 이름만 바꾸는 것뿐이다.

- `kg_rca/outputs/hypotheses.json`을 열어서 `questions[]` 중 `pattern`이 일치하는 항목을 찾는다.
- 그 안의 `hypotheses[]` 배열 각 항목을, `GraphRAGCandidate`(state.py) 모양으로 옮긴다. 필드 대응:

| hypotheses.json 필드 | GraphRAGCandidate 필드 |
|---|---|
| `path.cause` | `cause` |
| `path.failure_mode` | `failure_mode` |
| `path.step` | `step` |
| `route` | `route` |
| `tier` | `tier` |
| `path.evidence_label` | `evidence_label` |
| `path.evidence` | `evidence` |
| `verification.fab_table` | `fab_table` |
| `verification.direction` | `direction` |
| `score.occurrence_prior` | `occurrence_prior` |
| `score.confidence` | `confidence` |
| `sentence` | `sentence` |

- **완료 기준**: `KGClient(...).get_candidates("Center")`를 부르면 결과가 나온다. 정확한 건수는 하드코딩하지 말 것 — kg_rca가 재생성될 때마다 바뀐다(0711 작성 시점 125건 → 0712 381건으로 이미 한 번 바뀜). 실행 시점의 정확한 값은 `kg_rca/STATUS.md` §1을 확인.
- 의존관계 없음. `Route` 타입에 `"signature"`가 빠져 있으니(§8.2 #1) 이 스텝에서 `state.py` 1줄도 같이 고친다.

### 스텝 2. `mcp_client/client.py` — secsgem-mcp 서버 연결

- secsgem-mcp README의 `MultiServerMCPClient` 예시를 그대로 `MCPClient.__init__`에 옮기고, `get_tools()`로 받은 도구를 이름으로 매핑해 9개 메서드가 그 도구를 호출하도록 바꾼다.
- 구현 순서 권장: `get_lot_history` → `run_commonality_analysis` → `get_normal_lot_ratio` → `query_telemetry` → `get_maintenance_history` → 나머지(`get_alarm_history`, `detect_change_points`, `get_lot_timeline`, `get_wafer_map`).
- **완료 기준**: `sqlite3 fab.db`로 아무 `lot_id` 하나를 확인한 뒤 `get_lot_history(그 lot_id)`를 호출하면 6줄짜리 결과(공정 6단계)가 온다.
- 의존관계: secsgem-mcp 서버가 로컬에서 실제로 뜰 수 있어야 한다(스텝 0-4 완료 필요).

### 스텝 3. `nodes/hypothesis.py` — 안에서도 쉬운 것부터 쪼갠다

`_verify_candidate`부터 채우고, 그 다음 `build_hypotheses`로 조립한다.

1. **`tier == "근거없음"` 분기부터** — MCP 호출이 아예 없어서 제일 쉽다. 빈 `EvidenceEntry`를 그냥 반환.
2. **`tier == "자동"`(`Parameter`) 분기** — `query_telemetry` 호출 → 반환된 값과 정상범위를 비교 → `direction`과 일치하는 방향으로 벗어났으면 `drift_detected=True`.
3. **`tier == "반자동"`(`Maintenance`/`Recipe`) 분기** — `get_maintenance_history` 또는 `get_lot_history`(레시피 비교용) 호출 → `maintenance_hit`/`recipe_match`만 채우고, 최종 판정은 하지 않는다(사람 몫).
4. **`build_hypotheses` 조립** — `run_commonality_analysis`/`get_normal_lot_ratio`를 모든 candidate에 공통으로 먼저 부르고, candidate마다 위 1~3을 적용해 `Hypothesis` 리스트를 만든다.

- **완료 기준**: Center 패턴의 `chamber_pressure`/`high` 경로(`kg_mapping_vocabulary.md`에서 실신호와 일치한다고 확인된 경로)를 넣으면 실제로 지지 증거가 나온다. 단 이 확인은 자동 후보가 지금보다 훨씬 적었던 0711 스냅샷(당시 자동 11건) 기준이라, 착수 전 최신 `hypotheses.json`(현재 Center 자동 29건, §8.1)으로 한 번 더 확인할 것.
- 의존관계: 스텝 1(candidate를 얻어야 함), 스텝 2(MCP 호출) 완료 필요. 단 1번(근거없음 분기)은 스텝 2 없이도 먼저 짤 수 있다. `route="direct"`(step=null) 후보의 suspect 장비 선정 방식과 `direction=null`인 자동 후보의 판정 규칙은 착수 전 팀 결정이 필요하다(§8.2 #2·#3).

### 스텝 4. `nodes/critic.py` — 순수 함수부터

1. **`_check_negative_evidence`, `_check_faithfulness`, `_check_kg_mechanism`** — MCP를 새로 안 부르고 `hypothesis` 안에 이미 있는 값만 보고 판단하는 순수 함수라 제일 쉽다.
2. **`_check_time_consistency`** — `get_lot_timeline` 호출이 필요해서 스텝 2가 끝나야 한다.
3. **`review_hypotheses` 조립** — 4개를 문서에 적힌 순서(①시간정합 ②반대근거 ③faithfulness ④KG메커니즘)대로 적용.

- **완료 기준**: 함정 장비(정비 시각이 결함 발생 시각보다 늦은 경우)를 넣으면 실제로 `reject`된다.
- 의존관계: 스텝 3의 `Hypothesis` 출력이 있어야 함.

### 스텝 5. `graph.py`의 `_run_per_group`, `main.py`

- `_run_per_group`: `groups` 리스트를 순회하며 `node_fn(state, group_id, ...)`을 호출하고 결과를 병합한다.
- `main.py`: `app_state.db`(커서·배치 결과 저장용, `산출물_데이터모델설계.md` §4)를 SQLite로 먼저 만들고 나서 `run_daily_batch`/`get_batch_results`를 채운다.
- **완료 기준**: `uvicorn backend.main:app --reload`로 띄운 뒤 `POST /batch/run`을 호출하면 에러 없이 응답이 온다.
- 의존관계: 스텝 1~4가 끝난 노드들을 엮는 단계라 제일 나중.

### 스텝 6. 나머지 결정적 노드(⓪ `lowyield.py`, ② `grouper.py`) — 독립적, 언제든 병렬 가능

- 스텝 1~5와 데이터 의존관계가 없다. 다른 팀원이 동시에 진행할 수 있다.
- `lowyield.py`는 `wafer.die_map` 직접 집계, `grouper.py`는 패턴별 다수결 그룹화 — 둘 다 MCP·KG 없이 fab.db 조회만으로 끝난다.

### 스텝 7. LLM 노드(① `vlm.py`, ⑥ `response.py`) — 맨 마지막

- API 키가 필요하고 호출마다 비용이 든다. 그리고 나머지 스텝이 다 끝나야 전체 파이프라인을 실제로 눈으로 확인할 수 있다.
- 그 전까지는 `vlm.py`가 고정 패턴 문자열("Center" 하나)을 하드코딩해서 반환하도록 임시로 채워두면, 스텝 5의 end-to-end 확인을 LLM 없이도 먼저 해볼 수 있다(Walking Skeleton 방식, `산출물_mvp설계서.md` §4 슬라이스 0과 같은 발상).

### 스텝 8. 예외 상황

- 채택 가능한 후보가 0개면 재시도 없이 바로 "판단 불가"(스텝 4에서 이미 `insufficient_evidence`로 처리됨, 여기선 응답 카드 문구만 확인).
- KG에 원인 매핑이 없는 패턴(9종 중 6종)이 들어오면 `graphrag.py`에서 `candidates=[]`로 두고, `response.py`에서 Hypothesis/Critic을 건너뛰어 바로 "원인 분석 데이터 없음" 카드를 만든다.

### 스텝 9. end-to-end 확인

- Center 패턴 lot_id 몇 개를 하드코딩해서 넣고, ⓪~⑥ 전체를 한 번 실행해 결과 카드가 나오는지 확인한다. 이게 되면 `산출물_mvp설계서.md` §3의 필수 기준 1번을 스켈레톤 수준에서 통과한 것이다.

### 요약 — 의존관계 한눈에

```
스텝 0 (환경)
  ├─ 스텝 1 (kg_client)        ─┐
  ├─ 스텝 2 (mcp_client)        ├─→ 스텝 3 (hypothesis) → 스텝 4 (critic) → 스텝 5 (graph/main) → 스텝 9 (e2e)
  └─ 스텝 6 (lowyield/grouper) ─┘        스텝 7 (vlm/response)는 스텝 9 직전에만 필요
```

---

## 5. 오늘 시작할 때 체크리스트

- [ ] 2장·3장 용어를 팀원 전체가 한 번씩 읽었다
- [ ] `SesacLine_SemiRCA/backend/` 스켈레톤 구조를 한 번 훑었다(README.md 참고)
- [ ] 스텝 0(환경 준비)부터 시작한다 — 로직부터 채우지 않는다
- [ ] 스텝 1·2·6은 의존관계가 없으니 팀원끼리 나눠서 동시에 시작할 수 있다
- [ ] Center 패턴 하나로 스텝 9(end-to-end)를 목표로 잡는다

---

## 6. 막히면 볼 문서

| 궁금한 것 | 어디를 보면 되는가 |
|---|---|
| KG 스키마 전체 명세 (정본, v2.3) | `kg_rca/schema_v2.md` |
| KG 진행 상황·남은 문제(P1~P6)·다음 액션 (정본, KG팀원 작성) | `kg_rca/STATUS.md` |
| KG가 실제로 뽑은 가설 원본(건수는 계속 바뀜, 0712 기준 381건) | `kg_rca/outputs/hypotheses.json` |
| MCP 9개 함수 상세 계약 | `SesacLine_SemiRCA/secsgem-mcp/README.md` |
| MCP 시나리오(A0~E4) 최신판 — 아래 baselinefile판보다 최신·상세 | `kg_rca/SECS GEM MCP 문서_v0 1.md` |
| MCP 시나리오 구버전(0711 baseline, 참고용) | `personalspace/0711 work/baselinefile/rca_secsgem_mcp.md` |
| **KG 출력 ↔ MCP 문서 정합성 검토 (X1~X10 충돌목록, Q1~Q7 결정필요사항) — KG팀원 자체 작성, §8.3 필독** | `kg_rca/MCP_KG_정합성검토.md` |
| fab.db 표·파라미터 전체 정리 | `personalspace/0710 work/metadata.md` |
| RCAState(데이터가 오가는 모양) 전체 정의 | `personalspace/0708 work/산출물_데이터모델설계.md` §3 |
| KG cause 어휘와 fab.db cause 어휘가 왜 안 맞는지 (0711 스냅샷 기준, 재검증 전) | `personalspace/0711 work/kg_mapping_vocabulary.md` |
| 오늘 나눈 질문/답 전체(노드화, agent vs node 등) | `personalspace/0711 work/qna_0711.md` |

---

## 7. 아직 팀이 결정 안 한 것 (스켈레톤은 일단 가정하고 진행, 나중에 확정되면 고친다)

**우리 쪽(스켈레톤) 결정 사항**

1. 저수율 임계값, 그룹 팬아웃 방식(순차 loop 확정적이나 규모 커지면 재검토), 정비기록 마스킹 — 스텝 3·6에서 가장 단순한 기본값으로 가정하고 진행, TODO로 표시
2. `route="direct"`(공정 미상) 후보의 suspect 장비 선정 방식 — §8.2 #2
3. `verification.direction: null`인 `[자동]` 후보의 판정 규칙 — §8.2 #3
4. `app_state.db`에 가설을 저장할 때 참조 키를 `rank`가 아니라 `(step, failure_mode, cause, evidence)` 튜플로 쓸지 — §8.2 #4
5. proposal.md 제목의 "multi-agent" 표현을 바꿀지 — 문서 작업에는 영향 없음, 코드 작업과 무관

**KG팀원이 이미 정리해 둔 결정 필요 사항** (`kg_rca/MCP_KG_정합성검토.md` §3 Q1~Q7, 요약 — 스켈레톤 코드와 직접 관련된 것 위주)

6. **[Q1]** 파라미터 어휘의 정본을 어디로 할지 — fab.db 시뮬레이터 쪽에 파라미터를 추가할지, MCP 문서/시나리오 예시를 KG의 20종에 맞춰 줄일지. 지금은 이게 안 정해져서 Scratch `[자동]` 가설이 0건이다 (§8.3 X1)
7. **[Q2]** MCP 쪽의 "클래스×원인 매핑표"(mapping_table.yaml)를 정답 시나리오로 볼지, 예시로만 볼지 — 정답이면 KG 문헌을 그에 맞춰 보강해야 함
8. **[Q5]** Hypothesis 루프의 단위를 "가설 1건당"으로 돌지, "검증 단위(`step`×`evidence`) 1건당"으로 돌지 — 가설이 381건이라 가설 단위로 돌면 MCP 호출이 폭증한다(§8.3 X3). **스텝 3(`hypothesis.py`) 설계에 직접 영향** — 착수 전에 정해야 함
9. **[Q6]** KG 조회 방식 — 지금 스켈레톤(`kg_client.py`)처럼 배치로 미리 생성된 `hypotheses.json`을 읽을지, 패턴 단건 질의나 Neo4j 직접 질의로 바꿀지. 스켈레톤은 배치 방식을 이미 전제하고 있음(README/§4 스텝1 docstring 참고) — 바뀌면 `kg_client.py` 재작성 필요

---

## 8. 0713 통합 정합성 점검 — state.py/graph.py 스켈레톤과 kg_rca·fab.db 실제 파일 대조

`SesacLine_SemiRCA/backend/`의 state.py·graph.py·nodes/*.py를 kg_rca·secsgem-mcp의 실제 파일과 필드 단위로 직접 대조했다(8.1·8.2). 이후 KG팀원이 별도로 남긴 `kg_rca/MCP_KG_정합성검토.md`(0711 작성, 우리보다 먼저 발견한 부분도 있음)를 확인해 겹치는 부분은 정리하고 우리 쪽에 없던 결정 필요 항목을 추가했다(8.3). cause 문자열이 join key가 아니라는 전제(§1~7 전반)는 코드로도 재확인됐고, 구조적으로 재설계가 필요한 문제는 없다 — 전부 "노드 로직 작성 전 한 줄/한 규칙만 정하면 되는" 수준이다.

### 8.1 확인된 것 (그대로 진행해도 됨)

- `GraphRAGCandidate`(state.py) 필드 ↔ `hypotheses.json`의 `path`/`verification`/`score` 매핑(스텝 1 표, §4)이 실제 파일과 정확히 일치.
- `mcp_client.py`의 9개 스텁 시그니처가 `secsgem-mcp/server/tools/*.py`의 실제 `@mcp.tool()` 9개 함수와 인자명·타입·기본값까지 전부 일치. 어댑터 없이 바인딩만 하면 됨.
- Parameter 20종 고정 vocabulary(`kg_rca/data/seeds/parameters.json`)와 `fab_model.yaml`의 실제 telemetry 파라미터가 일치.
- `hypotheses.json`이 381건으로 재생성된 것(0712, v2.3)은 KG팀원의 `STATUS.md`가 공식으로 확인해 준다 — 숫자가 커진 이유(`[근거없음]` 노출 방식 변경)도 문서화돼 있음. **더 이상 "확인 필요"가 아니라 확정된 최신 상태.**

### 8.2 우리 스켈레톤 자체의 gap (이번 점검에서 새로 발견, KG팀원 문서엔 없음)

| # | 내용 | 근거 | 영향 |
|---|---|---|---|
| 1 | `state.py`의 `Route = Literal["step", "direct"]`에 `"signature"`가 빠짐. `schema_v2.md`가 문서화한 3번째 경로(형상 경유)인데, 현재 3패턴 전부 signature route 0건이라 당장은 안 터짐(직접 카운트 확인, §2.3 참고). | `state.py` vs `schema_v2.md` | 지금은 무해. kg_rca가 형상 추출을 개선하면 조용히 타입 불일치 생김 — 1줄 수정으로 예방 가능 |
| 2 | `route="direct"` 후보는 `path.step`이 `null`이라, 스텝 3의 `run_commonality_analysis(lot_ids, step=cand.step)` 호출이 step 필터 없이 로트 전체 이력을 뒤섞게 됨. direct 경로는 스키마상 항상 반자동/근거없음이라 자동판정 오류로 이어지진 않지만, suspect 장비를 어떻게 좁힐지 미정의. | `6_ask_graphrag.py` DIRECT_QUERY(step=NULL) | 스텝 3(`hypothesis.py`) 작성 전에 결정 필요 |
| 3 | `verification.direction: null`인 `[자동]` 후보가 실제로 존재(예: Center `system_power_needs_adjustment`/`rf_power`). "값이 높아야 이상"인지 "그냥 벗어나면 이상"인지 규칙이 없음. | `hypotheses.json` 실제 항목 확인 | 스텝 3의 `_verify_candidate` 작성 전에 결정 필요 |
| 4 | 가설에 안정적 id가 없고 `rank`(생성 시 순서)만 있음. kg_rca가 재생성될 때마다(0711→0712 이미 한 번) rank 의미가 바뀜. | `hypotheses.json` 구조 | `app_state.db`에 배치 결과 저장 시 rank로 참조하면 다음날 다른 후보를 가리킬 수 있음 — `(step, failure_mode, cause, evidence)` 튜플을 키로 사용 권장 |

### 8.3 KG팀원의 자체 정합성 검토 요약 (`kg_rca/MCP_KG_정합성검토.md`)

KG팀원이 MCP 시나리오 문서(`kg_rca/SECS GEM MCP 문서_v0 1.md`)와 `hypotheses.json`을 대조해 이미 훨씬 상세하게 정리해 둔 문서다. 스켈레톤 코드와 직접 관련된 것 위주로 요약(심각도는 원문 표기 그대로 ■■■/■■/■):

| # | 심각도 | 내용 | 우리 스켈레톤과의 연결점 |
|---|---|---|---|
| X1 | ■■■ | 파라미터 어휘 불일치 — MCP 문서/`mapping_table.yaml`이 예시로 쓰는 파라미터(`패드 사용 시간` 등)가 KG 20종 vocab에 없음. 우리가 §8.2 이전 버전에서 찾은 `pad_usage_hours` 미스매치와 **같은 문제를 KG팀원이 더 넓게 확인**했다 — Scratch `[자동]` 가설이 그 결과로 0건 | 스텝 3에서 Scratch 패턴은 자동판정 경로가 사실상 없다고 가정하고 진행할 것 |
| X2 | ■■■ | MCP `mapping_table.yaml`의 클래스×원인 매핑표(9종)와 KG 추출 원인이 어휘·구성 모두 다름. 특히 CLEAN 공정은 KG에 근거 문헌이 아예 없어 CLEAN 가설 0건 | cause 표시 문장에 영향(전에 확인한 대로 join에는 무영향), 세정 관련 후보는 기대하지 말 것 |
| X3 | ■■ | 가설 381건을 "가설별로" MCP 호출하면 호출 폭발(175건 기준으로도 875회 추산). 실제 고유 검증 단위(`step`×`evidence`)는 그보다 훨씬 적음 | **스텝 3(`hypothesis.py`) 설계에 직접 영향** — `build_hypotheses`를 가설 단위가 아니라 `(step, evidence)` 단위로 묶어 MCP를 1회만 부르고 결과를 그 unit을 공유하는 모든 가설에 broadcast하는 구조로 짜야 함. Q5(§7) 결정 필요 |
| X4 | ■■ | `Alarm` evidence 노드가 KG에 없어서, 모든 알람이 "KG 메커니즘 경로 없음"으로 자동 처리됨 | Critic의 "④ KG 메커니즘 연결" 체크에서 알람 관련 근거는 항상 `insufficient_evidence` 방향으로 갈 것을 감안 |
| X6 | ■■ | `route="direct"`·`[근거없음]` 가설의 처리 절차가 MCP 시나리오 문서에 없음 | §8.2 #2와 같은 문제의 다른 표현. 스텝 3에서 함께 결정 |
| X7~X9 | ■ | Maintenance id ↔ fab `parts` 필드 자동 대조 불가(사람이 읽고 판단, `[반자동]` 정의와 일치) / step 표기가 문서는 한글·코드는 영문 / 배정확률(prob) 출처가 KG에 없음 | 스텝 3·4 구현 세부에 영향, 차단급은 아님 |

전체 목록(X1~X10)과 결정 필요 사항(Q1~Q7)은 §7에 우리 쪽 결정 사항과 함께 정리해 뒀다.

### 8.4 종합 — §4 순서에 반영된 것

- **스텝 1**: `state.py`의 `Route`에 `"signature"` 추가(8.2 #1), `KGClient` 완료 기준에서 하드코딩된 건수 제거.
- **스텝 3 착수 전 결정 필요**(팀 논의 후 진행): direct 경로 suspect 장비 선정(8.2 #2), `direction=null` 판정 규칙(8.2 #3), 가설 단위 vs 검증 단위 루프(X3/Q5) — 이 중 X3/Q5가 가장 설계에 크게 영향을 준다.
- **스텝 3 진행 시 가정**: Scratch는 자동판정 경로 사실상 없음(X1), CLEAN 공정은 후보 자체가 안 나옴(X2) — 데모/평가 범위를 Center 위주로 잡는 이유가 여기서도 재확인됨.
- **app_state.db 설계 시**: 참조 키를 rank가 아니라 `(step, failure_mode, cause, evidence)` 튜플로(8.2 #4).

### 8.5 0713 구현 착수 로그

**폴더 이동**: `kg_rca`, `dataset/secsgem_mcp/secsgem-mcp-main` → `SesacLine_SemiRCA/kg_rca`, `SesacLine_SemiRCA/secsgem-mcp`. 공동작업 편의를 위해 스켈레톤 repo 하위로 물리적으로 옮겼다(robocopy — 일부 파일이 `.venv`/편집기 프로세스에 잠겨 있어 plain `mv`는 실패, robocopy `/MOVE`로 우회). 두 폴더 다 자체 `.git`이 남아있었는데, **팀 결정으로 둘 다 삭제**해서 이제 평범한 폴더다 — `SesacLine_SemiRCA`에 나중에 `git init`하면 그 순간부터 안의 파일까지 하나의 repo/커밋 히스토리로 잡힌다(각 폴더의 이전 커밋 기록은 로컬에 더 이상 없음, 필요하면 원본 repo에서 따로 백업 확인).

**구현 완료 (실제 코드로 검증)**:
- `state.py`: `Route`에 `"signature"` 추가, `GraphRAGCandidate`에 `signature` 필드 추가(8.2 #1 해소).
- `graph_client/kg_client.py`: `get_candidates()` 완전 구현. `python3`로 직접 실행해 새 경로(`./kg_rca/outputs/hypotheses.json`)에서 `Center 255 / Edge-Ring 79 / Scratch 47`건이 정확히 나오는 것 확인, 미매핑 패턴(`Donut`)은 `candidates=[]` 확인.
- `mcp_client/client.py`: `MultiServerMCPClient` 연결 로직 전체 구현(지연 연결, cwd/PYTHONPATH/FAB_DB 절대경로 고정, 9개 메서드 전부 바인딩). 경로 리졸브는 검증 완료(`./secsgem-mcp` → 실제 `fab.db`/`server/main.py` 정확히 찾음). **단, `langchain-mcp-adapters` 등 패키지가 이 환경에 아직 설치돼 있지 않아 실제 서버 기동·툴 호출까지는 미검증** — 스텝 0(`pip install -r requirements.txt`) 이후 `get_lot_history` 한 번 호출해서 6줄짜리 결과가 오는지 확인 필요(§4 스텝2 완료 기준).
- `main.py`: `load_dotenv()` 추가, 하드코딩돼 있던(그리고 틀렸던) `kg_rca/outputs/hypotheses.json` 경로를 `KG_HYPOTHESES_PATH` 환경변수 참조로 교체.
- `.env`/`.env_example`: `./kg_rca`, `./secsgem-mcp` 상대경로로 정리.

**남은 것**: Step 0의 가상환경 구성(아래 §8.6으로 방법 확정됨), 그리고 그걸로 `mcp_client.py`를 실제 MCP 서버에 붙여서 라이브 검증하는 것.

### 8.6 0713 `.gitignore`/`pyproject.toml` 루트 통합

`kg_rca`, `secsgem-mcp`를 하위 폴더로 옮긴 뒤에도 각자 자체 `.gitignore`·`pyproject.toml`·`requirements.txt`를 따로 갖고 있던 상태였다. 가상환경을 루트 하나로만 관리하기로 하면서 다음을 정리했다.

- **`.gitignore`**: `kg_rca/.gitignore`, `secsgem-mcp/.gitignore`를 루트 `.gitignore` 하나로 병합. 경로 한정 규칙(`datasets/raw/`, `issue/`, `eval/results.json` 등)은 다른 폴더에 잘못 영향 주지 않도록 `secsgem-mcp/` 접두사를 붙여 이동.
- **가상환경**: `secsgem-mcp/.venv` 삭제(다른 하위 폴더엔 원래 없었음). 이제 `SesacLine_SemiRCA/.venv` 하나만 존재.
- **`pyproject.toml`**: `secsgem-mcp/pyproject.toml`의 `[project]`/`[tool.setuptools]`/`[tool.pytest.ini_options]`/`[tool.secsgem-mcp]`를 전부 루트 `pyproject.toml`로 이전. `server`/`preprocess`/`simulator`/`agent`/`eval` 패키지가 실제로는 `secsgem-mcp/` 밑에 있어서, `[tool.setuptools.package-dir]`로 실제 위치를 매핑해줬다(`backend`는 루트에 바로 있어서 매핑 불필요). 의존성은 루트/`kg_rca`/`secsgem-mcp` 세 곳에서 실제 `import`문을 직접 grep으로 확인해서 병합(`kg_rca/requirements.txt`는 `pip freeze` 전체 스냅샷이라 전이 의존성까지 다 박혀 있었음 — 직접 import하는 것만 추림).
- **CI**: `secsgem-mcp/.github/workflows/ci.yml`은 저장소 루트가 아니라 하위 폴더에 있어서 GitHub Actions가 애초에 인식하지 못하는 위치였다. 루트 `.github/workflows/ci.yml`로 옮기고 `working-directory: secsgem-mcp`를 추가해 살렸다.
- **검증**: `pip install --no-deps --no-build-isolation -e .`로 editable install 후 `server`/`preprocess`/`simulator`/`agent`/`eval` import까지 확인(테스트 후 uninstall해서 원상복구, 실제 가상환경 구성은 팀원 각자 진행).
- **미정**: 루트/`kg_rca`의 기존 `requirements.txt`를 그대로 둘지 삭제할지는 아직 결정 안 됨(내용은 `pyproject.toml`에 이미 흡수됨).
