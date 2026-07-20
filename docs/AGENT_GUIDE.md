# 개발 가이드 (에이전트용)

> **계약 정본: `docs/API_명세서_v1.0.md`.** 이 문서의 모든 `§n`은 그 명세서의 절 번호다. 절은 Grep으로 `### 2.7` 형태로 찾아 그 절만 읽는다(행번호로 찾지 마라).

## 1. 세션 규칙

- 계약의 정본은 **맨 위 한 줄에 적힌 명세서 하나**다. `docs/`의 다른 문서(`API_CHANGELOG.md`·`skeleton_kickoff.md`·`service_flow.md`·`semiconductor_proposal.md`)는 **보지 않는다** — 폐기된 대안·구버전 서술이 섞여 있어 이중 진실원이 된다.
- **필드표가 정본, 예시 JSON은 참고다.** §2.4·§2.5 예시엔 `"...": "동일 7키"` 같은 축약이 있어, 예시를 복붙해 Pydantic 모델·타입을 만들면 키가 빠진다. 반드시 각 절의 "필드 존재 계약" 표를 근거로 삼는다.
- **명세서 자체를 고치지 마라.** 계약이 이상해 보이면 코드나 명세를 손대지 말고 사용자에게 보고한다(명세 개정은 사용자가 한다).
- **이 가이드도 담당자 재량으로만 수정한다.** 에이전트는 임의로 고치지 말고 필요성을 보고한다 — 계약을 라우팅하는 문서라 한쪽에서 조용히 바꾸면 명세서와 갈라진다.
- **소통 없이 고칠 수 있는 곳은 §3의 `AGENT-EDITABLE` 블록 하나뿐**이다(프론트 환경 4줄). 슬라이스 표·금지 목록·3등급 표·매핑표는 해당 없음.
- 상시 참조는 **§1(공통 규약)·§1.1(에러 형식)·§3(enum 정본표)·§3.1(핵심 원칙 4개)** 네 곳뿐. 나머지는 해당 슬라이스일 때만 읽는다.
- **노드 번호는 명세(⓪~⑦, 8노드)와 코드(⓪~⑥, 7노드)가 다르다.** 이 가이드와 `BACKEND_GAP.md`는 **명세 번호**로 말하고(⑤Hypothesis·⑦응답생성), 코드 대응은 **§5 매핑표**로 확인한다.

### 1-a. 미결정·갭 3등급

| 등급 | 해당 | 행동 |
|---|---|---|
| **정지** | §4-2(`semi_auto` 사람판정 엔드포인트)·§4-3(Critic 반대근거 문구) | 구현 금지. 계약이 함께 바뀌는 사안이다 |
| **선확인 후 진행** | 본문 `🔲 백엔드 확인(4장)` 마커 | 슬라이스 착수 시 그 절의 🔲를 **모아 한 번** 보고 → 승인 후 진행 |
| **잠정+기록** | §4-1(대표 원인 `top_cause` 지정 로직) 등 계약 밖 내부 구현 정책 | 규칙을 정해 구현하고 근거를 한 곳에 남긴 뒤 보고 |

§4를 통째로 정지로 묶지 마라 — **§4-1만 성격이 다르다.** 명세가 "API가 아니라 ⑦응답생성 소관"이라고 이미 선을 그었고, §2.5는 정렬 불변식(index 0 = 대표)을 계약으로 걸어놨다. 정지로 묶으면 ⑦응답생성 구현이 시작되지 않는다.

🔲는 마커마다 멈추지 말고 **슬라이스 단위로 한 번** 보고한다(§2.7 갭 표만 11행이라 매번 멈추면 세션이 안 굴러간다):

```
§2.5 착수 — 이 절의 🔲 2건
1. description: VLM 미연동 → 제안: null 반환, 프론트는 summary_line fallback
   계약 수정 필요? 아니오
2. stage: Hypothesis에 필드 없음 → 제안: state.py에 stage 추가, ⑤Hypothesis에서 cand.step 전달
   계약 수정 필요? 아니오
진행할까요? (계약을 고쳐야 한다면 명세서 수정은 사용자가 합니다)
```

핵심은 **"계약 수정 필요? 예/아니오"를 매번 명시적으로 판단해 내놓는 것**이다. "예"면 멈추고 사용자의 명세 개정을 기다린다.

### 1-b. 수정 가능 경계

**고쳐야 하는 곳** — 갭 해소는 대부분 여기 수술이다: `backend/state.py`(예: `Hypothesis`에 `stage` 추가)·`backend/nodes/`·`backend/api/`·프론트 코드 전부.

**건드리면 안 되는 곳**(전부 실제 사고 이력):

- `mcp_client/client.py`의 **싱글턴 세션 재사용** — 깨면 대량 호출에서 타임아웃(실측)
- `graph.py`의 ③~⑥ `async def` 래핑 — 람다로 되돌리면 `await`를 못 담아 실행 자체가 안 됨
- `hypothesis.py`의 `(step, evidence_label, evidence)` 캐싱 키 — 없으면 244건에서 타임아웃
- `kg_rca/`·`secsgem-mcp/` — 변경이 필요하면 멈추고 보고(알람 미연동 등 원인이 그쪽인 갭이 있다)

**enum 정규화는 API 경계에서만** 한다. `state.py`의 `Tier`는 한글 `"자동"|"반자동"|"근거없음"`인데 §3 계약은 `auto`|`semi_auto`|`none`이다. 노드 안에서 값을 바꾸면 `hypothesis.py`·`critic.py`의 tier 분기가 깨진다. §1이 `pattern`에 쓰는 방식(FastAPI가 정규화)을 그대로 따른다.

**라우터는 `backend/api/` 하위 모듈로 분리**하고 `main.py`는 앱 조립(CORS·의존성·라우터 등록)만 한다. 현재 `main.py`에 엔드포인트가 직접 박혀 있으나 7종으로 늘리면서 이 구조로 옮긴다.

## 2. 읽기 지도 — 슬라이스 표

**착수 순서**: 슬라이스 0 → 수율 차트 → 배치 실행·진행 → 대기열 → 분석 상세 → 웨이퍼맵 → 근거 모달. 수율 차트(§2.1)·웨이퍼맵(§2.6)은 `fab.db`만 있으면 되지만, **대기열·상세·근거는 배치를 한 번 돌려야 볼 데이터가 생긴다**(§2.3 `result_ids` → §2.2 `analysis_id` → §2.5 `hypothesis_id` → §2.7). 웨이퍼맵은 §2.5 화면에서 진입하므로 상세 뒤에 붙인다.

| 슬라이스 | 읽을 절 | 백엔드 | 프론트 | 해당 절 🔲 |
|---|---|---|---|---|
| 0. 프론트 부트스트랩 | §1 (Base URL·CORS) | — | Vite 프로젝트 생성, §3 블록 4줄 기록 | — |
| 화면1 수율 차트 | §2.1 | `GET /yield-summary` 신설. `metric_series` 단독 집계(라인평균=일별 `AVG`, 저수율장비=최저 장비 시리즈), `×100` 정수 변환, 기준일 `max(ts)` 7일, 빈 날 `null` 채움 | 7일 추이 차트. `series[].name` 키로 매칭(인덱스 금지), `points[i]=null`은 선 끊김, 빈 배열 UI 유지 | 없음 |
| 화면1 분석 대기열 | §2.2 | `GET /analyses` 신설. `sort`(422 검증)·`limit`/`offset`, `count`=전체 총계, `app_state.db` 조회, `items[]` 5키 항상 존재, `top_cause`=`hypotheses[0].cause` | 대기열 테이블, `status` 3종 배지, 행 클릭 → 상세, `count`로 페이지 계산, 빈 목록 안내 | 없음(단 `top_cause`는 §4-1 대표 선정에 의존 → 1-a "잠정+기록") |
| 배치 실행·진행 | §2.3 §2.4 | `POST /batches`(202 즉시 반환·비동기 실행·409 2케이스) + `GET /batches/{batch_id}`. `EVENT_DATE=2026-04-01` 상수로 ID 채번, 응답 7키 superset, `steps` 고정 8키, `current_step` 0-based, `logs` MCP 트레이스 방출 | 실행 버튼(409면 비활성+`detail` 안내), 화면2 1~2초 폴링, 진행바(`steps[current_step]`), 로그 리스트, `completed`/`failed`면 폴링 종료 | 없음(§5 매핑표 필수 — 진행 방출 훅 자체가 코드에 없다) |
| 화면3 분석 상세 | §2.5 (+§3.2) | `GET /analyses/{analysis_id}`. 3 status 키집합 동일(값만 `null`), ⑦이 대표를 index 0에 두고 정렬한 **뒤** `h{n}` 부여, `stage`·`citations`·`next_actions` 실기, `verdict` 3-state 승격(고정 토큰) | 가설 카드, `description`→`summary_line`(§3.2) fallback, `verdict`/`tier` 배지, `lot_ids` 클릭 → 웨이퍼맵, 받은 순서 그대로 렌더 | 3건 — `description`(VLM 미연동), `semi_auto` 자동기각(잠정), `stage` 필드 부재. §3.2의 🔲는 이 `stage`와 같은 갭이다 |
| 로트 웨이퍼맵 | §2.6 §2.6.1 | `GET /lots/{lot_id}/wafers`(`wafer_id` 정수 오름차순 정렬, 3집계 항등식, `die_map_url`은 `/api/v1` 없는 경로) + die-map 얇은 재서빙(MCP `get_wafer_map` base64 디코드 → `image/png`) | 웨이퍼 그리드(`wafers.length` 기준·25칸 고정 금지), 이미지 `src` = Base URL + `die_map_url`, 이미지 404 방어 | 없음 |
| 근거 모달 | §2.7 | `GET /analyses/{id}/evidence/{hypothesis_id}`. 배치 실행 시 `EvidenceEntry`에 리치 보존 → 조회만(재계산 금지). 3섹션 `available`/`reason`, `suspect` 교차제약, 404 2종 | 모달 3섹션(Commonality 표·Telemetry 차트+`normal_range`·`t0` 수직선·Events 타임라인), `available:false`는 "미수집"으로 렌더, `ratio`만 %로 변환 | 2건 — `verdict` 3-state 매핑, §2.7 갭 표 전체(11행) |

**슬라이스 0은 프론트 코드가 아직 없어서 있는 행**이다. 완료 조건은 "§3 `AGENT-EDITABLE` 블록 4줄이 채워짐"이고, 한 번 끝나면 이후 세션은 그 블록을 읽기만 한다.

## 3. 검증 방법

- 전제: 실서버로 확인한다(mock 없음). `secsgem-mcp/datasets/fab.db`가 없으면 거기서 멈추고 사용자에게 보고한다 — 데이터 빌드는 별도 절차다.
- 실행: 백엔드·프론트 개발 서버를 동시에 띄운다(포트는 §1 Base URL·CORS 오리진 참조).
- 슬라이스 완료 기준: **엔드포인트를 curl로 한 번 + 해당 화면에서 한 번** 확인한다.
- 회귀: `pytest -q -m "not data"` 통과(fab.db 없이 도는 셋).
- 완료를 주장하기 전에 실제 실행 결과를 붙인다. 안 돌려보고 "구현했습니다"는 금지.
- 슬라이스별 확인 curl(`B=http://localhost:8000/api/v1`):
  1. `curl "$B/yield-summary"`
  2. `curl "$B/analyses?sort=latest&limit=10&offset=0"`
  3. `curl -X POST "$B/batches" -H 'Content-Type: application/json' -d '{}'` → `curl "$B/batches/batch_20260401_01"`
  4. `curl "$B/analyses/grp_center_20260401_01"`
  5. `curl "$B/lots/lot23844/wafers"` → `curl -o w1.png "$B/lots/lot23844/wafers/1/die-map"`
  6. `curl "$B/analyses/grp_center_20260401_01/evidence/h0"`

<!-- AGENT-EDITABLE: 프론트 환경. 슬라이스 0에서 채운다.
     이미 채워져 있으면 수정 금지 — 변경이 필요하면 멈추고 보고할 것. -->
- 프론트 디렉터리: (슬라이스 0에서 채움)
- dev 실행(백엔드+프론트 2줄): (슬라이스 0에서 채움)
- API Base URL 주입 방식: (슬라이스 0에서 채움)
- Vite 프록시: **사용 안 함** — §1 CORS를 서버(`CORSMiddleware`)가 담당한다
<!-- /AGENT-EDITABLE -->

블록 규칙 3가지: ⑴ 에이전트가 **소통 없이** 고칠 수 있는 곳은 이 블록뿐이다(다른 절은 보고 → 담당자 합의 → 담당자가 수정, §1과 동일). ⑵ **1회성**이다 — 값이 이미 있으면 덮어쓰지 말고 보고한다. ⑶ 스캐폴드와 **같은 턴에** 기록한다.

프론트 스택(TS 여부·상태관리·차트·폴링 구현)은 **에이전트 재량**이다. 다만 이 계약은 타입으로 막히는 함정이 여럿이라(§3 enum 오탈자, §1.1 `detail` 배열/문자열 분기, §2.4 `current_step` 0-based) TypeScript가 유리하다 — **힌트지 강제가 아니다.**

## 4. 절대 하지 말 것

- 수율 `points`에 ×100 재적용 (§1 비율 스케일 — 서버가 이미 적용)
- 응답 키를 camelCase로 재변환 (§1 필드 네이밍 — snake_case 그대로 사용)
- `current_step`을 1-based로 읽기 (§2.4 — `steps`의 0-based 인덱스)
- `wafer_id` 문자열/사전식 정렬 (§2.6 — `"10"`이 `"2"` 앞에 온다)
- `die_map_url`에 Base URL 이중조립 (§2.6 — 값에 `/api/v1`이 없다)
- `detail`을 무조건 문자열로 렌더 (§1.1 — 422만 배열, `[object Object]` 버그)
- `hypotheses[]` 프론트 재정렬 (§2.5 정렬 불변식 — index 0이 대표)
- 열린 문자열(`top_cause`·`logs[].tool`) 하드코딩 (§2.2·§2.4 — raw id fallback 필수)
- 빈 결과·`insufficient`·`unmapped`를 에러로 (§3.1 핵심원칙 1 — 전부 200)
- 배치 실행 실패를 500으로 (§3.1 핵심원칙 2 — `200 + status:"failed"`)
- status별로 응답 키 집합을 다르게 (§2.4·§2.5 필드표 — 키는 항상 동일, 값만 null)
- 이벤트 시각에 `now()` 사용 (§1 — 고정 기준일 `2026-04-01`, `EVENT_DATE` 상수)
- `verdict_reason` 자연어 본문을 매칭해 `insufficient` 판정 (§2.7 — 고정 사유 토큰으로만 분기)

## 5. `steps[]` 8키 ↔ 현재 코드 노드 매핑

§2.4 `steps[]`는 8키지만 현재 코드는 ⓪~⑥ 7노드다. 명세 순서는 **분류 → 그룹화 → 서술**이고, `vlm_describe`는 §2.5 `description`(= **그룹 대표** 자유서술)을 만드는 단계라 정의상 `grouping` 뒤여야 성립한다. 코드의 `vlm.py`는 분류와 **웨이퍼 1장 단위** 서술을 그룹화 전에 함께 끝내는데, 이 웨이퍼 단위 서술은 `vlm_describe`가 아니다. 임의 매핑 금지 — 아래를 따른다.

| `steps[]` 키 | 코드 노드 | 파일 | 비고 |
|---|---|---|---|
| `lot_selection` | ⓪ `select_low_yield_lots` | `nodes/lowyield.py` | 1:1 |
| `cnn_classify` | ① `read_wafer_maps`(분류 부분) | `nodes/vlm.py` | 패턴 `"Center"` 하드코딩, CNN/VLM 미연동 |
| `grouping` | ② `group_by_pattern` | `nodes/grouper.py` | 1:1 |
| `vlm_describe` | **대응 노드 없음** | — | 그룹 대표 서술(§2.5 `description`)을 만드는 단계인데 그런 노드가 없다. `vlm.py`가 내는 서술은 **웨이퍼 1장 단위**(`state.py:28`)라 이 키가 아니다 → `BACKEND_GAP.md` A표 `description` 행 |
| `cause_lookup` | ③ `fetch_graphrag_candidates` | `nodes/graphrag.py` | 1:1 (빌드타임 결과 조회) |
| `hypothesis` | ④ `build_hypotheses` | `nodes/hypothesis.py` | 1:1 |
| `critic` | ⑤ `review_hypotheses` | `nodes/critic.py` | 1:1 |
| `response_gen` | ⑥ `generate_response` | `nodes/response.py` | 1:1 |

**대응되는 코드가 없는 것 둘**: ⑴ 위 `vlm_describe`, ⑵ 진행 상태 방출 자체. `graph.py`에는 `current_step`·`logs`를 외부로 내보내는 훅이 전혀 없고(`ainvoke` 후 최종 상태만 반환), `main.py`도 배치를 동기로 돌린다. §2.4를 구현하려면 이 방출 경로를 새로 만들어야 한다.

→ 백엔드 갭 전체 목록: **[`docs/BACKEND_GAP.md`](BACKEND_GAP.md)**
