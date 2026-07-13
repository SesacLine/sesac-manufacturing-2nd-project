# 웨이퍼 결함 RCA 대시보드 — API 명세서

> **대상 시스템** React+Vite 프론트엔드 ↔ FastAPI 백엔드 (REST)    
> **근거 문서**: `아키텍처 및 컴포넌트 설계_v1.0.png`, `rca_wireframe_v4.html`

---

## 0. 이 문서를 채우는 법 (작성자용 · 최종본에서 삭제)

1. 각 엔드포인트의 **요청/응답 예시 JSON**은 와이어프레임 더미데이터로 미리 채워뒀다. 실제 필드명은 백엔드 담당자와 맞춰 확정한다.
2. `🔲 결정 필요` 표시는 팀이 합의해야 하는 지점이다. 회의에서 정하고 표시를 지운다.
3. 완성 후에는 이 명세가 FastAPI의 Pydantic 모델 → `/docs`(Swagger) 자동 문서와 일치해야 한다. 지금은 사람이 읽는 계약서, 나중에 코드로 수렴.
4. 순서: **공통 규약 확정 → 엔드포인트별 요청/응답 확정 → 데이터 모델 확정 → 프론트/백엔드 리뷰**.

---

## 1. 공통 규약 (Conventions)

| 항목 | 값 | 비고 |
|---|---|---|
| Base URL | `http://localhost:8000/api/v1` | |
| 데이터 형식 | `application/json` (UTF-8) | 웨이퍼맵 이미지만 예외(아래 참조) |
| 날짜 형식 | ISO 8601 (`2026-07-06T09:02:00Z`) | |
| 페이지네이션 | 🔲 결정 필요 — **배치 실행 빈도 미정이라 판단 보류** (`?limit=&offset=` 후보) | 아래 4장 참조 |

### 1.1 공통 상태 코드 · 에러 형식
모든 4xx/5xx 응답은 `detail` 키를 갖는다. (FastAPI 기본 형식)

| 코드 | 의미 | 사용 예시 | `detail` 예시 |
|---|---|---|---|
| 200 | 성공(조회) | 목록/상세 조회 | — |
| 202 | 접수됨(비동기 시작) | 배치 분석 실행 요청 | — |
| 400 | 잘못된 요청 | 파라미터 형식 오류 | `"detail": "잘못된 요청입니다."` |
| 404 | 없음 | 존재하지 않는 analysis_id | `"detail": "'grp_edgering_20250101' 분석을 찾을 수 없습니다."` |
| 409 | 충돌 | 이미 실행 중인 배치가 있는데 또 실행 요청 | `"detail": "이미 진행 중인 배치가 있습니다."` |
| 422 | 검증 실패 | FastAPI 유효성 검사 실패(타입/범위) | `"detail": [{"loc": ["query","days"], "msg": "...", "type": "..."}]` |
| 500 | 서버 오류 | 에이전트 실행 실패 | `"detail": "서버 내부 오류가 발생했습니다."` |

---

## 2. 엔드포인트 명세

### 2.1 `GET /yield-summary` — 수율 현황 요약 (화면1)
최근 7일 로트별/장비별 수율 추이. 대시보드 진입 시 1회 호출.

**요청** 파라미터 없음 (🔲 기간 파라미터 `?days=7` 필요 여부 결정)

**응답 200**
```json
{
  "updated_at": "2026-07-06T09:02:00Z",
  "series": [
    { "name": "저수율 장비", "points": [80, 88, 72, 96, 58, 50, 46] },
    { "name": "라인 평균", "points": [64, 65, 62, 64, 61, 62, 60] }
  ]
}
```

**에러**
- `422` — `?days`에 숫자가 아닌 값이 오거나 허용 범위(1~90)를 벗어난 경우 (🔲 기간 파라미터 `?days=7` 필요 여부 결정)
```json
{
  "detail": [
    { "loc": ["query", "days"], "msg": "value is not a valid integer", "type": "type_error.integer" }
  ]
}
```
- `500` — 수율 데이터 조회 실패(예: `fab.db` 접근 불가)
```json
{ "detail": "수율 데이터를 불러오지 못했습니다." }
```

---

### 2.2 `GET /analyses` — 가설 검토 대기열 (화면1)
분석 완료 결과 누적 목록. 행 클릭 시 상세(2.5)로 이동.

**요청** `?sort=latest|oldest` — `latest`(최신순, 기본값) 또는 `oldest`(오래된순). 생략 시 `latest` (🔲 페이지네이션 여부 결정)

**응답 200**
```json
{
  "count": 4,
  "items": [
    { "analysis_id": "grp_edgering_20260706", "batch_id": "batch_20260706", "pattern": "Edge-Ring", "lot_count": 8, "top_cause": "etch_nonuniformity",  "adopt_prob": 82, "status": "reviewed" },
    { "analysis_id": "grp_center_20260706",   "batch_id": "batch_20260706", "pattern": "Center",    "lot_count": 8, "top_cause": "clean_nozzle_clog",   "adopt_prob": 71, "status": "reviewed" },
    { "analysis_id": "grp_scratch_20260706",  "batch_id": "batch_20260706", "pattern": "Scratch",   "lot_count": 8, "top_cause": "handling_mechanical", "adopt_prob": 88, "status": "reviewed" },
    { "analysis_id": "grp_donut_20260706",    "batch_id": "batch_20260706", "pattern": "Donut",     "lot_count": 6, "top_cause": null,                  "adopt_prob": null, "status": "unmapped" }
  ]
}
```
- **`analysis_id` 형식**: `grp_{패턴}_{배치날짜}` (예: `grp_edgering_20260706`). 같은 Edge-Ring 패턴이라도 **배치 실행일마다 다른 ID로 누적**되어 날짜별 이력이 각각 보존된다. `batch_id`로 어느 배치에서 나온 결과인지 역참조할 수 있다.
- `status`: `reviewed`(검토완료) | `unmapped`(판단불가·원인 매핑 없음)

**응답 200 (결과 없음)** — 에러가 아니라 빈 목록으로 반환한다. 프론트는 "아직 분석된 결과가 없습니다" 안내를 띄운다.
```json
{ "count": 0, "items": [] }
```

**에러**
- `422` — `?sort`에 허용값(`latest`|`oldest`) 외의 값이 온 경우.
```json
{ "detail": [ { "loc": ["query", "sort"], "msg": "unexpected value; permitted: 'latest', 'oldest'", "type": "value_error" } ] }
```

---

### 2.3 `POST /batches` — 오늘 판독 배치 실행 (화면1 버튼)
어제 누적 데이터 자동 그룹화 → 전 그룹 Hypothesis·Critic 일괄 실행. **오래 걸리므로 비동기**로 접수만 하고 즉시 batch_id 반환

**요청 본문** (자동 대상이면 비어있음)
```json
{}
```

**응답 202**
```json
{ "batch_id": "batch_20260706", "status": "running", "started_at": "2026-07-06T09:14:00Z" }
```

**에러**
- `409` — 이미 실행 중인 배치가 있는 경우(중복 클릭 방지), 진행 중 batch_id를 함께 돌려주면 프론트가 바로 진행 화면으로 보낼 수 있다
```json
{ "detail": "이미 진행 중인 배치가 있습니다.", "running_batch_id": "batch_20260706" }
```
- `500` — 그룹화/에이전트 실행 시작에 실패
```json
{ "detail": "배치 실행을 시작하지 못했습니다." }
```

---

### 2.4 `GET /batches/{batch_id}` — 배치 진행 상태 (화면2)
진행 단계 + MCP 도구 호출 로그. **폴링 방식**(프론트가 1~2초마다 반복 호출).
🔲 결정 필요: 폴링 vs SSE 스트리밍(`GET /batches/{id}/stream`). 로그가 실시간이라 SSE도 후보.

**응답 200 (진행 중)**
```json
{
  "batch_id": "batch_20260706",
  "status": "running",
  "current_step": 2,
  "steps": ["자동 그룹화", "원인 후보 검색", "증거 수집", "검증", "완료"],
  "logs": [
    { "time": "09:14:00", "tool": "auto_group_wafermaps", "message": "4개 패턴 그룹 감지", "status": "done" },
    { "time": "09:14:02", "tool": "run_commonality_analysis", "message": "[Edge-Ring] ETCH-01 공통", "status": "done" }
  ]
}
```

**응답 200 (완료)** — `status: "completed"`, `result_ids: ["grp_edgering_20260706", "grp_center_20260706", "grp_scratch_20260706", "grp_donut_20260706"]` 포함. 이 ID들이 곧 대기열(2.2)에 쌓이는 `analysis_id`다.

**응답 200 (실패)** — 배치 자체는 존재하지만 에이전트 실행이 중단된 경우. HTTP는 200이되 `status`로 실패를 표현한다(폴링 중이므로).
```json
{
  "batch_id": "batch_20260706",
  "status": "failed",
  "current_step": 3,
  "error": "Critic 단계에서 Neo4j 연결이 끊겼습니다.",
  "logs": [ { "time": "09:14:20", "tool": "critic_validate", "message": "Neo4j timeout", "status": "error" } ]
}
```

**에러**
- `404` — 존재하지 않는 batch_id. `{ "detail": "'batch_00000000' 배치를 찾을 수 없습니다." }`

> **설계 노트**: "배치 실행이 실패한 것"과 "요청이 잘못된 것"을 구분한다. 없는 ID 조회는 `404`(위), 실행 중 오류는 위처럼 `200 + status:"failed"`. 폴링 화면이 200을 기대하며 계속 호출하기 때문이다.

---

### 2.5 `GET /analyses/{analysis_id}` — 분석 결과 상세 (화면3)
가설 카드 · Critic · 인용 · 소속 로트. 대기열 행 클릭 시 호출.

**응답 200 (판독 성공)**
```json
{
  "analysis_id": "grp_edgering_20260706",
  "batch_id": "batch_20260706",
  "pattern": "Edge-Ring",
  "title": "Edge-Ring 그룹",
  "description": "가장자리 고리형 불량 — ETCH 공정 연관 추정",
  "lot_count": 8,
  "wafer_count": 42,
  "status": "reviewed",
  "lot_ids": ["lot23844", "lot44793", "lot6092"],
  "hypotheses": [
    {
      "cause": "etch_nonuniformity",
      "stage": "ETCH",
      "prob": 82,
      "adopted": true,
      "narrative": "8개 로트 전부가 ETCH-01(CH2)를 통과했고, rf_power가 정상범위 상한을 넘어...",
      "evidence_key": "etch_edgering"
    }
  ],
  "critic": "Critic 검증: 시간 선후 정합, 정상 로트 대조, 함정 장비 기각...",
  "citation": "[1] Wang et al., IEEE Trans. Semiconductor Manufacturing 2020"
}
```

**응답 200 (판단 불가)** — `status: "unmapped"`, `hypotheses: []`, `reason: "원인 매핑 데이터 없음..."` 포함. (판단 불가는 **정상 응답**이지 에러가 아니다.)

**에러**
- `404` — 존재하지 않는 analysis_id(대기열에 없는 그룹).
```json
{ "detail": "'grp_edgering_20250101' 분석을 찾을 수 없습니다." }
```

---

### 2.6 `GET /lots/{lot_id}/wafers` — 로트 웨이퍼맵 판독 (화면3 로트 클릭)
로트 소속 판독 웨이퍼 목록. VLM 판독 기준.

**응답 200**
```json
{
  "lot_id": "lot23844",
  "pattern": "Edge-Ring",
  "wafers": [
    { "wafer_id": "w01", "is_normal": false, "defect_pattern": "Edge-Ring", "die_map_url": "/api/v1/wafers/w01/die-map" },
    { "wafer_id": "w05", "is_normal": true,  "defect_pattern": null,        "die_map_url": "/api/v1/wafers/w05/die-map" }
  ]
}
```
🔲 결정 필요: 웨이퍼맵을 **좌표 배열**(JSON)로 줄지, **이미지 URL/BLOB**(`wafer.die_map`)로 줄지. 위는 이미지 URL 방식 예시.

**에러**
- `404` — 존재하지 않는 lot_id.
```json
{ "detail": "'lot00000' 로트를 찾을 수 없습니다." }
```
- `404` (웨이퍼맵 이미지 별도 조회 시) — `GET /wafers/{wafer_id}/die-map` 에서 이미지가 없을 때. 이미지 엔드포인트는 성공 시 JSON이 아니라 `image/png` 바이너리를 반환한다(🔲 확정 필요).
```json
{ "detail": "'w99' 웨이퍼의 die map 이미지를 찾을 수 없습니다." }
```

---

### 2.7 `GET /analyses/{analysis_id}/evidence/{cause}` — 근거 상세 (근거 모달)
Commonality / Telemetry / Alarm·Maintenance 3섹션.

**응답 200**
```json
{
  "cause": "etch_nonuniformity",
  "commonality": [
    { "equipment": "ETCH-01 (CH2)", "match": "8 / 8", "rate": "100%" },
    { "equipment": "LITHO-01",      "match": "8 / 8", "rate": "100% (함정 · t0 이후 PM)" }
  ],
  "normal_ratio": "ETCH-01-CH2 통과 로트 중 정상 20% 미만 → 원인 지지",
  "telemetry": {
    "has_telemetry": true,
    "label": "ETCH-01-CH2 · rf_power",
    "range": "정상범위 [1900, 2100] W · t0 이후 상한 초과 step-up",
    "points": [50, 52, 49, 50, 48, 20, 15, 18, 16]
  },
  "events": [
    { "time": "2026-01-29", "type": "Maintenance", "equipment": "ETCH-01", "detail": "BM · 부품 교체" },
    { "time": "2026-01-30", "type": "Alarm",       "equipment": "ETCH-01", "detail": "rf_power high alarm" }
  ]
}
```
- 텔레메트리가 없는 원인(handling_mechanical 등)은 `has_telemetry: false`, `telemetry_na: "해당 없음 — ..."` 반환.

**에러**
- `404` — analysis_id는 있지만 그 안에 해당 `cause`가 없는 경우(오타·잘못된 조합).
```json
{ "detail": "'grp_edgering_20260706' 분석에 'wrong_cause' 원인이 없습니다." }
```
- `404` — `unmapped` 그룹(예: Donut)에 대해 근거를 요청한 경우. 가설이 없으므로 근거도 없다.
```json
{ "detail": "이 그룹은 원인 매핑이 없어 근거를 제공하지 않습니다." }
```

---

## 3. 데이터 모델 (스키마 요약)

| 모델 | 주요 필드 | 저장소 |
|---|---|---|
| YieldSummary | updated_at, series[] | SQLite `fab.db` |
| AnalysisSummary | analysis_id, batch_id, pattern, lot_count, top_cause, adopt_prob, status | `app_state.db` |
| Batch | batch_id, status, current_step, steps[], logs[], result_ids[] | `app_state.db` (checkpoint) |
| Analysis | analysis_id, batch_id, pattern, hypotheses[], critic, citation, lot_ids[] | Neo4j + `app_state.db` |
| Hypothesis | cause, stage, prob, adopted, narrative, evidence_key | Neo4j |
| Wafer | wafer_id, is_normal, defect_pattern, die_map_url | SQLite `wafer.die_map` |
| Evidence | cause, commonality[], normal_ratio, telemetry, events[] | MCP 도구 집계 |

> **`analysis_id` 유니크 규칙**: `analysis_id`는 **배치 실행 + 패턴 단위로 유니크**하다(형식 `grp_{패턴}_{배치날짜}`). 같은 패턴이라도 배치마다 새 ID가 부여되므로, `grp_edgering_20260706`과 `grp_edgering_20260707`은 서로 다른 별개의 결과다. 이렇게 해야 배치가 반복 실행돼도 과거 결과가 덮어써지지 않고 대기열에 누적된다. `batch_id`는 여러 analysis가 공유하는 값(1개 배치 → 여러 그룹 결과).

---

## 3.1 엔드포인트별 에러 요약 (한눈에 보기)

| 엔드포인트 | 200 정상 | 발생 가능 에러 |
|---|---|---|
| `GET /yield-summary` | 추이 데이터 | `422`(days 형식) · `500`(DB) |
| `GET /analyses` | 목록(빈 목록 포함) | `422`(sort 값) |
| `POST /batches` | `202` 접수 | `409`(중복 실행) · `500`(시작 실패) |
| `GET /batches/{id}` | 진행/완료/실패 상태 | `404`(없는 batch) |
| `GET /analyses/{id}` | 상세(unmapped 포함) | `404`(없는 analysis) |
| `GET /lots/{id}/wafers` | 웨이퍼 목록 | `404`(없는 lot) |
| `GET /analyses/{id}/evidence/{cause}` | 근거 3섹션 | `404`(없는 cause / unmapped 그룹) |

> **핵심 원칙 3가지** (리뷰 때 이걸로 설득하면 됨)
> 1. **"결과 없음"은 에러가 아니다** — 빈 목록·판단불가(unmapped)는 `200`으로 정상 반환한다.
> 2. **폴링 대상(배치)은 실행 실패도 `200 + status:"failed"`** 로 준다. 폴링 루프가 200을 기대하기 때문.
> 3. **없는 리소스는 `404`, 형식 오류는 `422`** — 이 둘을 섞지 않는다.

---

## 4. 미결정 사항 (팀 합의 필요)
- [x] Base URL / 버전 prefix 확정
- [x] 인증 방식 유무
- [x] `analysis_id` 유니크 기준 → **배치 실행 + 패턴 단위**로 확정(형식 `grp_{패턴}_{배치날짜}`, `batch_id`로 배치 역참조). 배치별 결과 누적을 위함
- [ ] 배치 진행 조회: 폴링 vs SSE 스트리밍
- [ ] 웨이퍼맵 전달 방식: 좌표 JSON vs 이미지 URL/BLOB
- [ ] **배치 실행 빈도/데이터 누적 주기** (기획 담당자 확인 필요 — 하루 1회? 데모 시에만? 최대 그룹 수는 9개로 산정됨)
- [ ] **같은 날 배치 재실행 시 처리** — "오늘 판독 배치 확인"을 하루에 또 누르면: (A) 새 배치로 취급해 새 `batch_id`/`analysis_id` 생성(이력 누적) vs (B) 같은 날 기존 결과를 덮어쓰기. ⤷ 현재 ID가 날짜 단위(`_20260706`)라 (A)로 가려면 날짜에 순번/시각을 더해야 충돌을 피함. 위 배치 실행 빈도와 함께 결정
- [ ] 대기열 페이지네이션 필요 여부 — ⤷ 위 배치 실행 빈도가 정해져야 판단 가능. 정해지면 `limit` 기본값은 배치 1회 최대 결과(9건)가 안 잘리도록 10~15 선에서 재검토
- [ ] 필드 네이밍 컨벤션(snake_case 확정) — 백엔드와 합의
