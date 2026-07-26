# Langfuse 관측성(트레이싱) 설계 공유 문서 v1.0

## 0. 요약

- **기능**: Langfuse Cloud 트레이싱 통합 (LangGraph 배치 파이프라인 관측성)
- **파일**: `backend/deps.py`(핸들러 게이트) · `backend/batch_runner.py`(배선·앵커·flush)
- **설정**: `.env_example`(키 4종 + `LANGFUSE_TIMEOUT`) · `pyproject.toml`(`langfuse>=4.14.1`)
- **담당**: noh000
- **한 줄 역할**: 이게 없으면 "배치가 왜 이 원인 카드를 냈나"를 노드/LLM/MCP 호출 단위로
  되짚을 수 없다 — 배치 1회를 **트레이스 1개**로 잡아 노드·그룹·LLM·MCP 도구호출을 트리로 남긴다.
- **상태**: 구현 완료(라이브 검증 통과). ⑦ 응답 LLM은 아직 템플릿이라 GENERATION은 ⑤ react-agent만.
- **작성일 / 대상 커밋**: 2026-07-26 / `da7faf1` (통합 커밋열 U2~U9 + flush 수정)
- **정본 이슈/PR**: #81 / PR #90.

---

## 1. 계약 (필수)

노드처럼 state 키를 주고받지 않는다. 이 통합의 "계약"은 **환경변수 게이트**와 **격리 보장**이다.

### 1-1. 입력 — 환경변수 게이트

| env | 의미 | 없으면/off면 |
|---|---|---|
| `LANGFUSE_TRACING` | `1/true/yes`일 때만 트레이싱 활성 | 그 외 전부 완전 비활성(핸들러=None) |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Cloud 인증 키 | 하나라도 없으면 활성 안 됨(경고 후 None) |
| `LANGFUSE_BASE_URL` | 리전 엔드포인트(기본 JP `https://jp.cloud.langfuse.com`) | langfuse SDK 기본값 |
| `LANGFUSE_TIMEOUT` | span export HTTP 타임아웃(초, 기본 60) | 60초 |

- **전제조건**: `LANGFUSE_TRACING=1` **그리고** public/secret 키가 둘 다 있어야만 실체 핸들러가
  생긴다. 이 관례는 `KG_LIVE`/`RESPONSE_LLM`과 동일하다(off-by-default).
- **가정이 깨지면**: 조용히 None을 돌려주고 파이프라인은 트레이싱 없이 정상 진행한다.
  예외를 던지지 않는다(§2).

### 1-2. 출력 — 무엇이 어떻게 잡히나

| 산출물 | 형태 | 불변식 |
|---|---|---|
| 트레이스 | 배치 1회 = **트레이스 1개** | `name=rca-batch`, `session=batch_id`, `tags=[rca-batch]` |
| 관측치(observation) | 노드=CHAIN, LLM=GENERATION, MCP=TOOL, react-agent=AGENT | 단일 루트 `[SPAN] rca-batch` 아래 전부 중첩 |

- **믿어도 되는 불변식**: 정상 export 시 **고아(부모 유실) 0** — 배치그래프 → `run_groups` →
  그룹 서브그래프(④~⑦) → LLM/MCP가 하나의 트리로 이어진다. (라이브 실측: 트레이스
  `0f994794`, obs 575, orphans 0.)
- **건드리지 않는 것**: `RCAState`/`GroupState` 등 파이프라인 state·결과 저장(`store`)은
  일절 변경 없음. 트레이싱은 순수 관측이라 배치 결과에 영향 0.

### 1-3. 새로 도입한 것

- `deps.langfuse_handler()` — 게이트 팩토리(지연 싱글턴, `response_translator`와 같은 관례).
- 신규 state 필드 **없음**.

---

## 2. 실패·경계 케이스 계약 (필수)

> **원칙 #2: 관측성 실패가 배치를 죽이면 안 된다.** 모든 langfuse 호출은 try/except로 격리.

| 상황 | 동작 | 배치가 보게 되는 것 |
|---|---|---|
| `LANGFUSE_TRACING` off | 핸들러=None, `run_config=None`(LangGraph no-op) | 트레이싱 없이 기존과 완전 동일 |
| 키 없음 | 경고 1줄 후 None | 위와 동일 |
| langfuse import/초기화 실패 | try/except → 경고 후 None | 위와 동일 |
| 트레이스 속성 설정 실패 | `ExitStack` 안 try/except → 경고 후 계속 | 배치 정상, 트레이스만 속성 일부 누락 |
| export 타임아웃(엔드포인트 느림/죽음) | SDK가 로그+재시도 후 드롭(예외 안 던짐) | 배치 정상, 해당 span만 유실 |
| flush 실패 | `finally` try/except → 경고 후 계속 | 배치 결과 정상 저장 |

- **예외를 던지는 경로가 있는가?** 없다 — 트레이싱 전 구간이 격리돼 있어 배치/그룹 어느
  것도 트레이싱 때문에 죽지 않는다.
- **타임아웃·재시도**: export는 SDK 내부 재시도(로그만, 예외 없음). 우리 코드의 재시도는 없음.

---

## 3. 내부 플로우

```
[조립 시점] deps.langfuse_handler()
   TRACING!=1 or 키없음 ─→ None ─→ run_config=None ─→ (이하 트레이싱 no-op, 기존 경로)
   실체 핸들러 ─→ Langfuse(timeout=env)로 싱글턴 먼저 초기화 → CallbackHandler()

[run_batch 실행] _run_batch_inner
   run_config = {"callbacks":[handler]}
   with ExitStack:
       (handler 있으면) start_as_current_observation(span, "rca-batch")  ← 그룹핑 앵커
                        propagate_attributes(trace_name/session=batch_id/tags)  ← 트레이스 속성
       async for ... graph.astream(state, subgraphs=True, config=run_config)  ← 트리 자동 캡처

[run_batch finally] (성공·실패 무관)
   handler 있으면 → await asyncio.to_thread(get_client().flush)   ← 잔여 트레이스 강제 전송
```

- **왜 앵커 span이 필요한가**: config metadata의 `langfuse_*` 키는 LangGraph subgraphs 구조에서
  트레이스 레벨에 안 붙었다(Step 7 실측). v4 권장대로 활성 span 컨텍스트로 감싸야 astream이
  만드는 콜백 span들이 한 트레이스로 묶인다. 앵커를 빼면 span이 트레이스에서 유실된다.
- **왜 finally에서 flush**: `run_batch`는 `create_task`로 뜬 장수 백그라운드 코루틴이라
  프로세스 종료 훅(atexit)에 안 걸린다 → 마지막 트레이스가 유실될 수 있어 배치 끝에 강제 전송.

---

## 4. 설계에서 중요하게 고려한 것 (필수)

### 4-1. 기본 완전 비활성(off-by-default) 게이트

- **문제**: CI·미설정·팀원 로컬에 langfuse 키가 없거나 아예 설치 안 돼 있을 수 있다. 트레이싱이
  기본 켜져 있으면 그런 환경에서 import/인증 에러로 배치가 깨진다.
- **선택**: `LANGFUSE_TRACING=1` + 키 둘 다일 때만 실체, 아니면 None. langfuse import도 함수
  안 지연 import라 미설치 환경에서 `deps` import 자체가 안 깨진다.
- **대안과 기각**: "설치돼 있으면 자동 활성" — 미설정 환경에서 조용히 실패하거나 원치 않는
  데이터 전송이 생겨 기각. `KG_LIVE`/`RESPONSE_LLM`과 관례를 맞추는 게 팀 학습비용도 낮다.
- **되돌릴 조건**: 트레이싱이 상시 필수가 되면 기본값을 켜는 것 재검토.

### 4-2. 루트 앵커 span + `propagate_attributes` (트레이스 속성 부착)

- **문제**: LangGraph 2층(배치그래프 + 그룹 서브그래프) 구조에서 `config.metadata`의
  `langfuse_session_id`/`tags`가 트레이스 레벨에 안 붙고, 콜백 span이 트레이스에서 유실됐다
  (Step 7 실측).
- **선택**: `start_as_current_observation(span, "rca-batch")`로 활성 컨텍스트를 만들고 그 안에서
  `astream`을 돌려 모든 콜백 span을 attach. 속성은 `propagate_attributes`(baggage)로 부착.
- **대안과 기각**: config metadata만으로 처리 — 위 실측으로 트레이스 레벨 미적용 확인돼 기각.
- **되돌릴 조건**: langfuse SDK가 subgraph config 전파를 개선하면 앵커 래퍼 제거 검토.

### 4-3. export 타임아웃 60초 상향 (U9, 커밋 `c39a4a6`)

- **문제**: 기본 export timeout 5초가 JP 리전 + 전체 state를 실은 큰 컨테이너 span
  (`build_hypotheses` 등) 업로드에 짧아 span이 드롭됐다(실측 5s→3실패, 20/30s→1, 60s→0).
  드롭된 컨테이너의 자식이 고아가 되어 트리가 평평해 보였다.
- **선택**: `CallbackHandler`보다 먼저 `Langfuse(timeout=int(env,60))`로 싱글턴 초기화.
- **대안과 기각**: 30초로 축소 — 실측에서 1건 드롭 재현돼 60초 유지(팀 결정). 정상 export는
  <1초라 이 값은 **도달하지 않는 상한**이고 느릴 때만 여유를 준다.
- **되돌릴 조건**: 리전을 가까운 곳으로 옮기거나 span payload를 줄이면 하향 검토.

### 4-4. flush를 워커 스레드로 (`da7faf1`, CodeRabbit PR #90 리뷰 반영)

- **문제**: `get_client().flush()`는 동기 blocking인데 `run_batch`는 이벤트 루프 위 코루틴이라,
  flush 동안(4-3으로 최악 60초) FastAPI 루프 전체가 멈춰 다른 요청(배치 상태 폴링·`/health`)을
  얼릴 수 있었다.
- **선택**: `await asyncio.to_thread(get_client().flush)`로 워커 스레드에 이관. 트레이스 내용은
  불변(export 동작 그대로), 이벤트 루프만 살렸다. 라이브 재검증 통과(§7).
- **대안과 기각**: `shutdown()` — 서버는 계속 살아 다음 배치도 트레이싱해야 하므로 닫으면 안 됨.
- **되돌릴 조건**: 없음(순수 개선).

---

## 5. 외부 의존

| 무엇 | 어디 | 결정적인가 | 없으면 |
|---|---|---|---|
| Langfuse Cloud | `LANGFUSE_BASE_URL`(JP) | 네트워크 의존(비결정적 지연) | 트레이싱만 유실, 배치 무영향 |
| `langfuse` SDK | `pyproject.toml`(`>=4.14.1`) | — | 지연 import라 미설치여도 배치 정상 |
| `CallbackHandler`/`get_client` 싱글턴 | `deps` / `batch_runner` | 앱 전체 1개 공유 | — |

- **비결정적 요소**: 네트워크 export 지연 → span 전송 시점·타임아웃 여부가 run마다 다를 수 있다.
  그래서 **트레이싱 완전성은 obs 수가 아니라 `Failed to export`=0 + orphans=0으로 판단**한다
  (obs 수는 배치 자체의 비결정성 탓에 흔들림 — 아래 §8).
- **호출 횟수/지연**: 배치 1회당 트레이스 1개. flush는 배치 끝 1회(정상 <1초, 워커 스레드).

---

## 6. 튜닝 상수 · 매직넘버

| 이름 | 값 | 위치 | 근거 |
|---|---|---|---|
| `LANGFUSE_TIMEOUT` | 60(초) | `deps.langfuse_handler` | §4-3 — 도달하지 않는 상한, 30초는 드롭 재현 |
| trace name / tag | `"rca-batch"` | `batch_runner._run_batch_inner` | 배치 트레이스 식별용 고정 문자열 |
| session id | `batch_id` | 동상 | 배치 1회 = 세션 1개 |

---

## 7. 테스트 현황

- **단위 테스트**: `backend/tests/test_deps_langfuse.py` — 게이트 off 경로 2종(TRACING 미설정 /
  키 없음)에서 핸들러가 None임을 보장. `backend/tests` 전체 176 passed(`-m "not data"`).
- **라이브 검증(uvicorn + `POST /api/v1/batches`)**: 트레이스 1개, 단일 `[SPAN] rca-batch` 루트,
  orphans 0, 서버 로그 `Failed to export` 0. flush 수정(`da7faf1`) 후 재검증도 동일 재현
  (트레이스 `0f994794`, obs 575).
- **아직 검증 못 한 것**: 엔드포인트 완전 다운 상태에서의 동시요청 응답성(이벤트 루프 비블로킹)은
  코드 경로로만 보장, 부하 실측은 미수행(데모 범위 밖). 비-LLM span 커스텀 속성/스코어 미부착.

---

## 8. 알려진 한계 · 팀 논의 필요

| # | 항목 | 내 제안 | 결정 필요 |
|---|---|---|---|
| 1 | 트레이스 obs 수가 run마다 크게 변동(170~575) | react-agent 비결정성+후보 수 탓, 트레이싱 문제 아님 → 완전성은 export실패/orphans로 판단 | 문서화로 충분 |
| 2 | Center 폴백 시 후보 다수 → TOOL span 수백 개 | 파이프라인 특성(CNN 붙으면 그룹 분산) — 결함 아님 | 논의 불요 |
| 3 | ⑦ 응답 LLM 미연동 → GENERATION은 ⑤ react-agent만 | RESPONSE_LLM 붙으면 자동 캡처됨 | 후속 |
| 4 | 팀 키 공유·seat 초대(Step 8) | 관리자가 seat 초대 후 개인 키 발급 | 팀 진행 |
| 5 | faithfulness 스코어·비-LLM span 보강(선택 Step 6) | 데모 범위 밖, 여유 시 | 후순위 |

---

## 부록. 코드 진입점 맵

| 하고 싶은 일 | 볼 곳 |
|---|---|
| 트레이싱 켜기/끄기 | `.env`의 `LANGFUSE_TRACING`(+ 키) |
| 핸들러 생성 규칙·게이트 바꾸기 | `backend/deps.py:langfuse_handler` |
| export 타임아웃 조정 | `.env`의 `LANGFUSE_TIMEOUT` (기본 `deps.langfuse_handler`) |
| 트레이스 이름·세션·태그 바꾸기 | `backend/batch_runner.py:_run_batch_inner`(propagate_attributes) |
| flush 동작 바꾸기 | `backend/batch_runner.py:run_batch`(finally) |
