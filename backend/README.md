# backend — FastAPI + LangGraph

RCA 파이프라인 ⓪~⑥ 실행과 API 8종 제공. 프로젝트 전체 소개·설치·실행은 루트 `README.md`,
API 계약 정본은 `docs/API_명세서_v1.0.md`를 본다. 이 문서는 **백엔드 내부 구조와 주의점**만 다룬다.

## 모듈 구조

```
backend/
  main.py            # 앱 조립만 (CORS·/api/v1 prefix·라우터 등록·저장소 초기화)
  api/               # 계약 라우트 8종 — 엔드포인트는 전부 여기
    yield_summary.py  # GET /yield-summary                                  §2.1
    analyses.py       # GET /analyses · /{id} · /{id}/evidence/{hid}        §2.2·2.5·2.7
    batches.py        # POST /batches · GET /batches/{id}                   §2.3·2.4
    lots.py           # GET /lots/{id}/wafers · .../die-map                 §2.6·2.6.1
  batch_runner.py    # 배치 백그라운드 실행 + 진행/로그 방출 + 결과 저장
  assembler.py       # 파이프라인 결과 → API 응답(§2.5+§2.7) 조립
  store.py           # app_state.db 접근 (batch·analysis·wafer_reading·cursor)
  schemas.py         # enum 정규화(tier 한글→영문, pattern 5종) + steps 8키 매핑
  config.py          # EVENT_DATE(2026-04-01) 등 상수
  deps.py            # KGClient·MCPClient 싱글턴
  state.py           # RCAState — 파이프라인 전체가 공유하는 상태 타입
  graph.py           # LangGraph StateGraph 조립 + _run_per_group(그룹 순회)
  nodes/             # ⓪~⑥ 파이프라인 노드 (아래)
  mcp_client/        # secsgem-mcp 9종 도구 클라이언트 (지속 세션 — 아래 주의)
  graph_client/      # kg_rca 결과(hypotheses.json) 조회 클라이언트
```

`main.py`는 앱 조립만 하고 엔드포인트를 직접 갖지 않는다. 라우터는 `api/` 하위 모듈로 분리한다.

### 파이프라인 노드

| 노드 | 파일 | 역할 |
|---|---|---|
| ⓪ | `nodes/lowyield.py` | 저수율 로트 선별 — fab.db 직접 SQL, **누적 구간**(직전 배치 이후 ~ 데이터축 최신일) |
| ① | `nodes/vlm.py` | 웨이퍼맵 판독 — 실제 VLM 미연동, `pattern="Center"` 고정 |
| ② | `nodes/grouper.py` | 패턴별 그룹화 — 로트별 다수결 대표패턴 |
| ③ | `nodes/graphrag.py` | kg_rca 원인후보 조회 (빌드타임 결과 조회, LLM 호출 없음) |
| ④ | `nodes/hypothesis.py` | 증거 수집·검증·**fab 재랭킹**. 자동 tier는 **LLM 에이전트**(그룹 조사관)가 step 배치로 telemetry 검증, 반자동·근거없음은 결정론. 근거 리치 보존 |
| ⑤ | `nodes/critic.py` | 4규칙 채택/기각 + `investigated` 마커 소비(미조사→judge_unknown) + 고정 사유 토큰(P2~P5·SEMI_AUTO_PENDING·NOT_INVESTIGATED) |
| ⑥ | `nodes/response.py` | 대표 정렬(index 0) → `h{n}` 부여 → 그룹 status 확정 |

- **명세는 8노드(⓪~⑦), 코드는 7노드(⓪~⑥)로 번호가 다르다.** 매핑표는 `docs/AGENT_GUIDE.md` §5.
  명세의 `vlm_describe`(그룹 대표 서술)에 대응하는 노드가 코드에 아직 없다.
- LLM을 실시간 호출하는 노드: **①VLM · ⑦응답생성**(둘 다 아직 하드코딩/템플릿), 그리고
  **④ Hypothesis의 자동 tier**(2026-07-22 S2-2로 `create_react_agent` 그룹 조사관 도입 —
  반자동·근거없음과 ⑤ Critic은 결정론 유지, ③KG조회는 빌드타임 결과 조회).
  **주의: ④가 LLM이 됐어도 숫자(evidence)는 도구 반환에서 코드가 재구성하고 LLM은 서사
  (rationale)만 쓴다(옵션 A) — ⑤ Critic은 rationale을 안 믿고 evidence만 읽어 판정한다
  (faithfulness firewall).**
- `graph.py`의 그룹 팬아웃은 Send API가 아니라 **순차 loop**(`_run_per_group`)다.

## 설계 포인트

**1. 배치는 비동기 job.** `POST /batches`가 배치 레코드를 만들고 `asyncio.create_task`로
`batch_runner.run_batch`를 띄운 뒤 202로 즉시 반환한다. 러너는 `graph.astream(stream_mode="updates")`
로 노드 완료마다 `current_step`을 갱신하고, MCP 호출 트레이스를 `logs`에 쌓는다. 프론트는
`GET /batches/{id}`를 1.5초 간격으로 폴링한다. 실행 실패는 HTTP 500이 아니라
`200 + status:"failed"`로 표현한다(폴링 루프가 200을 기대하기 때문).

**2. 근거는 배치 때 저장하고, 조회 시 재계산하지 않는다.** ④에서 모은 증거를 `EvidenceEntry`에
리치하게(commonality 전체 테이블·telemetry 시계열·정비 rows) 보존해 `assembler.py`가 API 응답
형태로 조립한 뒤 `app_state.db`에 통째로 넣는다. 근거 모달은 저장분을 꺼내 보여줄 뿐이다 —
온디맨드로 MCP를 다시 부르면 배치 때의 판단 근거와 미세하게 어긋난다.

**3. enum 정규화는 API 경계에서만.** `state.py`의 `Tier`는 한글(`"자동"`/`"반자동"`/`"근거없음"`)이고
`hypothesis.py`·`critic.py`가 이 값으로 분기한다. 노드 안에서 값을 바꾸면 tier 분기가 깨지므로,
영문(`auto`/`semi_auto`/`none`) 변환은 `schemas.py`/`assembler.py`에서만 한다. `pattern` 5종
정규화도 같은 노선.

**4. 정렬 불변식.** ⑥이 대표 accepted를 index 0에 두도록 정렬을 **확정한 뒤** 그 인덱스로
`hypothesis_id`(`h{n}`)를 부여한다. 정렬 전에 번호를 매기면 `h0`가 대표가 아니게 된다. 프론트는
받은 순서를 신뢰하고 재정렬하지 않는다.

## MCP 연결 (지속 세션 — 깨지 말 것)

`MultiServerMCPClient.get_tools()`는 **호출마다 새 stdio 서브프로세스를 생성한다**(라이브러리
docstring에 명시된 동작). Hypothesis 노드처럼 다회 호출하는 패턴에서는 치명적으로 느려서
(실측: Center 244건 처리 시 타임아웃), `mcp_client/client.py`는 `client.session()`으로 연결을
한 번만 열고 `load_mcp_tools(session, ...)`로 그 세션을 재사용한다.

- `MCPClient`는 모듈 레벨 싱글턴으로 유지할 것 (`deps.py`).
- 배치 진행 로그를 남기는 `LoggingMCP`(`batch_runner.py`)는 이 싱글턴을 감싸는 **위임 프록시**일
  뿐 세션을 새로 만들지 않는다.
- `hypothesis.py`의 `(step, evidence_label, evidence)` 캐싱 키도 같은 이유로 유지한다
  (현재는 반자동·근거없음 결정론 경로 전용 — 자동 tier의 중복 호출은 배치 telemetry 1콜이 흡수).

## 단순화 목록

코드에 `# 결정①/②/③` 또는 `TODO(팀 결정 필요)`로 표시돼 있다. 계약 밖 내부 정책 결정 12건은
`docs/BACKEND_DECISIONS.md`에 따로 기록했다.

| # | 위치 | 지금 선택 | 비고 |
|---|---|---|---|
| 1 | `hypothesis.py` — MCP 호출 단위 | 자동 tier는 배치 telemetry 1콜, 반자동·근거없음은 `(step, evidence_label, evidence)` 캐싱 | 자동은 그룹 조사관(S2-2)이 흡수, 캐싱은 결정론 경로 잔존 |
| 2 | `hypothesis.py` — `step=null` 후보 | ~~그대로 전달~~ → **mapping.process로 폴백**(`_with_step_fallback`, D14) | KG가 path.step 교정하면 무동작. 근본은 kg_rca 6번(`personalspace_rca` `kg_step보충_제안.md`) |
| 3 | ~~`direction:null` 자동 방향 무시~~ **해소(S2-1)** | 방향 대조(`_drift_direction`/`_direction_match`)로 승격 — drift 방향↔KG 예상 대조로 경쟁 가설 판별 | `direction=null` 후보만 여전히 n/a |
| 4 | `lowyield.py` — 저수율 임계값 | `LOW_YIELD_THRESHOLD = 0.8` 고정 | 동적 임계값 미검토 |
| 5 | `grouper.py` — 최소 로트수 게이트 | `MIN_LOTS_PER_GROUP = 1`(게이트 없음) | 서브클러스터링 없음 |
| 6 | `vlm.py` | 실제 VLM 미연동, `pattern="Center"` 고정 | 이 때문에 그룹이 1개만 생긴다 |
| 7 | `response.py` | 실제 LLM 미연동, 결정적 템플릿 | §2.5 `description`은 `null` → 프론트가 `summary_line`으로 fallback |
| 8 | `critic.py` — `semi_auto`/미조사 판정 | **judge_unknown 보류**(`investigated` 마커 기반, S2-6·D8) — 반자동 `SEMI_AUTO_PENDING` / 자동 폴백 `NOT_INVESTIGATED` | 기각 아님(보류). §4-2 사람 판정/반자동 조사 경로 생기면 해소 |

## 알려진 버그 (발견·수정·재검증 완료 — 재발 방지용)

1. `mcp_client/client.py`의 `_as_dict`가 MCP 응답 모양을 못 받음 — 구조화 출력이 없으면 MCP 표준
   콘텐츠 블록 리스트(`[{"type": "text", "text": "<json>"}]`)로 오는데 `dict`/`str`만 처리하고 있었음.
2. `"command": "python"`이 PATH 의존적 — 다른 파이썬이 먼저 잡히면 `fastmcp`를 못 찾고 죽음.
   `sys.executable`로 고정.
3. `env=`를 통째로 갈아치우면 Windows에서 불안정 — `SystemRoot` 등 필수 환경변수가 빠짐. 부모
   환경을 이어받은 채로 `PYTHONPATH`/`FAB_DB`만 덧붙이도록 수정.
4. `MultiServerMCPClient.get_tools()`가 호출마다 새 세션을 만듦 — 위 "MCP 연결" 참고. 가장
   치명적이었던 버그(타임아웃 유발).
5. `secsgem-mcp/simulator/fab_model.py`가 Windows에서 `fab_model.yaml`을 인코딩 미지정으로 읽어
   한글 주석에서 `UnicodeDecodeError` — `encoding="utf-8"` 명시. **Windows에서 파일 읽을 때는
   항상 인코딩을 명시할 것.**
6. `hypothesis.py`가 `candidate["senetence"]`(오타)를 읽어 후보 1건만 처리해도 `KeyError` —
   2026-07-20 수정.
7. `graph.py`의 ③~⑥ 노드를 람다로 감싸면 `await`를 담지 못해 코루틴 객체만 반환하고 실행이 안 됨
   — `async def`로 감싼다.

## 테스트

```bash
pytest -q -m "not data" backend    # 11건 — fab.db 없이 도는 계약 스모크
```

`backend/tests/test_api_smoke.py`가 라우팅·검증·404/422/빈 목록 형태와 `assembler`의 키 집합
계약을 확인한다. 레포 루트에서 `pytest -q -m "not data"`를 돌리면 secsgem-mcp 테스트 9건이
실패하는데, 테스트가 cwd 상대경로(`simulator/mapping_table.yaml`)를 참조하는 기존 문제다
(백엔드 변경과 무관).
