# 웨이퍼 결함 RCA 대시보드 — API 명세서

> **버전** `v1.0` · **작성일** 2026-07-16
> **대상 시스템** React+Vite 프론트엔드 ↔ FastAPI 백엔드 (REST)
> **근거 문서**: `기획안_v1.5.md`, `아키텍처 및 컴포넌트 설계_v1.0.png`

> 변경 이력·설계 논의 과정은 별도 문서 `API_CHANGELOG.md` 참조.

---

## 1. 공통 규약 (Conventions)

| 항목 | 값 | 비고 |
|---|---|---|
| Base URL | `http://localhost:8000/api/v1` | |
| 데이터 형식 | `application/json` (UTF-8) | 웨이퍼맵 이미지만 예외(아래 참조) |
| 날짜 형식 | ISO 8601 (`2026-07-06T09:02:00Z`) | 시각 두 종류 구분(아래). **예외 1건**: 2.4 `logs[].time`은 `HH:MM:SS` |
| 페이지네이션 | offset 기반 `?limit=&offset=` (기본 `limit=10`, `offset=0`). `count`는 전체 총계 | 2.2 `GET /analyses`에 적용 |
| 비율 스케일 | 수율(`points`)은 `0~100` 정수, 그 외 비율(`ratio`·`normal_ratio.value`)은 `0~1` 소수 | 표시 % 변환 규칙은 아래 |
| CORS | 개발 오리진 `http://localhost:5173`(Vite) 허용, 메서드 `GET`/`POST` | 서버 미들웨어(`CORSMiddleware`) 처리 |
| 필드 네이밍 | JSON 키·쿼리 파라미터 모두 **snake_case** (`analysis_id`·`defect_pattern`·`next_actions`) | URL 경로 세그먼트는 kebab-case(`/yield-summary`·`/die-map`), enum **값**은 별도 규칙(아래) |

> **필드 네이밍(snake_case)** — 프론트가 응답 키를 변환 없이 그대로 쓰기 위한 규약이다.
> - **snake_case 적용**: 모든 요청/응답 JSON 키, 쿼리 파라미터(`limit`·`offset`·`sort`), path 파라미터명(`lot_id`·`wafer_id`·`hypothesis_id`).
> - **적용 안 함**: ⑴ URL 경로 세그먼트는 kebab-case(`/yield-summary`·`/die-map`), ⑵ enum **값**은 각 필드의 정의(3장)를 따른다 — `pattern`/`defect_pattern`은 데이터셋 라벨 표기 그대로(`Center`·`Edge-Ring`·`Unknown`·`Normal`), 그 외 enum 값은 소문자 snake(`semi_auto`·`not_collected_for_tier`).
> - 프론트는 응답 키를 camelCase로 재변환하지 않는다(변환 계층을 두면 문서의 키와 코드의 키가 갈라진다).

> **비율 스케일** — 필드마다 스케일이 달라 표시 변환 시 주의한다.
> - **수율(`points`, 2.1)**: `0~100` 정수. 서버가 DB 원값(`0~1`)에 **×100을 이미 적용**해 내려주므로 **프론트는 ×100을 재적용하지 않는다**.
> - **그 외 비율(`ratio`·`normal_ratio.value`, 2.7)**: `0~1` 소수(원값). 표시용 % 변환은 **프론트 몫**이다(`0.65` → "65%").
> - 각주: `normal_ratio.caption`은 이미 "정상 65%"처럼 완성된 **표시 문장**이라 `value`(`0.65`)와 스케일이 다르다 — `caption`은 그대로 출력하고 `value`만 변환한다.

> **시각(timestamp)은 두 종류로 구분한다** — 형식은 둘 다 ISO 8601이지만 출처·의미가 다르다.
> - **데이터축 시각**: 데이터셋 타임라인에 속한 값. Fab 데이터의 `ts`(예: `metric_series.ts`, lot 처리 시각)에서 온다. 시뮬레이터 캔드 데이터라 현재는 가상 기점(`EPOCH=2026-01-01`)부터 90일 구간에 고정돼 있다. "최근 N일" 같은 데이터 조회 창은 벽시계가 아니라 이 축의 `max(ts)` 기준으로 계산한다. → 예: `yield-summary`의 7일 창, lot/웨이퍼 시각, 근거의 telemetry·alarm 시각.
> - **이벤트/조회 시각**: 사용자 동작으로 발생하는 값. 데이터 신선도가 아니라 "언제 일어났나/조회했나"를 뜻한다. → 예: `batch_id`·`analysis_id`에 박히는 **배치 실행일**(`batch_{배치날짜}_{순번}`·`grp_{패턴}_{배치날짜}_{순번}` — 데이터가 아니라 배치라는 이벤트에 이름을 붙인 것), 폴링 시각. **기준일은 서버 `now()`(벽시계)가 아니라 고정일 `2026-04-01`**(데이터축 90일 구간 직후)이며, 시·분·초만 실제 실행 시각을 쓴다.
> 필드마다 어느 축인지 헷갈리면 이 규약을 기준으로 한다.
>
> **고정 기준일(`2026-04-01`) 적용 범위**
> - 적용: `batch_id`/`analysis_id`의 `{배치날짜}`(항상 `20260401`), 배치 시작 시각의 날짜, `logs[].time`이 파생하는 날짜(2.4), 그 밖의 "지금" 기반 이벤트/조회 시각.
> - 미적용: 데이터축 시각 전부(계속 `max(ts)` 기준).
> - 결과: `{순번}`이 실질적 유일 discriminator다 — 실제 실행일이 며칠에 걸쳐도 ID는 `batch_20260401_01`·`_02`·`_03`…으로 누적된다(`{순번}`은 "그날의 배치 순번"이 아니라 "고정 기준일 위의 배치 순번"으로 읽는다. 2.2·2.3·3장 유니크 규칙은 그대로 유효).
> - 이 고정값은 데모 전용이므로 서버 설정 한 곳(`EVENT_DATE` 상수)에 두고, 실데이터 전환 시 `now()`로 되돌린다.

### 1.1 공통 상태 코드 · 에러 형식
모든 4xx/5xx 응답은 `detail` 키를 갖는다. (FastAPI 기본 형식)

| 코드 | 의미 | 사용 예시 | `detail` 예시 |
|---|---|---|---|
| 200 | 성공(조회) | 목록/상세 조회 | — |
| 202 | 접수됨(비동기 시작) | 배치 분석 실행 요청 | — |
| 404 | 없음 | 존재하지 않는 analysis_id | `"detail": "'grp_edgering_20250101_01' 분석을 찾을 수 없습니다."` |
| 409 | 충돌 | 실행 중인 배치가 있거나, 이미 완료된 배치가 있는데 또 실행 요청 | `"detail": "이미 진행 중인 배치가 있습니다."` / `"detail": "기존 완료된 분석이 있습니다."` |
| 422 | 검증 실패 | FastAPI 유효성 검사 실패(타입/허용값) | `"detail": [{"loc": ["query","sort"], "msg": "...", "type": "..."}]` |
| 500 | 서버 오류 | 에이전트 실행 실패 | `"detail": "서버 내부 오류가 발생했습니다."` |

> **`detail`은 두 형태다** — **`422`는 배열**(`[{loc, msg, type}]`, FastAPI 자동 검증 결과), **그 외 4xx/5xx는 문자열**이다. 프론트는 `Array.isArray(detail)`로 분기해 `422`는 `loc`/`msg`를 조합해 표시하고, 나머지는 문자열을 그대로 표시한다. `detail`을 무조건 문자열로 렌더하면 `422`에서 `[object Object]`가 나온다.

---

## 2. 엔드포인트 명세

### 2.1 `GET /yield-summary` — 수율 현황 요약 (화면1)
최근 7일간 수율 추이. 대시보드 진입 시 1회 호출.

**요청** 파라미터 없음. 기간은 **최근 7일 고정**(화면1에 기간 선택 UI 없음 → `?days` 파라미터는 두지 않음).

**응답 200**
```json
{
  "series": [
    { "name": "low_yield_eq", "points": [80, 88, 72, 96, 58, null, 46] },
    { "name": "line_avg",     "points": [64, 65, 62, 64, 61, 62, 60] }
  ]
}
```
- **데이터 출처**: `fab.db`의 `metric_series` 테이블(`metric="yield"`, 장비별 일별 수율). DB `value`는 `0~1`(=`1 − 장비·날짜 defect lot 비율`)이므로 응답에선 **×100(0~100 정수)**으로 변환해 내려준다.
- **`points` 타입 = `array of (integer | null)`**: 값이 있는 날은 `0~100` 정수, 데이터가 없는 날은 `null`이다(아래 gap 처리). 위 예시의 `low_yield_eq` 6번째 원소가 그 `null` 케이스다. 프론트는 원소가 정수라고 가정하지 말고 `null`을 방어한다.
- **`series` 계약(개수 가변 · `name` 키 매칭)**: 프론트는 `series[i]` **인덱스가 아니라 `name` 키로 매칭**한다(배열 순서·개수 보장 안 함). `name`은 표시 라벨이 아니라 **시맨틱 키**이며, 한국어 라벨·배지색 매핑은 **프론트 몫**이다. `name` 허용값(enum): `low_yield_eq`(저수율 장비) | `line_avg`(라인 평균).
  - **빈 배열 처리(계약)**: "데이터 없음"은 에러가 아니라 `200 + {"series": []}`로 정의한다(형태 계약). 다만 **현 데모(시뮬레이터) 데이터 특성상 빈 배열은 발생하지 않는다** — 이는 *보장*이 아니라 *현재 관측*이며, 향후 실데이터에선 빈 배열이 나올 수 있으므로 **프론트는 빈 상태 UI를 방어적으로 유지**한다. 단 개별 `points[i]`가 `null`일 가능성은 별개로 남는다(아래 gap 처리).
- **`points` 길이**: **7 고정**(최근 7일). 향후 기간 선택 UI가 생겨 `?days`를 도입하면 길이가 가변이 될 수 있으므로, 프론트는 상수 7을 하드코딩하지 말고 `points.length` 기준으로 렌더한다(지금은 파라미터 없이 7 고정).
- **"최근 7일"의 기준일**: 벽시계 `now()`가 아니라 **데이터셋 최신일(`max(ts)`) 기준** 7일이다. 시뮬레이터 타임라인이 가상 기점(`EPOCH=2026-01-01`)부터 `timeline_days=90`일이라 실제 오늘과 무관하며, `now()`로 쿼리하면 `series`가 빈 배열이 된다. (`simulator/generate.py`·`fab_model.yaml` 확인)
- **`series` 구성은 서버 계산값**: `저수율 장비`(`name: "low_yield_eq"`, 장비별 yield 최저 1개 선정)와 `라인 평균`(`name: "line_avg"`, 그날 장비 yield 평균)은 DB에 저장된 행이 아니다. `metric_series.scope`는 장비(`equipment_id`) 단위뿐이라 서버가 집계해서 만든다. 두 시리즈 모두 `metric_series` **단독 집계**로 도출된다(다른 테이블 조인 불필요) — `라인 평균`은 `GROUP BY ts`의 세로 평균, `저수율 장비`는 `GROUP BY scope`로 최저 장비 선정 후 그 장비의 일별 시리즈.
- **`라인 평균` 정의(계약)**: **장비 단순평균**(`AVG(value)` per day)으로 확정한다. 그날 장비별 처리 lot 수로 가중하는 **가중평균이 아니다**. 가중평균을 쓰려면 lot 수가 `metric_series`에 없어 `lot_history` 조인이 필요하므로, 단순화를 위해 단순평균으로 못박는다.
- **날짜 구멍(gap) 처리**: 실측상 배경 lot 800개(`--n-background`)로 장비별 일일 커버리지가 조밀하다 — **라인 평균은 매일 수십 건이라 gap이 구조적으로 없고**, 저수율 장비 시리즈만 저트래픽 장비(예: ETCH/DEPO 인스턴스 ~3.3 lot/일)일 때 드물게 하루 빠질 수 있다(빈 날 확률 수 %). 빈 날은 **`null`로 채워** `points` 길이 7을 유지한다(보간·재계산 안 함). 프론트는 `null` 지점을 선 끊김/공백으로 렌더. 엣지 케이스라 UI 영향은 미미.

**에러**
- `500` — 수율 데이터 조회 실패(예: `fab.db` 접근 불가)
```json
{ "detail": "수율 데이터를 불러오지 못했습니다." }
```

---

### 2.2 `GET /analyses` — 분석 결과 대기열 (화면1)
분석 완료 결과 누적 목록. 행 클릭 시 상세(2.5)로 이동.

**요청** (query 파라미터, 모두 Optional)
- `?sort=latest|oldest` — `latest`(최신순, 기본값) 또는 `oldest`(오래된순). 생략 시 `latest`. **정렬은 서버가 수행**하며 프론트는 받은 `items` 순서 그대로 렌더한다(정렬 키는 서버 내부값 = `app_state.db`의 배치 실행 시각이라 응답 JSON에 싣지 않는다).
- `?limit=10&offset=0` — 페이지네이션(offset 기반). `limit` 기본값 `10`(배치 1회 최대 결과 4건이 안 잘리도록 여유를 둔 값), `offset` 기본값 `0`.

> **배치 1회 최대 그룹 수 = 4**: 그룹은 결함 패턴별로 1개씩 생기고, 결함 패턴은 `Center`·`Edge-Ring`·`Scratch`·`Unknown` 4종이다(`pattern` enum 5종 중 `Normal`은 정상이라 그룹을 만들지 않는다, 3장). 따라서 한 배치가 만드는 `analysis`는 최대 4건이다.

**응답 200**
```json
{
  "count": 4,
  "items": [
    { "analysis_id": "grp_edgering_20260706_01", "pattern": "Edge-Ring", "lot_count": 8, "top_cause": "etch_nonuniformity",  "status": "reviewed" },
    { "analysis_id": "grp_scratch_20260706_01",  "pattern": "Scratch",   "lot_count": 8, "top_cause": "handling_mechanical", "status": "reviewed" },
    { "analysis_id": "grp_center_20260706_01",   "pattern": "Center",    "lot_count": 8, "top_cause": null,                  "status": "insufficient" },
    { "analysis_id": "grp_unknown_20260706_01",  "pattern": "Unknown",   "lot_count": 6, "top_cause": null,                  "status": "unmapped" }
  ]
}
```
- **`analysis_id` 형식**: `grp_{패턴}_{배치날짜}_{순번}` (예: `grp_edgering_20260706_01`, 순번은 그날 배치 순번 2자리). 같은 Edge-Ring 패턴이라도 **배치 실행마다 다른 ID로 누적**되어 배치별 이력이 각각 보존된다(같은 날 2회차는 `_02`). 배치 날짜·순번이 `analysis_id` 문자열에 내장돼 있어 별도 `batch_id` 필드 없이도 어느 배치 소산인지 식별된다(대기열 화면이 배치ID를 소비하지 않아 응답에서 제외).
- **`top_cause` (열린 문자열 · Nullable)**: **워크플로우 ⑦응답생성**이 지정한 **대표 채택 원인**(= 2.5 `hypotheses[0]`의 cause). 채택 여부(어느 가설이 accepted인지)는 Critic의 `verdict`가 정하지만, 여러 accepted 중 **대표 1개 선정은 Critic이 아니라 응답생성 단계 몫**이다(Critic은 순위를 내지 않음). API는 파이프라인 결론을 전달만 하며 자체 정렬/선정을 하지 않는다. 채택 0개면 `null`.
  - **값 집합은 enum이 아니다.** KG cause id(`etch_nonuniformity`·`handling_mechanical` 등)로, KG 내용에 따라 값이 늘어나는 **열린 문자열**이다. `status`/`pattern`처럼 고정 집합을 나열하지 않으며, **프론트는 값을 하드코딩하지 말고 받은 문자열을 그대로 표시**한다(현재 화면은 cause id 원문을 렌더). 한국어 라벨이 필요해지면 별도 매핑 테이블을 두는 것은 향후 과제.
- **`status` (3종)**: `reviewed`(채택된 가설 있음) | `insufficient`(원인 매핑은 됐으나 Critic이 채택 0개 → 판단 불가·근거부족) | `unmapped`(패턴이 원인 매핑 대상 아님 = `pattern:"Unknown"`). `insufficient`/`unmapped`는 `top_cause`가 `null`.
- **`pattern` (enum 5종, KG 표준 엔티티)**: `Center` | `Edge-Ring` | `Scratch` | `Unknown` | `Normal`. 원인 매핑 대상 3종(`Center`/`Edge-Ring`/`Scratch`) + 비매핑 결함 통합값 `Unknown`(기획안 v1.5 §6.1의 "새로운 결함 패턴" — WM-811K 원 9종 중 `Edge-Loc`·`Loc`·`Donut`·`Near-Full`·`Random`을 단일화) + 정상 `Normal`. CNN/DB가 어떤 표기로 내보내든 FastAPI가 이 5종으로 정규화해 내려준다(비매핑 결함은 고유명 대신 `Unknown`으로 접어 내려줌 — CNN 내부 출력 형식은 계약 밖·FastAPI↔LangGraph 구현 영역). `Unknown`은 `status:"unmapped"`. (3장 enum·3.2 형상 gloss 표와 동일 집합.)
- **`count`**: 필터·페이지네이션 **적용 전 전체 결과 수**(현재 페이지의 `items.length`가 아님). 프론트는 이 값으로 총 페이지 수를 계산한다.
- **필드 존재 계약**: `items[]`의 5개 키(`analysis_id`·`pattern`·`lot_count`·`top_cause`·`status`)는 **항상 존재**한다. `top_cause`만 Nullable(키는 늘 있고 `reviewed`가 아니면 값이 `null`), 나머지는 값이 채워진다.


**응답 200 (결과 없음)** — 에러가 아니라 빈 목록으로 반환한다. 프론트는 "아직 분석된 결과가 없습니다" 안내를 띄운다.
```json
{ "count": 0, "items": [] }
```

**에러**
- `422` — `?sort`에 허용값(`latest`|`oldest`) 외의 값이 온 경우.
```json
{ "detail": [ { "loc": ["query", "sort"], "msg": "unexpected value; permitted: 'latest', 'oldest'", "type": "value_error" } ] }
```
- `500` — 대기열 저장소(`app_state.db`) 조회 실패.
```json
{ "detail": "분석 목록을 불러오지 못했습니다." }
```

---

### 2.3 `POST /batches` — 오늘 판독 배치 실행 (화면1 버튼)
**직전 배치 이후 누적된 저수율 로트**를 대상으로 파이프라인 전체(⓪~⑦)를 1회 실행한다. **오래 걸리므로 비동기**로 접수만 하고 즉시 `batch_id`를 반환한다.

> **실행 빈도 = 1회(확정)**: 배치는 **하루 1회**이며, 이벤트 기준일이 고정일 `2026-04-01`(1장)이라 실질적으로 **완료된 배치가 1건이라도 있으면 이후 실행 요청은 전부 `409`**다. 프론트는 실행 버튼을 비활성화하고 "기존 완료된 분석이 있습니다" 안내와 함께 대기열(화면2)로 유도한다. 재실행이 필요하면 서버 상태 저장소(`app_state.db`)를 초기화한다. `batch_id`의 `{순번}`은 포맷상 예약만 되고(`_02`~) 현 정책에서는 생성되지 않는다.

> **분석 대상 범위 = 누적(확정)**: ⓪저수율 로트 선별의 스코프는 **직전 배치 이후 누적된 저수율 로트**이며, "데이터셋 최신일 1일 창"이 아니다. 서버가 배치 커서(직전 배치 지점)를 보관하고 배치 실행 시 그 이후 구간을 대상으로 전진시킨다 — 배치를 며칠 건너뛰어도 그 사이 로트가 누락되지 않는다. (2.1 `yield-summary`의 "최근 7일"은 화면1 추이 차트 전용 창이라 이 스코프와 무관하다.)

**요청 본문** (비어있음)
```json
{}
```
> **입력이 비어있는 이유(기획안 v1.5)**: 이 시스템은 **자유 질의가 없다**. 분석 대상은 서버가 "직전 누적 저수율 로트"로 자동 결정하고, 질문은 고정 템플릿(`"{패턴} 결함 패턴이 나타나는 근본 원인은 무엇인가요?"`)을 쓴다. 따라서 날짜·질문 등 클라이언트 입력이 필요 없다.

**응답 202**
```json
{ "batch_id": "batch_20260706_01", "status": "running" }
```
- **`batch_id` 형식 — `batch_{배치날짜}_{순번}`**: 날짜 뒤에 배치 순번(2자리, `01`부터)을 붙인다. 이 순번이 **여러 번 실행해도 ID가 충돌하지 않게** 하는 discriminator다. 현 정책(1회 실행)에선 실질적으로 `_01`만 나오지만, 포맷을 지금부터 순번 포함으로 고정해 **추후 "배치 하나 더 생성"을 켜도 프론트 파서를 고칠 필요가 없게** 한다. 이 배치가 만들어내는 그룹들은 같은 순번을 물려받는다(`grp_{패턴}_{배치날짜}_{순번}`). (근거: 3장 유니크 규칙.)

**에러**
- `409` — 두 경우다. **어느 쪽이든 진행 화면 자동 이동은 하지 않고**, `detail` 문자열을 그대로 안내에 쓴다(프론트는 문자열을 파싱해 분기하지 않는다 — 두 경우 모두 "실행 불가"로 동일 처리).
  - 이미 **실행 중인** 배치가 있는 경우(중복 클릭 방지, 버튼 비활성화의 방어용)
  - 이미 **완료된** 배치가 있는 경우(1회 실행 정책)
```json
{ "detail": "이미 진행 중인 배치가 있습니다." }
```
```json
{ "detail": "기존 완료된 분석이 있습니다." }
```
- `500` — 그룹화/에이전트 실행 시작에 실패
```json
{ "detail": "배치 실행을 시작하지 못했습니다." }
```

---

### 2.4 `GET /batches/{batch_id}` — 배치 진행 상태 (화면2)
진행 단계 + MCP 도구 호출 로그. 하루 1회·소수 사용자·데모 안정성을 감안해 **폴링 방식**(프론트가 1~2초마다 반복 GET 호출)으로 간다. SSE 스트리밍(`GET /batches/{id}/stream`)은 로그 실시간성이 중요해질 때 추가하는 **향후 선택지**로 열어둔다.

**응답 200 (진행 중)**
```json
{
  "batch_id": "batch_20260706_01",
  "status": "running",
  "current_step": 5,
  "steps": ["lot_selection", "cnn_classify", "grouping", "vlm_describe", "cause_lookup", "hypothesis", "critic", "response_gen"],
  "logs": [
    { "time": "09:14:01", "tool": "get_lot_history",          "message": "[Edge-Ring] 불량 lot 8건 이력 조회(병렬)", "status": "done" },
    { "time": "09:14:03", "tool": "run_commonality_analysis", "message": "[Edge-Ring] ETCH-01 (CH2) 공통 8/8", "status": "done" },
    { "time": "09:14:05", "tool": "query_telemetry",          "message": "[Edge-Ring/auto] rf_power 상한 초과 → 지지", "status": "running" }
  ],
  "result_ids": null,
  "error": null
}
```
> `steps`는 기획안 v1.5 §7.1 전체 파이프라인 8노드(⓪저수율 로트 선별 → ①CNN 분류 → ②Grouper → ③VLM description 생성 → ④지식그래프(KG) **빌드타임 순회 결과 조회** → ⑤Hypothesis 노드 → ⑥Critic 노드 → ⑦응답생성)를 그대로 노출한다.
> - **`steps[]` 값은 표시 라벨이 아니라 시맨틱 키다.** 서버는 키만 주고, 한국어 라벨 매핑은 **프론트 몫**이다(2.1 `series[].name`·2.2 `top_cause`와 동일 노선). 키↔라벨: `lot_selection`=저수율 로트 선별 · `cnn_classify`=CNN 분류 · `grouping`=자동 그룹화 · `vlm_describe`=VLM 서술 · `cause_lookup`=원인 후보 조회 · `hypothesis`=가설·증거 수집 · `critic`=검증 · `response_gen`=응답 생성. 배열 순서·길이(8)는 서버가 보증하며 프론트는 `current_step`으로 인덱싱한다.
> - **`current_step`은 `steps` 배열의 0-based 인덱스**다(`steps[current_step]`가 현재 단계). 값이 v1.5 파이프라인 노드번호 ⓪~⑦과 일치한다 — 예: `current_step: 5` = `steps[5]` = `"hypothesis"`(프론트 라벨 "가설·증거 수집") = ⑤Hypothesis 노드. **"6번째 단계"(1-based)로 읽지 말 것** — off-by-one 주의. `status:"completed"`면 전 단계 완료를 뜻하며 `current_step`은 마지막 인덱스(`7`)로 둔다.
> - **④는 "검색"이 아니라 "조회"**: v1.5에서 지식그래프(KG)는 빌드타임에 이미 결정적으로 순회를 끝냈으므로(GraphRAG류 동적 기법 미사용), 런타임엔 그래프를 새로 도는 게 아니라 사전 계산된 원인 후보를 **꺼내 볼(조회)** 뿐이다.
> - **`logs`는 MCP 도구 호출 트레이스 — `steps`(진행 바)와는 별개 축이다.** MCP 도구 호출은 **기획안 v1.5 §7.1 기준 ⑤Hypothesis·⑥Critic 노드**에만 나타난다. **`logs[].tool`은 닫힌 enum이 아니라 열린 문자열이다.** 이 두 노드가 부르는 MCP 도구 **8종(T2~T9)**(`SECS GEM MCP 문서_v0.1` §1: `get_lot_history`·`run_commonality_analysis`·`get_normal_lot_ratio`·`query_telemetry`·`get_alarm_history`·`get_maintenance_history`·`detect_change_points`·`get_lot_timeline`) + MCP 미경유 노드명(아래)이 올 수 있다. 서버는 **시맨틱 키를 원문 그대로** 주고 한국어 표시명 매핑은 **프론트 몫**이다(2.1 `name`·2.2 `top_cause`와 동일 노선). 프론트는 값을 하드코딩하지 말고 매핑에 **없는 키가 오면 raw id를 그대로 표시**하는 fallback을 둔다(도구/노드가 늘어도 계약·프론트가 안 깨지게).
>   - T1 `get_wafer_map`은 배치 파이프라인이 아니라 **웨이퍼맵 이미지 엔드포인트 2.6.1**에서 이미지 로드용으로 쓰이므로 배치 `logs`엔 나타나지 않는다.
>   - MCP를 거치지 않는 노드 내부 오류만 예외적으로 노드명(예: `critic`)으로 표기한다.
> - **tier(검증등급) 참고 조건부 호출**(⑤Hypothesis 노드 — LLM 에이전트가 tier를 **참고해** 후보별 도구 호출 여부·순서를 스스로 판단): `auto`→통상 `query_telemetry`(즉시 채택/기각), `semi_auto`→통상 `get_maintenance_history`·`lot_history.recipe_id`(사람 판정), `none`→통상 MCP 호출 없음(문헌 서술만). tier는 강제 게이트가 아니라 기본 힌트이므로, 에이전트 판단에 따라 이 매핑과 다르게 호출할 수 있다. 단 `run_commonality_analysis`·`get_normal_lot_ratio`는 tier와 무관하게 모든 candidate 공통 호출이며 에이전트 자율 판단 대상이 아니다.
> - **`status`(배치 진행, enum 3종)**: `running`(진행 중·폴링 계속) | `completed`(완료·폴링 종료, `result_ids` 포함) | `failed`(실행 중 오류·폴링 종료, `error` 포함). **이 3종이 전부다.**
> - **`logs[].status`(도구 호출 단위, enum 3종)**: `done`(완료) | `running`(진행 중) | `error`(해당 호출 실패). **이 3종이 전부다.**
> - **`logs[].time`은 §1 ISO 8601 규약의 명시적 예외**다: 날짜·타임존 없는 `HH:MM:SS`이며, **날짜는 `batch_id`의 배치일**(`batch_{배치날짜}_{순번}`)**에서 파생한다**. 배치가 하루 1회라 날짜 모호성이 없어 이 축약을 허용한다(다른 시각 필드 — 2.7 `ts`·`t0` 등 — 은 전부 ISO 8601 Z 정합). 프론트는 이 값을 ISO 파서로 강제 파싱하지 말고, 완전한 시각이 필요하면 `batch_id` 날짜와 결합한다.

**응답 200 (완료)** — `status: "completed"`. `current_step`은 마지막 인덱스(`7`), `result_ids`에 이번 배치 소산 그룹이 담긴다. 이 ID들이 곧 대기열(2.2)에 쌓이는 `analysis_id`다(포맷 `grp_{패턴}_{배치날짜}_{순번}`, 2.2·2.5와 동일).
```json
{
  "batch_id": "batch_20260706_01",
  "status": "completed",
  "current_step": 7,
  "steps": ["lot_selection", "cnn_classify", "grouping", "vlm_describe", "cause_lookup", "hypothesis", "critic", "response_gen"],
  "logs": [
    { "time": "09:14:05", "tool": "query_telemetry", "message": "[Edge-Ring/auto] rf_power 상한 초과 → 지지", "status": "done" },
    { "time": "09:14:11", "tool": "critic",          "message": "[Edge-Ring] 시간정합·반대근거 통과 → 채택", "status": "done" }
  ],
  "result_ids": ["grp_edgering_20260706_01", "grp_center_20260706_01", "grp_scratch_20260706_01", "grp_unknown_20260706_01"]
}
```

**응답 200 (실패)** — 배치 자체는 존재하지만 에이전트 실행이 중단된 경우. HTTP는 200이되 `status`로 실패를 표현한다(폴링 중이므로).
```json
{
  "batch_id": "batch_20260706_01",
  "status": "failed",
  "current_step": 6,
  "error": "검증 단계에서 Neo4j 연결이 끊겼습니다.",
  "logs": [ { "time": "09:14:20", "tool": "critic", "message": "검증 노드 KG(Neo4j) 연결 끊김 — 시간정합 재확인 중단", "status": "error" } ]
}
```

**에러**
- `404` — 존재하지 않는 batch_id. `{ "detail": "'batch_00000000_01' 배치를 찾을 수 없습니다." }`

> **설계 노트**: "배치 실행이 실패한 것"과 "요청이 잘못된 것"을 구분한다. 없는 ID 조회는 `404`(위), 실행 중 오류는 위처럼 `200 + status:"failed"`. 폴링 화면이 200을 기대하며 계속 호출하기 때문이다. 실패도 HTTP 200 + `status:"failed"`로 주는 것은 "내부 실패는 `500`"이라는 일반 원칙(3.1 원칙 ④)에 대한 **의도적 예외**다(실패도 폴링 응답이라 200으로 받아 body `status`로 표현). 조회 요청 자체가 처리 불가할 때만 여전히 `500`.

> **필드 존재 계약(2.4 세 응답 공통)** — 세 status(`running`/`completed`/`failed`)는 **키 집합이 동일한 superset**이며 해당 없는 값은 `null`이다(discriminated union 아님, Pydantic 모델 1개로 수렴 — 2.5와 동일 노선). 폴링 파서는 매 응답 `status`로 분기하고 나머지는 널 방어만 하면 된다.
>
> | 필드 | running | completed | failed | 규칙 |
> |---|---|---|---|---|
> | `batch_id` · `status` | ✔ | ✔ | ✔ | **항상 존재** |
> | `current_step` | 현재 단계 인덱스 | `7`(마지막) | 중단된 단계 | **항상 존재** |
> | `steps` | ✔ | ✔ | ✔ | **항상 존재**(고정 8키) |
> | `logs` | ✔ | ✔ | ✔ | **항상 존재**, 시작 순간엔 `[]` |
> | `result_ids` | `null` | 배열 | `null` | Nullable — `completed`에서만 값 |
> | `error` | `null` | `null` | 문자열 | Nullable — `failed`에서만 값 |
>
> - `result_ids`는 완료 전 **`null`이지 `[]`가 아니다** — `[]`("결과 0건")와 "아직 없음"을 구분한다. 반면 `logs`는 실제 리스트라 시작 시 `[]`.
> - 위 예시 JSON들은 지면상 일부 필드를 생략했다(해당 status에 무관한 널 필드 예 `result_ids:null`·`error:null`, 및 진행바 필드 예 실패 예시의 `steps`). **실제 응답은 status와 무관하게 항상 위 7개 키를 모두 포함**한다.

---

### 2.5 `GET /analyses/{analysis_id}` — 분석 결과 상세 (화면3)
가설 카드 · Critic · 인용 · 소속 로트 · 권장 조치. 대시보드에서 각 행 상태 버튼 클릭 시 호출.

> **전제 — 항상 종료상태만 반환**: 그룹 `status`는 `reviewed | insufficient | unmapped` 3종뿐이며 "진행중" 상태는 없다. 아직 분석 중인 그룹은 **2.2 대기열에 노출되지 않아** 화면3에서 클릭 대상이 되지 않으므로, 2.5는 분석이 끝난 그룹만 조회한다. (배치 진행 상태는 2.4 소관.)

**응답 200 (판독 성공 · `status: "reviewed"`)**
```json
{
  "analysis_id": "grp_edgering_20260706_01",
  "pattern": "Edge-Ring",
  "description": "웨이퍼 가장자리를 따라 폭이 비교적 일정한 고리형 불량대가 관찰되며, 중심부는 대체로 정상입니다.",
  "status": "reviewed",
  "reason": null,
  "lot_count": 8,
  "lot_ids": ["lot23844", "lot44793", "lot6092", "lot11527", "lot38210", "lot50974", "lot7365", "lot42088"],
  "hypotheses": [
    {
      "hypothesis_id": "h0",
      "cause": "etch_nonuniformity",
      "stage": "ETCH",
      "tier": "auto",
      "verdict": "accepted",
      "verdict_reason": null,
      "narrative": "8개 로트 전부가 ETCH-01(CH2)를 통과했고, rf_power가 정상범위 상한을 넘어 step-up drift를 보였습니다...",
      "next_actions": ["ETCH-01 CH2 rf_power 상한 드리프트 점검", "포커스링(소모품) 교체 이력 확인"],
      "citations": [{ "id": 1, "text": "Wang et al., IEEE Trans. Semiconductor Manufacturing 2020" }]
    },
    {
      "hypothesis_id": "h1",
      "cause": "cmp_edge_overpolish",
      "stage": "CMP",
      "tier": "semi_auto",
      "verdict": "rejected",
      "verdict_reason": "P3 반대근거 기각 — 정상 로트 대조에서 CMP-01 통과 로트 65%가 정상이라 원인 지지 약함",
      "narrative": "일부 로트(3/8)만 CMP-01 공통, down_force 신호도 약합니다.",
      "next_actions": [],
      "citations": [{ "id": 4, "text": "Kim et al., J. Manufacturing Systems 2022" }]
    }
  ]
}
```
- **`description` (VLM 자연어 서술 · Nullable)**: **③VLM 노드가 그룹 대표 패턴에 대해 생성한 자유서술 문장**이다(기획안 v1.5 §4 기능4·노드③의 최소구현 산출물). 화면3의 그룹 서술로 그대로 노출한다. 이 값은 **LLM 생성물이라 배치 실행마다 문구가 달라질 수 있고**, 프론트는 내용을 파싱하지 말고 문장 그대로 표시한다.
  - **결정적 gloss 조립값과 혼동 금지**: 프론트가 `pattern`·`stage`로 조립하는 한 줄 요약은 이것과 **별개의 값**이며, 이름도 `summary_line`으로 구분한다(상수표·조립 규칙·fallback은 **부록 3.2(프론트 파생 표시값, 비계약)** 참조). `description`이 `null`이면 프론트는 `summary_line`으로 fallback한다.
  - 🔲 **백엔드 확인(4장)**: 현재 백엔드 `VLMResult`(`state.py:21`)의 `description`은 **웨이퍼 1장 단위**라, 그룹 대표 서술을 무엇으로 삼을지(대표 웨이퍼 선정 vs 그룹 단위 재생성)가 미정이다. 또 VLM은 아직 실제 모델 미연동(패턴 하드코딩) 상태다. 확정·연동 전까지 `description`은 `null`일 수 있으며, 그동안 화면3은 `summary_line` fallback으로 동작한다.

- **`tier` (검증등급)**: `auto`(자동·즉시 채택/기각까지) | `semi_auto`(반자동·사람 판정 필요) | `none`(근거없음·문헌 서술만, MCP 증거 없음)
  - 🔲 **`semi_auto` 판정 처리(잠정·결정 필요)**: 반자동 등급의 사람 판정 시나리오가 아직 정립되지 않아, **현재는 Critic이 자동으로 기각(`rejected`)** 처리한다(위 `cmp_edge_overpolish` 예시). 추후 사람 판정 경로/시나리오가 정해지면 `verdict`가 미확정 대기 등으로 **변동될 수 있다**. ⤷ 4장 미결정 "`semi_auto` 사람 판정 결과 API 수신 경로"와 연동 — 그 엔드포인트가 생기면 이 잠정 처리(자동 기각)를 걷어낸다.
- **`verdict` (Critic 판정)**: `accepted`(채택) | `rejected`(기각) | `insufficient`(근거부족) — 비채택 사유는 `verdict_reason`이 담는다
  - **`verdict_reason` (비채택 사유, Nullable)**: `accepted`이면 `null`, `rejected`/`insufficient`이면 문자열. 값은 기획안 v1.5 Critic Workflow(§7.2) 규칙에 대응한다 — `rejected`는 ①시간 선후(P2)·②반대근거(P3, `get_normal_lot_ratio`)·③faithfulness, `insufficient`는 ④KG 메커니즘 연결 없음(P5).
- `stage` (공정, 고정 6종 **또는 `null`**): `LITHO` | `ETCH` | `DEPO` | `CMP` | `CLEAN` | `EDS` | `null`
  - **출처**: 각 `cause`가 KG(`kg_rca`/Neo4j)에서 매달린 **`ProcessStep` 노드값**(`hypotheses.json`의 `path.step`)이다. 기획안 v1.5 §6.2 스키마 `DefectPattern→ProcessStep→FailureMode→Cause→Evidence`에서 `ProcessStep`은 **고정 vocabulary 6종**(fab.db `EQUIPMENT.step_group`과 동일 집합). ④지식그래프(KG) 조회 시 candidate가 `cand.step`으로 이미 달고 나오고(§7.2 `suspect = top_equipment_for(comm, cand.step)` — stage로 장비를 찾는 것이지 장비에서 역산하지 않음), ⑤Hypothesis·⑥Critic·API는 전달만 한다. 빌드타임에 확정되는 그래프 구조 속성이라 fab.db·장비에서 계산하는 값이 아니다(데이터 모델 §3 Hypothesis 저장소 = Neo4j와 일치).
  - **`null` 가능**: 문헌직결 후보(`path.step` 없음)는 `stage: null`이다(`KG_output_명세.md:50`). 이 필드는 **가설 카드 표시용**이며, 프론트가 파생하는 한 줄 요약(부록 3.2)의 공정 조각 입력으로도 쓰인다. `stage=null`(실측 6~9%, 순위 꼬리)이면 그 요약은 "공정 미상"으로 fallback한다.
  - 🔲 **백엔드 확인(4장)**: 백엔드 `Hypothesis`(`state.py:90`)에는 현재 `stage`/`step` 필드가 없다(`equipment`만 있음). ⑤에서 `cand.step`을 `Hypothesis`에 실어주면 카드 `stage`가 채워진다(API가 `cause`로 ④ 후보에 재조인하는 대안도 있으나 전자가 간단). 프론트 파생 요약(부록 3.2)의 공정 조각도 이 값을 공유하므로 함께 해소된다.

**응답 200 (판단 불가·근거부족 · `status: "insufficient"`)** — 원인 후보는 매핑돼 있으나 Critic이 **채택 가능한 후보를 하나도 못 찾은** 경우(재시도 없이 즉시 반환). 후보 목록(`hypotheses`)은 있으나 전부 `verdict`가 `rejected`/`insufficient`다.
> **`status:"insufficient"`는 "채택 0개"의 세 하위 경우를 모두 포함한다**(기획안 v1.5 §7.1 "채택 후보 0개 → 즉시 `insufficient_evidence`"): ⓐ 전부 `rejected`(①시간정합·②반대근거·③faithfulness로 반박), ⓑ 전부 `insufficient`(④KG 메커니즘 없음), ⓒ 둘의 혼합. 세 경우 응답 형태는 동일하며(전부-reject라고 별도 status를 두지 않음), 반박이냐 근거부족이냐의 구분은 그룹이 아니라 **가설별 `verdict`/`verdict_reason`**이 담는다.
```json
{
  "analysis_id": "grp_center_20260707_01",
  "pattern": "Center",
  "description": "웨이퍼 중심부에 원형으로 집중된 불량 밀집이 보이며, 가장자리로 갈수록 옅어집니다.",
  "status": "insufficient",
  "reason": "매핑된 원인 후보는 있으나 시간 정합·정상 로트 대조에서 채택 가능한 후보가 없어 판단 불가(근거부족).",
  "lot_count": 8,
  "lot_ids": ["lot30112", "lot30988", "lot31544", "lot32077", "lot32610", "lot33291", "lot33845", "lot34120"],
  "hypotheses": [ { "hypothesis_id": "h0", "cause": "clean_nozzle_clog", "stage": "CLEAN", "tier": "auto", "verdict": "insufficient", "verdict_reason": "KG 메커니즘 연결(VERIFIED_BY) 없음", "narrative": "...", "next_actions": [], "citations": [{ "id": 7, "text": "Lee et al., Microelectronics Reliability 2021" }] } ]
}
```

**응답 200 (원인 매핑 없음 · `status: "unmapped"`)** — 패턴 자체가 원인 매핑 대상이 아님(`pattern:"Unknown"`). `hypotheses: []`이고, 판독은 됐으므로 `lot_count`/`lot_ids`는 채워진다. **판단 불가·매핑 없음 모두 에러가 아니라 정상 200이다.**
```json
{
  "analysis_id": "grp_unknown_20260706_01",
  "pattern": "Unknown",
  "description": "웨이퍼 전반에 뚜렷한 형상 없이 산발적으로 흩어진 불량이 관찰됩니다.",
  "status": "unmapped",
  "reason": "이 결함 패턴은 원인 매핑 데이터가 없어 판독까지만 지원됩니다.",
  "lot_count": 6,
  "lot_ids": ["lot40233", "lot41002", "lot41776", "lot42501", "lot43188", "lot43920"],
  "hypotheses": []
}
```

> **필드 존재 계약(2.5 세 응답 공통)** — 세 status는 **키 집합이 동일한 superset**이며 해당 없는 값은 `null`이다(discriminated union 아님, Pydantic 모델 1개로 수렴). ⓐ `description`(VLM 자연어 서술)은 **세 status 모두 키가 존재**하되 **Nullable**이다 — 판독(①~③)은 세 status 모두에서 끝났으므로 값이 담기며, VLM 미연동·생성 실패 시에만 `null`이다(그때 프론트는 부록 3.2 `summary_line`으로 fallback). ⓑ `reason`은 결과 없음(`insufficient`/`unmapped`)일 때만 값이 있고 `reviewed`는 `null`이다. ⓒ `lot_count`/`lot_ids`는 **세 status 모두 존재**한다 — unmapped도 패턴으로 묶인 형성된 그룹이라 로트를 가진다(2.2 대기열이 unmapped에도 `lot_count`를 주는 것과 정합). ⓓ `hypotheses[]`는 `reviewed`/`insufficient`엔 후보가 담기고(채택/기각·근거부족), `unmapped`는 `[]`다. `top_cause`(2.2)는 `reviewed`만 값, 나머지는 `null`.

> **`hypotheses[]` 배열 정렬 불변식** — `reviewed`면 **`hypotheses[0]`은 ⑦응답생성이 선정한 대표 accepted 후보**다. 배열은 ⑦이 **대표 우선으로 정렬해** 내려주며, 프론트는 **받은 순서를 신뢰**하고 재정렬하지 않는다. 2.2 `top_cause`(= `hypotheses[0].cause`)와 부록 3.2 한 줄 요약이 이 원소를 대표로 소비하므로, 이 불변식이 곧 두 파생값의 재현성 근거다. 여러 accepted 중 **무엇을 대표로 뽑는지(선정 규칙)는 ⑦ 소관**이며 API 계약이 규정하지 않는다(4장 미결정 "대표 원인 지정 로직" 연동) — 계약이 보장하는 것은 "index 0에 대표가 온다"까지다. `hypothesis_id`의 `h{n}` 부여도 이 정렬이 확정된 **뒤** 이뤄진다.

> **가설 원소(`hypotheses[]`) 필드 계약** — 원소도 키 집합이 고정이다. `hypothesis_id`·`cause`·`stage`·`tier`·`verdict`는 **항상 존재**(`stage`만 `null` 가능), `verdict_reason`은 위 규칙(`accepted`=`null` / 그 외 문자열). `hypothesis_id`(형식 `h{n}`, 그룹 내 가설 배열 인덱스 0-based)는 서버가 배치 실행 시점에 부여하는 **URL-안전 고유 id**로, 화면3 "근거 보기"가 2.7(`GET /analyses/{analysis_id}/evidence/{hypothesis_id}`)을 호출하는 드릴다운 키다. `narrative`는 **항상 문자열**(기각·근거부족 후보라도 서술은 채운다). `next_actions`는 **항상 존재하는 배열**이며 조치 없으면 `[]`(키 생략 아님). `citations`는 **`array<{id:int, text:string}>`** — 인용이 있으면 원소가 담기고(1건이어도 배열), 없으면(예: `tier:"none"`, MCP 증거 없음) **`[]`**다(`null`을 쓰지 않는다). **2.7 `citations`와 필드명·원소타입·빈값 규약이 동일**하므로 2.5→2.7 드릴다운 시 같은 인용 렌더러를 재사용한다.

> **`batch_id`는 2.5 응답에 없다** — 배치 역참조가 필요하면 `analysis_id`의 `{배치날짜}_{순번}`으로 `batch_id`(`batch_{배치날짜}_{순번}`)를 복원한다(값이 100% 복원되므로 중복 필드를 두지 않음). MVP엔 결과→배치 화면이 없고, 생기면 additive로 재추가한다.

**에러**
- `404` — 존재하지 않는 analysis_id(대기열에 없는 그룹).
```json
{ "detail": "'grp_edgering_20250101_01' 분석을 찾을 수 없습니다." }
```
- `500` — 조회/저장소 접근 실패 등 서버 내부 오류(상세 조회 공통, 3.1 원칙 ④).

---

### 2.6 `GET /lots/{lot_id}/wafers` — 로트 웨이퍼맵 판독 (화면3 로트 클릭)
로트 소속 판독 웨이퍼 목록. CNN 분류 기준(웨이퍼 단위 패턴 분류).

**응답 200**
```json
{
  "lot_id": "lot23844",
  "wafer_count": 25,
  "defect_count": 21,
  "normal_count": 4,
  "wafers": [
    { "wafer_id": "1", "defect_pattern": "Edge-Ring", "die_map_url": "/lots/lot23844/wafers/1/die-map" },
    { "wafer_id": "2", "defect_pattern": "Edge-Ring", "die_map_url": "/lots/lot23844/wafers/2/die-map" },
    { "wafer_id": "3", "defect_pattern": "Edge-Ring", "die_map_url": "/lots/lot23844/wafers/3/die-map" },
    { "wafer_id": "4", "defect_pattern": "Edge-Ring", "die_map_url": "/lots/lot23844/wafers/4/die-map" },
    { "wafer_id": "5", "defect_pattern": "Normal",    "die_map_url": "/lots/lot23844/wafers/5/die-map" }
  ]
}
```
> 예시는 상위 5장만 표시. 실제 `wafers[]`에는 **그 로트의 판독 웨이퍼 전량**이 담긴다. **로트당 웨이퍼 수는 가변(1~25장)이며 25장 미만인 로트가 다수다** — 25장 고정으로 가정하면 안 된다(그리드 슬롯 25칸 고정 렌더 금지, `wafers.length`에 맞춰 렌더). `wafer_count`/`defect_count`/`normal_count`는 예시에 보이는 5장이 아니라 **해당 로트 전량 기준**이라, 위 예시에 한해 `wafers.length`(5)와 `wafer_count`(25 — 25장짜리 로트를 가정한 값)가 다르다 — **실제 응답에서는 아래 항등식대로 일치한다.**

**id 형식 · die-map 경로**
- **`lot_id` = 원본 데이터셋 `lotName` 그대로** (`str`, `lot#####` 형식, 예 `lot23844`). path 파라미터로 받은 값을 응답에 echo.
- **`wafer_id` = 로트-로컬 웨이퍼 인덱스의 정수 문자열** (`str(int(waferIndex))`, `"1"`~`"25"` 범위, **로트당 장수는 1~25장 가변**이고 25장은 상한이지 고정값이 아니다). **전역 유니크가 아니다** — 로트마다 `"1"`이 존재한다.
- 따라서 die-map은 전역 라우트(`/wafers/{wafer_id}`)가 아니라 **로트 종속 경로**다: `die_map_url` = `/lots/{lot_id}/wafers/{wafer_id}/die-map`.

**웨이퍼맵은 이미지 방식으로 제공한다**(위 응답의 `die_map_url`이 그 예시).

- **`die_map_url` = Base URL 없는 경로**: 서버는 **Base URL 성분(`/api/v1` 포함)을 뺀 경로**(`/lots/{lot_id}/wafers/{wafer_id}/die-map`)만 내려준다. 절대 URL 조립은 **프론트 몫**이며 **1장 Base URL(`http://localhost:8000/api/v1`)과 결합**한다 → `http://localhost:8000/api/v1/lots/lot23844/wafers/1/die-map`. 환경(localhost/배포)별로 호스트가 바뀌어도 응답이 안 깨지게 하기 위함. **`die_map_url` 값에는 `/api/v1`이 들어있지 않다** — 값에 이미 들어있으면 Base URL과 결합할 때 `/api/v1`이 이중으로 붙어 전량 404가 된다.
- **`wafers[]` 정렬 = `wafer_id` 정수 오름차순**: 서버가 `wafer_id`를 **정수로 파싱해 오름차순 정렬**해 내려준다(`"1"`,`"2"`,…,`"10"`,`"11"`,…,`"25"`). `wafer_id`가 문자열이라도 **사전식(lexical) 정렬이 아니다** — 프론트는 받은 순서 그대로 렌더하면 되고, 문자열 정렬로 재정렬하면 `"10"`이 `"2"` 앞에 오는 버그가 나므로 하지 않는다.
- **`wafer_count`/`defect_count`/`normal_count` (서버 집계)**: 판독 웨이퍼 총장수 / 불량(`defect_pattern != "Normal"`) / 정상(`== "Normal"`) 장수. **`wafer_count == defect_count + normal_count` 항상 성립**하며 `wafer_count == wafers.length`다. 셋 다 `wafers[]`에서 파생 가능하지만, 화면3 헤더("판독 N장 중 M장 불량")가 쓰므로 서버가 집계해 함께 준다(별도 `is_normal` 없이 `defect_pattern`으로 계산).
- **용어 주의**: 원천 데이터 `wafer.die_map`은 **이미지가 아니라 `0/1/2`(배경/통과/불량) 2D 격자 배열**을 `np.save`한 BLOB이다(`secsgem-mcp/server/db.py`, `simulator/generate.py`). 이미지는 이 격자를 렌더한 **산출물**이지 `die_map` 그 자체가 아니다.
- **신규 렌더링 로직 0**: MCP `get_wafer_map`이 이미 `die_map` 격자를 읽어 **PNG(256×256, base64)로 렌더해서 반환**한다(`preprocess/render.py` → `to_base64_png`). 따라서 백엔드는 그 base64를 **그대로 pass-through** 하거나 디코드해 **`image/png` 바이너리로 재서빙**하기만 하면 되고, 렌더링 코드를 새로 짤 필요가 없다. `die_map_url`(`GET /lots/{lot_id}/wafers/{wafer_id}/die-map`)은 이 "얇은 재서빙 엔드포인트" 하나만 신설하면 성립한다.
- **좌표 배열 안은 보류**: 원천이 밀집 격자라 좌표 리스트로 바꾸는 변환·노출 도구가 코드에 없고(신규 MCP 도구 또는 백엔드의 fab.db 직접 접근이 필요 — 후자는 정답격리 원칙과 충돌), die 단위 hover/클릭 같은 **명시적 인터랙션 요구가 생길 때** 재검토한다(그때 sparse 좌표 반환·라벨 누출 차단이 후속 결정).

> **`defect_pattern` (enum · per-wafer)** — CNN이 웨이퍼별로 분류한 결함 패턴. **2.2/3장 `pattern`과 동일한 5종 집합**이다: `Center` | `Edge-Ring` | `Scratch` | `Unknown` | `Normal`(비매핑 결함 `Edge-Loc`·`Loc`·`Donut`·`Near-Full`·`Random`은 `Unknown`으로 단일화). 그룹 패턴(2.2/2.5)이 그룹 단위인 것과 달리 이건 **웨이퍼 단위**라, 그룹이 `Edge-Ring`이어도 개별 웨이퍼는 `Normal`일 수 있다(위 예시 5번). CNN/DB 표기가 무엇이든 FastAPI가 이 5종으로 정규화한다(2.2와 동일 노선). 정상 판별은 이 값 `== "Normal"`.

> **필드 존재 계약(2.6)** — 최상위 5키(`lot_id`·`wafer_count`·`defect_count`·`normal_count`·`wafers`)와 `wafers[]` 원소 3키(`wafer_id`·`defect_pattern`·`die_map_url`)는 **모두 항상 존재하고 non-null**이다(Nullable·Optional 필드 없음). `defect_pattern`은 늘 5종 중 하나이며 **판독 실패를 `null`로 표현하지 않는다**(필요해지면 additive). `die_map_url`은 항상 문자열이고, 이미지 부재는 URL 누락이 아니라 **그 URL을 조회한 시점의 404**로 나타난다(2.6.1).
>  - **빈 목록 계약**: 존재하는 lot이지만 판독 웨이퍼가 0장이면 에러가 아니라 **`200` + `{"wafer_count":0,"defect_count":0,"normal_count":0,"wafers":[]}`**로 준다(형태 계약). 현 데모는 실제로는 발생하지 않으며, 존재하지 않는 lot_id만 `404`다.

**에러**
- `404` — 존재하지 않는 lot_id.
```json
{ "detail": "'lot00000' 로트를 찾을 수 없습니다." }
```
- `500` — 웨이퍼 목록 조회 실패(저장소 접근 불가 등).
```json
{ "detail": "웨이퍼 목록을 불러오지 못했습니다." }
```

---

### 2.6.1 `GET /lots/{lot_id}/wafers/{wafer_id}/die-map` — 웨이퍼맵 이미지 (2.6 `die_map_url` 대상)

2.6 응답의 `die_map_url`이 가리키는 **얇은 재서빙 엔드포인트**. 이 문서에서 **유일하게 성공 응답이 JSON이 아니라 바이너리(`image/png`)**다. `wafer_id`가 로트-로컬이라 경로에 `lot_id`가 함께 들어간다.

**요청** path 파라미터 `lot_id`·`wafer_id`. 쿼리·본문 없음.

**응답 200** — `Content-Type: image/png`, 본문은 PNG 바이너리(256×256). MCP `get_wafer_map`이 `die_map` 격자(0/1/2)를 렌더한 base64를 백엔드가 디코드해 그대로 재서빙한다(신규 렌더링 로직 없음). 성공 응답은 JSON이 아니다.

**에러** (실패 시에는 1.1 공통 형식대로 JSON `detail`을 반환한다 — 바이너리는 `200`에서만)
- `404` — lot·wafer가 없거나 해당 웨이퍼의 die map 이미지가 없을 때.
```json
{ "detail": "lot23844 로트에 25번 웨이퍼의 die map 이미지가 없습니다." }
```
- `500` — 이미지 디코드/재서빙 실패.
```json
{ "detail": "웨이퍼 이미지를 불러오지 못했습니다." }
```

---

### 2.7 `GET /analyses/{analysis_id}/evidence/{hypothesis_id}` — 근거 상세 (근거 모달)
Commonality / Telemetry / Events(Alarm·Maintenance) 3섹션 + 검증등급·판정·권장조치. 응답은 **메타(판정) + 3섹션 + 부가정보**로 구성되며, 3섹션은 근거 모달의 ①Commonality ②Telemetry ③Events에 1:1 대응한다.

> **드릴다운 키 = `hypothesis_id`**: 2.5 가설 카드에서 "근거 보기"를 누르면 그 가설의 `hypothesis_id`를 path 파라미터로 이 엔드포인트를 호출한다. `hypothesis_id`는 서버가 **배치 실행 시점에 분석 그룹 내에서 부여하는 URL-안전 고유 id**(형식 `h{n}`, n = 그 분석의 가설 배열 인덱스 0-based, 배치 결과가 불변이라 인덱스가 안정적)다. `cause`는 kg_rca가 LLM으로 자유추출한 문자열이라 (ⓐ 공백·슬래시·유니코드로 URL이 깨지고 ⓑ 같은 cause가 서로 다른 path로 중복될 수 있어) path 키로 부적합하며, 응답 body에 표시용으로만 잔류한다(조회 키 아님).
>  - **2.5 연동(필수)**: 이 엔드포인트를 쓰려면 **2.5 응답의 각 `hypotheses[]` 항목에 `hypothesis_id`가 실려야** 프론트가 "근거 보기"에 URL을 걸 수 있다(2.5 가설 원소 계약에 반영).

> **섹션별 `available` 플래그 — 미수집을 `200`으로 표현**: 각 섹션(`commonality`·`telemetry`·`events`)은 `available` 불리언을 가진다. 에이전트의 도구 호출 판단·수집여부에 따라 없는 섹션은 `available:false`+`reason`으로 명시하고(에러 아님·`200`), 프론트는 그 상태를 "미수집/해당없음"으로 렌더한다. `series`·카운트·`ratio`는 **원값**으로 주고 표시 문장은 `caption`으로 분리한다(원데이터/표시문자열 분리).

**`available:false`의 `reason` (enum)**

| reason | 뜻 |
|---|---|
| `not_collected_for_tier` | 에이전트가 tier를 참고해 이 후보에 대해 해당 MCP 도구를 **호출하지 않음**(통상 `auto`는 정비/알람 미조회, `semi_auto`는 telemetry 미조회이나 에이전트 판단에 따라 달라질 수 있어, 프론트는 tier가 아니라 각 섹션의 `available`로 판단) |
| `none_tier` | `none`(근거없음) 등급 — MCP 증거 자체가 없고 문헌 서술만 존재 |
| `no_data_found` | 도구는 호출했으나 해당 구간에 데이터가 없음 (fab.db 커버리지 공백 등) |

**응답 200 (`auto` 등급 · 채택 · 대표 케이스)**
```json
{
  "analysis_id": "grp_edgering_20260706_01",
  "hypothesis_id": "h0",
  "cause": "etch_nonuniformity",
  "stage": "ETCH",
  "tier": "auto",
  "verdict": "accepted",
  "verdict_reason": null,
  "suspect": { "equipment_id": "ETCH-01", "chamber_id": "CH2" },

  "sections": {
    "commonality": {
      "available": true,
      "rows": [
        { "equipment_id": "ETCH-01", "chamber_id": "CH2", "matched_lots": 8, "total_lots": 8, "ratio": 1.0, "note": null },
        { "equipment_id": "LITHO-01", "chamber_id": null, "matched_lots": 8, "total_lots": 8, "ratio": 1.0, "note": "t0 이후 PM — 함정 장비" },
        { "equipment_id": "CLEAN-02", "chamber_id": null, "matched_lots": 2, "total_lots": 8, "ratio": 0.25, "note": null }
      ],
      "normal_ratio": {
        "value": 0.18,
        "caption": "ETCH-01-CH2 통과 로트 중 정상 18% → 원인 지지(반대근거 약함)"
      }
    },
    "telemetry": {
      "available": true,
      "param": "rf_power", "unit": "W",
      "normal_range": [1900, 2100],
      "drift_detected": true,
      "t0": "2026-01-30T04:00:00Z",
      "series": [
        { "ts": "2026-01-28T00:00:00Z", "value": 1985 },
        { "ts": "2026-01-28T12:00:00Z", "value": 2001 },
        { "ts": "2026-01-29T00:00:00Z", "value": 1994 },
        { "ts": "2026-01-29T12:00:00Z", "value": 2010 },
        { "ts": "2026-01-30T00:00:00Z", "value": 2035 },
        { "ts": "2026-01-30T12:00:00Z", "value": 2180 },
        { "ts": "2026-01-31T00:00:00Z", "value": 2240 },
        { "ts": "2026-01-31T12:00:00Z", "value": 2215 }
      ],
      "caption": "t0 이후 상한(2100 W) 초과 step-up drift"
    },
    "events": {
      "available": false,
      "reason": "not_collected_for_tier",
      "rows": []
    }
  },

  "unverified": [
    { "ref": "LITHO-01 PM", "reason": "t0 이후 정비라 근거로 미채택(함정 장비)" }
  ],
  "next_actions": [
    "ETCH-01 CH2 rf_power 상한 드리프트 점검",
    "포커스링(소모품) 교체 이력 확인"
  ],
  "citations": [
    { "id": 1, "text": "Wang et al., IEEE Trans. Semiconductor Manufacturing 2020" }
  ],
  "note": null
}
```
> `auto` 등급은 에이전트가 통상 `query_telemetry`만 부르고 정비/알람은 조회하지 않으므로(⑤Hypothesis LLM 에이전트의 tier 참고 판단) 이 예시의 `events.available:false / reason:"not_collected_for_tier"`가 **정상**이다. 단 에이전트가 필요하다고 판단하면 auto 후보에서도 정비/알람을 호출할 수 있으므로, 프론트는 tier가 아니라 `events.available`로 렌더한다(알람 미연동 관련은 아래 🔲 백엔드 갭 참조).

**응답 200 (`semi_auto` 등급 · 기각)** — 정비 이력 중심. telemetry는 미조회, events는 채워진다.
```json
{
  "analysis_id": "grp_edgering_20260706_01",
  "hypothesis_id": "h1",
  "cause": "cmp_edge_overpolish",
  "stage": "CMP",
  "tier": "semi_auto",
  "verdict": "rejected",
  "verdict_reason": "P3 반대근거 기각 — 정상 로트 대조에서 CMP-01 통과 로트 65%가 정상이라 원인 지지 약함",
  "suspect": { "equipment_id": "CMP-01", "chamber_id": "CH2" },

  "sections": {
    "commonality": {
      "available": true,
      "rows": [
        { "equipment_id": "CMP-01", "chamber_id": "CH2", "matched_lots": 3, "total_lots": 8, "ratio": 0.38, "note": null }
      ],
      "normal_ratio": {
        "value": 0.65,
        "caption": "CMP-01-CH2 통과 로트 중 정상 65% → 원인 지지 약함(반대근거 강함)"
      }
    },
    "telemetry": {
      "available": false,
      "reason": "not_collected_for_tier",
      "series": []
    },
    "events": {
      "available": true,
      "rows": [
        { "ts": "2026-01-25T09:00:00Z", "type": "maintenance", "equipment_id": "CMP-01", "kind": "PM", "detail": "패드 교체" }
      ]
    }
  },

  "unverified": [],
  "next_actions": [],
  "citations": [
    { "id": 4, "text": "Kim et al., J. Manufacturing Systems 2022" }
  ],
  "note": null
}
```
> **`verdict` 매핑 주의(🔲 백엔드 갭)**: 현재 Critic은 그룹 단위 `accepted[]`/`rejected[]` 두 리스트만 낸다. API는 조회된 가설이 어느 리스트에 있는지로 `accepted`/`rejected`를 정하고, `rejected` 중 **KG 메커니즘 연결 실패로 판정된 것**을 `verdict:"insufficient"`로 승격해 내린다(3-state 계약 유지).
> - **승격 판정 앵커**: 이 승격은 `verdict_reason` **자유서술 문자열 본문을 매칭하지 않는다**. Critic/파이프라인이 사유에 **고정 토큰(사유코드, 예 `P5_NO_KG_MECHANISM`)**을 부여하고 API는 그 토큰으로만 분기한다(Critic이 자연어 문구를 바꿔도 배지가 안 깨진다). `verdict_reason` 자연어는 **표시용**이다.
> - **`semi_auto` 최종 판정**: 조회 시점 `verdict`는 항상 3종 중 최종값이며 "검토 대기" 상태를 두지 않는다(2.5 "종료상태만 반환" 전제와 정합). ⤷ **단서**: 기획안상 반자동은 사람 판정이 필요할 수 있어, **사람 판정 결과를 서버로 되받는 별도 엔드포인트**가 신설되면 이 계약이 바뀐다(그 응답으로 `verdict`가 뒤집히거나 "미확정 대기" 상태가 필요해짐). 그 경로는 아직 없어 현재는 Critic 자동 확정으로 둔다 — 4장 미결항목 및 2.5 `tier` 🔲와 연동.

**응답 200 (`none` 등급 · 근거없음 · 문헌 서술만)**
```json
{
  "analysis_id": "grp_scratch_20260707_01",
  "hypothesis_id": "h0",
  "cause": "handling_mechanical",
  "stage": "CMP",
  "tier": "none",
  "verdict": "insufficient",
  "verdict_reason": "KG 메커니즘 연결(VERIFIED_BY) 없음",
  "suspect": { "equipment_id": "CMP-02", "chamber_id": "CH1" },

  "sections": {
    "commonality": {
      "available": true,
      "rows": [
        { "equipment_id": "CMP-02", "chamber_id": "CH1", "matched_lots": 8, "total_lots": 8, "ratio": 1.0, "note": null }
      ],
      "normal_ratio": null
    },
    "telemetry": { "available": false, "reason": "none_tier", "series": [] },
    "events":    { "available": false, "reason": "none_tier", "rows": [] }
  },

  "unverified": [],
  "next_actions": [],
  "citations": [
    { "id": 7, "text": "Lee et al., Microelectronics Reliability 2021" }
  ],
  "note": "이 원인은 텔레메트리 시그니처가 없어 문헌 서술만 제공됩니다."
}
```
> `none` 등급도 `commonality`/`normal_ratio`는 모든 candidate 공통 호출이라 채워질 수 있다. tier 전용 근거(`telemetry`/`events`)만 `none_tier`로 빠진다.

**필드 사전 — 메타**

| 필드 | 타입 | 설명 |
|---|---|---|
| `analysis_id` | string | 소속 분석 id |
| `hypothesis_id` | string | 이 가설의 그룹 내 고유 id (`h{n}`) |
| `cause` | string | 원인 이름(kg_rca 자유추출). 표시용, 조회 키 아님 |
| `stage` | enum\|null | 공정 6종 `LITHO/ETCH/DEPO/CMP/CLEAN/EDS` 또는 `null`(문헌직결) |
| `tier` | enum | `auto` / `semi_auto` / `none` (백엔드 `자동/반자동/근거없음` 매핑) |
| `verdict` | enum | `accepted` / `rejected` / `insufficient` |
| `verdict_reason` | string\|null | `rejected`/`insufficient`일 때 사유, `accepted`면 `null` |
| `suspect` | object\|null | `{equipment_id, chamber_id}`. commonality top 장비. 없으면 `null` |

**필드 사전 — `sections.commonality`**

| 필드 | 타입 | 설명 |
|---|---|---|
| `available` | bool | 항상 `true` 기대(공통 호출). 공백 시 `false`+`no_data_found` |
| `rows[]` | array | 장비별 집계. `{equipment_id, chamber_id, matched_lots, total_lots, ratio(0~1), note}`. 용의 장비 하이라이트는 최상위 `suspect`와 대조해 프론트가 파생 |
| `rows[].note` | string\|null | 함정/부가 설명(선택적 표시 힌트) |
| `normal_ratio` | object\|null | 반대근거(대상 장비 = `suspect`). `{value(0~1), caption}` — 지지/약화 판단은 `caption` 문장으로만 전달(원값/표시 분리) |

**필드 사전 — `sections.telemetry`**

| 필드 | 타입 | 설명 |
|---|---|---|
| `available` | bool | 에이전트가 `query_telemetry`를 호출한 후보에서 `true`(통상 `auto`). `false`면 `{available, reason, series:[]}`만 — 아래 상세 스칼라 키는 **존재하지 않음**(존재계약 ③) |
| `param`,`unit` | string | 대상 신호 식별(장비 = `suspect`) |
| `normal_range` | [number, number]\|null | 정상범위 [하한, 상한] |
| `drift_detected` | bool\|null | 정상범위 이탈 여부. 정상범위 자체가 없으면 `null` |
| `t0` | string(ISO)\|null | 이상 시작 추정 시점(차트 수직선용). 없으면 `null` |
| `series[]` | array | `{ts, value}` 다운샘플 시계열(원값) |
| `caption` | string\|null | 표시용 요약 문장(선택적) |

**필드 사전 — `sections.events`**

| 필드 | 타입 | 설명 |
|---|---|---|
| `available` | bool | 에이전트가 정비/알람을 호출한 후보에서 `true`(통상 `semi_auto`의 정비). 호출 안 하면 `false` |
| `rows[]` | array | `{ts, type, equipment_id, kind?, code?, detail}` 시간순 |
| `rows[].type` | enum | `maintenance` / `alarm` |
| `rows[].kind` | enum(Optional) | `type:"maintenance"`일 때만 존재. `PM` \| `BM` (fab.db 스키마 고정 집합 · 닫힘) |
| `rows[].code` | string(Optional) | `type:"alarm"`일 때만 존재. 알람 코드 |

**필드 사전 — 부가**

| 필드 | 타입 | 설명 |
|---|---|---|
| `unverified[]` | array | 인용됐으나 검증 제외된 항목 `{ref, reason}`. 여기 `reason`은 **자유서술 문자열**(섹션 `available:false`의 `reason` enum과 무관·별개). 없으면 `[]` |
| `next_actions[]` | array(string) | 권장 조치. 없으면 `[]` |
| `citations[]` | array | 근거 문헌 `{id, text}` |
| `note` | string\|null | 그룹/등급 수준 안내 문구(주로 `none` 등급) |

> 🔲 **백엔드 갭(4장) — 계약은 확정, 백엔드가 순차 구현**: 아래 필드는 목표 계약에 두되 미구현 구간은 `available:false`+`reason`으로 표기한다(계약 변경 없이 값만 채워진다). 데이터 소싱은 **배치 실행 시 EvidenceEntry에 리치하게 보존→2.7은 저장분 조회만**을 권장한다(단일 출처·재현성, 온디맨드 MCP 재계산은 배치 결과와 미세하게 달라질 수 있어 지양).

| 필드/섹션 | 현재 상태 | 필요한 변경 |
|---|---|---|
| `hypothesis_id` | 없음 | ⑦이 **대표 정렬을 확정한 뒤**(2.5 정렬 불변식) 그 배열 인덱스로 `h{n}` 부여, 2.5·2.7·저장 JSON에 실기. 정렬 전에 번호를 매기면 `h0`가 대표가 아니게 된다 |
| `hypotheses[]` 정렬 | ⑦이 `critic["accepted"]`를 그대로 전달(`nodes/response.py`) — 대표를 index 0에 놓는 보장이 계약에 없었음 | ⑦이 대표 accepted를 index 0에 두도록 정렬해 저장·반환(2.5 정렬 불변식). **대표 선정 규칙 자체는 미확정** — 4장 미결정 "대표 원인 지정 로직" 확정이 선행 |
| `stage` | `Hypothesis`에 없음(`state.py:90`, equipment만) | ⑤에서 `candidate.step`을 `Hypothesis`에 실어 전달(2.5 `stage` 🔲와 동일 조치) |
| `citations[]` | `Hypothesis`에 인용 필드 없음(`state.py:90`) | kg_rca candidate의 문헌 인용을 `{id:int, text:string}`로 실기. 2.5·2.7 **동일 스키마·빈값 `[]`**(2.5의 구 `citation: string[]`·`null` 규약은 폐기) |
| `commonality.rows[]` | top 1개+ratio만 저장(`hypothesis.py:82-87`) | commonality 전체 테이블(카운트 포함) 보존 |
| `telemetry.series[]` | series 폐기, summary 문자열만 | `query_telemetry` series를 EvidenceEntry에 보존 |
| `events`(maintenance) | `maintenance_ts`/summary만 | 정비 rows 배열 보존 |
| `events`(alarm) | 미연동(`get_alarm_history` 미호출) | 파이프라인에 알람 조회 추가. 미연동 동안 events엔 alarm rows 없음 — 미구현 상태를 계약(`coverage`/`not_implemented`)으로 노출하지 않음 |
| `unverified[]` | 추적 필드 없음 | ⑤/⑥에서 미검증 인용 기록 |
| `next_actions[]` | NotRequired인데 미충전 | kg_rca candidate 또는 ⑦에서 생성해 주입 |
| `verdict` 3-state | Critic은 accepted/rejected 2리스트, KG메커니즘 실패를 rejected에 넣음 | Critic이 사유에 **고정 토큰**(`P5_NO_KG_MECHANISM` 등) 부여 → API가 그 토큰으로 `insufficient` 승격(`verdict_reason` 문자열 본문 매칭 금지) |

> **필드 존재 계약(2.7)** — 이 응답은 `available`·`type`에 따라 **섹션 내부** 형태가 바뀐다. 키 존재 규칙을 층위별로 못 박는다(판단 기준: **Optional = 키 자체 부재 / Nullable = 키는 있고 값이 `null`**).
>
> **① 최상위(메타 8 + 부가 4) — 전부 항상 존재(Optional 없음).**
>  - 메타 `analysis_id`·`hypothesis_id`·`cause`·`stage`·`tier`·`verdict`·`verdict_reason`·`suspect` + 부가 `unverified`·`next_actions`·`citations`·`note` 는 **언제나 키가 있다**.
>  - **non-null**: `analysis_id`·`hypothesis_id`·`cause`·`tier`·`verdict`. 배열 `unverified`·`next_actions`·`citations`는 비어도 `[]`(null·부재 금지).
>  - **Nullable**(키는 늘 있고 값만 `null` 가능): `stage`(문헌직결), `verdict_reason`(`accepted`면 `null`), `suspect`(commonality top 없으면 `null`), `note`(그룹 안내 없으면 `null`).
>
> **② `sections`와 3섹션 — 항상 존재, `available`(bool·항상 존재)이 형태를 가른다.**
>  - `sections` 및 `commonality`·`telemetry`·`events` 3키는 항상 존재·non-null. 각 섹션의 **주 배열**(`commonality.rows`·`telemetry.series`·`events.rows`)도 **항상 존재**(비수집이면 `[]`).
>  - `available:false` 정본 형태 — `commonality`: `{available:false, reason, rows:[], normal_ratio:null}` / `telemetry`: `{available:false, reason, series:[]}` / `events`: `{available:false, reason, rows:[]}`.
>  - `reason`은 **`available:false`일 때만 존재(Optional)**. `available:true`면 `reason` 키 없음.
>
> **③ 섹션 상세 필드 — `available:true`일 때만 존재(Optional).**
>  - `telemetry`(true): `param`·`unit`은 non-null, `series[]`는 항상. `normal_range`·`drift_detected`·`t0`·`caption`은 **Nullable**. 이 스칼라들은 `available:false`면 **키 자체가 없다**(②의 빈 형태 참조).
>  - `commonality`: `rows[]`는 `available:true`에서 채워지고, `normal_ratio`는 **섹션 내내 항상 존재하되 Nullable**(반대근거 없으면 `null` — `none` 등급처럼 `available:true`+`normal_ratio:null`도 정상).
>  - `commonality.rows[]` 원소: `equipment_id`·`matched_lots`·`total_lots`·`ratio`는 non-null, `chamber_id`·`note`는 Nullable(키는 항상 존재).
>  - `events.rows[]` 원소: `{ts, type, equipment_id, detail}`는 항상. **`kind`는 `type:"maintenance"`, `code`는 `type:"alarm"`일 때만 존재(Optional·상호배타)** — 반대 키는 없다.
>
> **④ 교차 제약**: `telemetry`·`normal_ratio`의 대상 장비는 최상위 `suspect`이며 섹션에 장비 id를 중복 게재하지 않는다. 따라서 **`suspect:null`이면 `telemetry.available:false`이고 `commonality.normal_ratio:null`**이다(앵커 부재).

**에러**
- `404` — `analysis_id`는 있으나 그 안에 `hypothesis_id`가 없는 경우(오타·잘못된 조합).
```json
{ "detail": "'grp_edgering_20260706_01' 분석에 'h9' 가설이 없습니다." }
```
- `404` — `unmapped` 그룹(`pattern:"Unknown"`)에 대해 근거를 요청한 경우. 가설이 없으므로 근거도 없다.
```json
{ "detail": "이 그룹은 원인 매핑이 없어 근거를 제공하지 않습니다." }
```
- `500` — 저장된 근거(EvidenceEntry) 조회·조립 실패(저장소 접근 불가 등).
```json
{ "detail": "근거를 불러오지 못했습니다." }
```

---

## 3. 데이터 모델 (스키마 요약)

| 모델 | 주요 필드 | 저장소 |
|---|---|---|
| YieldSummary | series[] (`name`, `points[]` — `array of (integer \| null)`) | SQLite `fab.db` |
| AnalysisSummary | analysis_id, pattern, lot_count, top_cause, status | `app_state.db` |
| Batch | batch_id, status, current_step, steps[], logs[], result_ids[] | `app_state.db` (checkpoint) |
| Analysis | analysis_id, pattern, description, status, hypotheses[], lot_ids[], reason | Neo4j + `app_state.db` |
| Hypothesis | hypothesis_id, cause, stage, tier, verdict, verdict_reason, narrative, next_actions[], citations[] | Neo4j |
| Wafer | wafer_id, defect_pattern, die_map_url | SQLite `wafer.die_map` |
| Evidence | hypothesis_id, cause, stage, tier, verdict, verdict_reason, suspect, sections{commonality, telemetry, events}, unverified[], next_actions[], citations[] | MCP 도구 집계(배치 시 EvidenceEntry 보존) |

> **고정 vocabulary (enum)** — 아래 값들은 문자열이지만 정해진 집합만 허용한다. 백엔드는 Pydantic `Enum`으로, 프론트는 이 값 기준으로 배지/색을 매핑한다.
> - `status` (분석 결과, 2.2·2.5): `reviewed` | `insufficient` | `unmapped`
> - `status` (배치 진행, 2.3·2.4): `running` | `completed` | `failed` — 접수(2.3 `202`)는 항상 `running`, 진행 조회(2.4)에서 `completed`/`failed`로 전이. 큐 없음(접수 즉시 실행)이라 `queued`는 두지 않는다.
> - `pattern` (결함 패턴, 5종 · KG 표준 엔티티): `Center` | `Edge-Ring` | `Scratch` | `Unknown` | `Normal` — 원인 매핑은 앞 3종(`Center`/`Edge-Ring`/`Scratch`)만, 비매핑 결함 통합값 `Unknown`(원 9종 중 `Edge-Loc`·`Loc`·`Donut`·`Near-Full`·`Random`)은 `unmapped`, `Normal`은 정상. CNN/DB 표기를 FastAPI가 이 집합으로 정규화
> - `series[].name` (수율 시리즈, 2.1): `low_yield_eq`(저수율 장비) | `line_avg`(라인 평균) — 프론트가 이 키로 라벨·색 매핑
> - `tier` (검증등급): `auto`(자동) | `semi_auto`(반자동) | `none`(근거없음)
> - `verdict` (Critic 판정): `accepted` | `rejected` | `insufficient`
> - `stage` (공정, 6종): `LITHO` | `ETCH` | `DEPO` | `CMP` | `CLEAN` | `EDS`

> **`analysis_id` 유니크 규칙**: `analysis_id`는 **배치 실행 + 패턴 단위로 유니크**하다(형식 `grp_{패턴}_{배치날짜}_{순번}`). `{순번}`은 그날의 배치 순번(2자리, `01`부터)으로, **같은 날 배치를 두 번 실행해도 ID가 충돌하지 않게** 하는 discriminator다(날짜만으로는 같은 날 2회차가 1회차를 덮어써 누적이 깨진다). 같은 패턴이라도 배치마다 새 ID가 부여되므로 `grp_edgering_20260706_01`·`grp_edgering_20260706_02`·`grp_edgering_20260707_01`은 서로 다른 별개의 결과다. 이렇게 해야 배치가 반복 실행돼도 과거 결과가 덮어써지지 않고 대기열에 누적된다. `batch_id`(`batch_{배치날짜}_{순번}`)는 한 배치가 만든 여러 analysis가 공유하는 값(1개 배치 → 여러 그룹 결과)이며, 그 배치의 그룹들은 같은 `{배치날짜}_{순번}`을 공유한다.
>
> **문서 내 예시 표기 규약**: 이 명세의 다른 예시 JSON에 나오는 `batch_20260706`·`grp_edgering_20260706`처럼 순번이 빠진 ID는 **그날 첫 배치(`_01`)의 생략표기**로 읽는다(가독성상 축약). 최종 계약 형식은 순번 포함이 정본이다.

---

## 3.1 엔드포인트별 에러 요약 (한눈에 보기)

> **계약 라우트는 아래 표의 8개가 전부다**(2장 §2.1~§2.7 + §2.6.1). 라우트 수를 셀 때는 절 번호가 아니라 이 표를 센다 — §2.6.1은 §2.6의 하위 절 번호를 달고 있지만 별개의 HTTP 라우트다. 다른 문서에서 "API 계약 N종"을 적을 때도 이 표를 기준으로 한다.

| 엔드포인트 | 200 정상 | 발생 가능 에러 |
|---|---|---|
| `GET /yield-summary` | 추이 데이터 | `500`(DB) |
| `GET /analyses` | 목록(빈 목록 포함) | `422`(sort 값) · `500`(저장소 조회 실패) |
| `POST /batches` | `202` 접수 | `409`(실행 중 / 기존 완료 배치 존재) · `500`(시작 실패) |
| `GET /batches/{id}` | 진행/완료/실패 상태 | `404`(없는 batch) |
| `GET /analyses/{id}` | 상세(reviewed/insufficient/unmapped) | `404`(없는 analysis) · `500`(내부 오류) |
| `GET /lots/{id}/wafers` | 웨이퍼 목록(빈 목록 포함) | `404`(없는 lot) · `500` |
| `GET /lots/{id}/wafers/{wid}/die-map` | `image/png` 바이너리(비-JSON) | `404`(없는 wafer/이미지) · `500` |
| `GET /analyses/{id}/evidence/{hypothesis_id}` | 근거 3섹션(섹션별 `available`) | `404`(없는 hypothesis_id / unmapped 그룹) · `500` |

> **핵심 원칙**
> 1. **"결과 없음"은 에러가 아니다** — 빈 목록·판단불가(`insufficient`)·매핑없음(`unmapped`)은 모두 `200`으로 정상 반환한다.
> 2. **폴링 대상(배치)은 실행 실패도 `200 + status:"failed"`** 로 준다. 폴링 루프가 200을 기대하기 때문.
> 3. **없는 리소스는 `404`, 형식 오류는 `422`** — 이 둘을 섞지 않는다.
> 4. **모든 엔드포인트는 서버 내부 오류 시 `500`** — 위 표는 각 엔드포인트의 특기 에러(`404`·`422`·`409`)를 명시하고, `500`은 전역 공통이라 대표 발생처에만 표기한다.

---

## 3.2 프론트 파생 표시값 — gloss 상수표 (비계약 참고)

> **비계약.** 아래 표는 API 응답 필드가 아니다. 화면3의 결정적 한 줄 요약(`summary_line`)을 **프론트가 조립**할 때 쓰는 표시 문자열 상수표다. 백엔드는 코드값(`pattern`, `hypotheses[0].stage`)만 내려주고 표시 문구는 프론트가 소유하므로, 이 표의 문구가 바뀌어도 **API 계약은 바뀌지 않는다**.
>
> ⚠️ **`summary_line` ≠ 2.5 `description`** — 이름이 겹치지 않게 구분한다. 2.5 `description`은 **③VLM이 생성한 자연어 서술로 API 응답 필드(계약)**이고, 여기 `summary_line`은 **프론트가 코드값으로 조립하는 결정적 문자열(비계약)**이다. 화면3은 `description`을 우선 표시하고, `description`이 `null`일 때 `summary_line`으로 fallback한다.

**조립 규칙**: `summary_line = {형상 gloss(pattern)} — {공정 gloss(hypotheses[0].stage)}`. 두 조각 모두 결정적 매핑이라 LLM에 의존하지 않는다.
- **fallback**: `hypotheses[0]`가 없거나(`unmapped`/`insufficient`) `stage`가 `null`이면 공정 조각을 "원인 매핑 없음"(`unmapped`)·"판단 불가"(`insufficient`)·"공정 미상"(`stage` 부재) 고정 문구로 대체한다. `stage=null`은 실측상 순위 꼬리(전체 6~9%)라 채택 대표 `hypotheses[0]`엔 사실상 안 나타나므로 "공정 미상"은 거의 안 쓰인다.
- ↔ 기획안 v1.5 §4 기능4의 VLM 자연어 서술은 그룹 대표 패턴 단위·자유서술이며, **2.5 `description` 필드로 노출된다**(계약). 프론트가 조립하는 결정적 한 줄 요약(`summary_line`, gloss)은 그와 별개이며 `description`이 `null`일 때의 fallback으로 쓴다.

**형상 gloss 상수표 (KG 표준 엔티티 5종)** — 입력은 `pattern`. 원인 매핑 3종(Center/Edge-Ring/Scratch)만 `reviewed`/`insufficient` 가능, `Unknown`은 `unmapped`.

| 패턴 | 형상 gloss | 원인 매핑 |
|---|---|---|
| `Center` | 중심부 집중 불량 | ✅ 매핑(3종) |
| `Edge-Ring` | 가장자리 고리형 불량 | ✅ 매핑(3종) |
| `Scratch` | 선형 긁힘 불량 | ✅ 매핑(3종) |
| `Unknown` | 미지/새로운 결함 패턴(원 9종 중 Edge-Loc·Loc·Donut·Near-Full·Random 통합) | ✗ unmapped |
| `Normal` | 결함 없음(정상) | — (저수율 결함 그룹 아님, 그룹 미생성) |

**공정 gloss 상수표 (6종)** — 입력은 `hypotheses[0].stage`(KG `ProcessStep` 6종).

| 공정(stage) | 공정 추정 gloss |
|---|---|
| `LITHO` | LITHO 공정 연관 추정 |
| `ETCH` | ETCH 공정 연관 추정 |
| `DEPO` | DEPO 공정 연관 추정 |
| `CMP` | CMP 공정 연관 추정 |
| `CLEAN` | CLEAN 공정 연관 추정 |
| `EDS` | EDS 공정 연관 추정 |

> 6종은 `fab_model.yaml:2 route`(=KG `ProcessStep` 고정 vocabulary = fab.db `EQUIPMENT.step_group`)와 동일 집합. gloss 문구는 표시 취향에 따라 조정 가능(현재는 공정 코드 그대로 노출).
> 🔲 **백엔드 확인(4장)**: `stage`는 응답에 존재하는 가설 카드 필드지만(2.5), 현재 백엔드 `Hypothesis`(`state.py:90`)엔 `stage`/`step`이 없다(`equipment`만 보유). ⑤에서 `cand.step`을 실어주기 전까지는 카드 `stage`와 이 파생 요약의 공정 조각 둘 다 값을 못 받는다(2.5 `stage` 필드의 🔲와 동일 갭·동일 조치).

---

## 4. 미결정 사항 (팀 합의 필요)
- [ ] **대표 원인(`top_cause`) 지정 로직 확인** — 여러 accepted 중 무엇을 대표(`hypotheses[0]`)로 놓는지는 **API가 아니라 백엔드 ⑦응답생성 단계 소관**(Critic은 채택 여부만 판정하고 순위는 내지 않음). API는 그 순서를 전달만 한다. ⑦응답생성이 실제로 대표를 어떻게 정하는지(단수 "Root Cause" 선정 규칙) 백엔드와 확인·기록 필요.
- [ ] **`semi_auto`(반자동) 등급의 사람 판정 결과를 API로 다시 받을지** (별도 엔드포인트 필요 여부) — 기획안상 "사람 판정 필요"라 후속 입력 경로가 생길 수 있음. ⤷ **현재 잠정 처리**: 이 경로가 없어 2.5는 `semi_auto`를 Critic이 **자동 기각(`rejected`)**한다(2.5 `tier` 항목 🔲). 조회 시점 `verdict`엔 "검토 대기" 상태를 두지 않는다(항상 3종 최종값, 2.5 "종료상태만" 전제와 정합). **이 별도 엔드포인트가 신설되면** 사람 판정 결과로 `verdict`가 뒤집히거나 "미확정 대기" 상태가 필요해져 2.7·2.5 계약이 함께 바뀐다. 와이어프레임에 판정 입력 화면이 아직 없어 보류.
- [ ] **기획안 Critic ② 반대근거(P3) 문구 확장** — 기획안 v1.5 §7.2 Critic Workflow ②는 기각 사유를 `against is None`(정상 로트 대조 **미수행**)만 명시하나, 명세 2.5는 "대조는 수행했으나 정상비율이 높아 원인을 **반박**"하는 경우도 P3 기각(`rejected`)으로 처리한다(예: `cmp_edge_overpolish`, "CMP-01 통과 로트 65% 정상 → 지지 약함"). ⤷ 기획 변경 반영분이므로 기획안 ② 문구를 "미수행 **또는** 반박"까지 포함하도록 확장할지 기획/백엔드와 확인·정합. 확장 시 "반박" 판정 임계값(정상비율 몇 % 이상이면 기각인지)도 함께 정의 필요.
