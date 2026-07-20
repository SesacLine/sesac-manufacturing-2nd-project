# 백엔드 갭 목록

> **이 표와 `docs/API_명세서_v1.0.md`가 어긋나면 명세서가 이긴다.** 계약은 이미 확정이고 여기 적힌 것은 "값이 아직 안 채워진 구간"일 뿐이다 — 이 표를 두 번째 정본으로 쓰지 마라.
> **갭이 메워지면 해당 행을 지운다.** 행이 줄어드는 문서다.
> 착수 전 확인 절차는 `AGENT_GUIDE.md` §1-a의 3등급 표를 따른다. `§n`은 전부 명세서 절 번호다.

## A. 명세서 `🔲` 마커 유래

> 명세서 `🔲` 매치 11건 = 실질 마커 6지점(§2.5×3, §2.7×2, §3.2×1) + 상호참조 5건. §2.7의 마커 하나가 11행짜리 갭 표("필드 사전 — 부가" 바로 아래)를 열고 있어 아래 행 수가 마커 수보다 많다.

| 대상 필드/섹션 | 현재 상태 | 필요한 변경 | 관련 절 |
|---|---|---|---|
| `description` (VLM 서술) | `VLMResult.description`이 **웨이퍼 1장 단위**(`state.py:28`)이고 값은 `"Walking Skeleton 임시값"` 고정(`nodes/vlm.py:44`). 그룹 대표 서술을 만드는 단계(=§2.4 `vlm_describe`)가 코드에 없다 | 그룹 대표 서술 정의(대표 웨이퍼 선정 vs 그룹 단위 재생성) 후 그룹화 **뒤** 단계로 VLM 연동. 그때까지 `description: null` 반환 → 프론트 `summary_line` fallback | §2.5 · §2.4 · §3.2 |
| `tier: semi_auto` 판정 | Critic이 자동 처리(사람 판정 경로 없음). `critic.py`엔 `semi_auto` 전용 분기 자체가 없다 | **현재는 잠정 유지(자동 기각)**. 사람 판정 수신 엔드포인트는 §4-2 미결정이라 **구현 금지**(3등급 "정지") | §2.5 · §4-2 |
| `stage` | `Hypothesis`에 `stage`/`step` 없음(`state.py:90~101`, `equipment`만) | `state.py`의 `Hypothesis`에 `stage` 추가 + ⑤Hypothesis(`nodes/hypothesis.py`)에서 `candidate["step"]`을 실어 전달. 가설 카드·`summary_line` 공정 조각이 함께 해소된다 | §2.5 · §2.7 · §3.2 |
| `verdict` 3-state | Critic이 `accepted[]`/`rejected[]` 2리스트만 내고, KG 메커니즘 실패도 `rejected`에 넣는다(`critic.py:38-39`). 사유는 자유서술 문자열(`reject_reason`) | Critic이 사유에 **고정 토큰**(`P5_NO_KG_MECHANISM` 등)을 부여 → API가 그 토큰으로만 `insufficient` 승격. `verdict_reason` 자연어 본문 매칭 금지 | §2.7 · §2.5 |
| `hypothesis_id` | 없음 | ⑦응답생성(`nodes/response.py`)이 **대표 정렬을 확정한 뒤** 그 배열 인덱스로 `h{n}` 부여, §2.5·§2.7·저장 JSON에 실기. 정렬 전에 번호를 매기면 `h0`가 대표가 아니게 된다 | §2.5 · §2.7 |
| `hypotheses[]` 정렬 | ⑦응답생성이 `critic["accepted"]`를 순서 조작 없이 그대로 전달(`nodes/response.py:63`) — 대표가 index 0이라는 보장 없음 | 대표 accepted를 index 0에 두도록 정렬해 저장·반환. **대표 선정 규칙 자체는 §4-1 미결정**(3등급 "잠정+기록": 규칙을 정해 구현하고 근거를 남긴 뒤 보고) | §2.5 · §4-1 |
| `citations[]` | `Hypothesis`에 인용 필드 없음(`state.py:90`). `KGClient._to_candidate`도 문헌 인용을 안 옮긴다(`kg_client.py:47-61`) | kg_rca candidate의 문헌 인용을 `{id:int, text:string}`로 옮겨 실기. §2.5·§2.7 **동일 스키마·빈값 `[]`** | §2.5 · §2.7 |
| `commonality.rows[]` | top 1개 장비 + ratio만 저장(`hypothesis.py:84-88`, `EvidenceEntry.commonality_ratio`) | commonality 전체 테이블(`matched_lots`/`total_lots`/`ratio`/`note` 포함) 보존 | §2.7 |
| `telemetry.series[]` | series 폐기, 요약 문자열만(`hypothesis.py:110`, `telemetry_summary`) | `query_telemetry`의 `series`·`normal_range`·`t0`를 `EvidenceEntry`에 보존 | §2.7 |
| `events`(maintenance) | `maintenance_hit`/`maintenance_ts`/요약 문자열만(`hypothesis.py:116-119`) | 정비 rows 배열(`{ts, type, equipment_id, kind, detail}`) 보존 | §2.7 |
| `events`(alarm) | 미연동 — `get_alarm_history` 호출 지점이 파이프라인에 없다 | 파이프라인에 알람 조회 추가(단서: fab.db 알람은 `lot_id=NULL`이라 `equipment_id`로 조회). 미연동 동안 events에 alarm rows 없음 — 미구현을 계약으로 노출하지 않는다 | §2.7 |
| `unverified[]` | 추적 필드 없음 | ⑤Hypothesis·⑥Critic에서 "인용은 했으나 검증 제외" 항목을 `{ref, reason}`으로 기록 | §2.7 |
| `next_actions[]` | `Hypothesis.next_actions`가 `NotRequired`인데 아무도 안 채운다(`state.py:97`) | kg_rca candidate 또는 ⑦응답생성에서 생성해 주입. 없으면 `[]`(키 생략 아님) | §2.5 · §2.7 |
| 근거 저장 방식 | `EvidenceEntry`가 bool/float 요약값만 보관(`state.py:72-87`) | 배치 실행 시 `EvidenceEntry`에 **리치하게 보존 → §2.7은 저장분 조회만**. 온디맨드 MCP 재계산 금지(배치 결과와 어긋난다) | §2.7 |

## B. 코드 확인 추가 갭 (명세 `🔲`에 안 잡힌 것)

| 대상 필드/섹션 | 현재 상태 | 필요한 변경 | 관련 절 |
|---|---|---|---|
| `tier` 표기 | `state.py:13` `Tier = Literal["자동","반자동","근거없음"]`(한글). `hypothesis.py`·`critic.py`가 이 한글 값으로 분기한다 | **API 경계에서만** `auto`/`semi_auto`/`none`으로 정규화. 노드 안 값을 바꾸면 tier 분기가 깨진다 | §3 · §2.5 |
| `pattern` 5종 | ①이 `"Center"` 고정(`vlm.py:18,42`)이라 `Edge-Ring`/`Scratch`/`Unknown`/`Normal` 그룹이 생기지 않는다 | VLM/CNN 연동 후 FastAPI가 5종으로 정규화. `Unknown` → `status:"unmapped"` 경로도 그때 실검증 | §2.2 · §2.6 · §3 |
| `sentence` 키 오타 | `hypothesis.py:70`이 `candidate["senetence"]`를 읽는다. `kg_client.py:60`은 `"sentence"`로 넣으므로 **`KeyError` 발생** | 오타 수정(`candidate["sentence"]`). ⑤Hypothesis가 후보 1건이라도 처리하면 즉시 터지는 자리다 | — (내부 버그, 계약 무관) |
| `batch_id` · `analysis_id` | 채번 개념 자체가 없다. `group_id`는 `f"{pattern}-{cursor_date}"`(`grouper.py:38`), `batch_id`는 존재하지 않음 | `batch_{배치날짜}_{순번}` · `grp_{패턴}_{배치날짜}_{순번}` 형식으로 채번하고 한 배치의 그룹들이 같은 `{배치날짜}_{순번}`을 공유하게 한다 | §2.2 · §2.3 · §3 |
| `EVENT_DATE` 고정 기준일 | 없음. `main.py:32`의 `_FIRST_CURSOR_DATE="2026-03-04"`는 **데이터축 커서**라 별개 값이다 | 서버 설정 한 곳에 `EVENT_DATE = 2026-04-01` 상수를 두고 ID·이벤트 시각에 사용(데이터축 시각은 계속 `max(ts)` 기준) | §1 |
| 배치 진행 상태(`current_step`·`logs`) | 방출 훅이 없다 — `graph.py`는 최종 상태만 반환하고 `main.py:79`는 `ainvoke`를 동기로 await한다 | 배치를 백그라운드로 돌리고 단계 전이·MCP 호출을 `app_state.db`에 기록하는 경로 신설. `steps` 8키 매핑은 `AGENT_GUIDE.md` §5 | §2.3 · §2.4 |
| 배치 1회 실행 정책(409) | 없다 — `POST /batch/run`은 호출할 때마다 커서를 전진시킨다(`main.py:51-60`) | 실행 중/완료 배치가 있으면 `409` + 해당 `detail` 문자열 반환 | §2.3 |
| 그룹 `status` · `reason` | `CriticResult.status`는 `accepted`/`insufficient_evidence` 2종(`state.py:106`), `FinalResponse`엔 `reason`·`lot_ids`·`lot_count`가 없다(`state.py:111-118`) | 그룹 status를 `reviewed`/`insufficient`/`unmapped` 3종으로 매핑하고 `reason`·`lot_ids`·`lot_count`를 응답에 싣는다 | §2.2 · §2.5 |
| `GET /yield-summary` | 미구현. `metric_series` 집계 코드가 백엔드에 없다 | `metric_series` 단독 집계로 `low_yield_eq`·`line_avg` 2시리즈 생성(×100 정수, `max(ts)` 기준 7일, 빈 날 `null`) | §2.1 |
| 대기열 쿼리 파라미터 | `GET /batch/results`가 전체 행을 배열로 반환(`main.py:93-109`) — `count`·`sort`·`limit`/`offset` 없음 | `{count, items[]}` 형태 + `sort`(422 검증)·페이지네이션 구현 | §2.2 |
| 웨이퍼맵 엔드포인트 | 미구현(2종 모두 없음) | `GET /lots/{lot_id}/wafers`(정수 오름차순 정렬·3집계) + die-map 재서빙(MCP `get_wafer_map` base64 디코드 → `image/png`) | §2.6 · §2.6.1 |
| URL prefix · CORS · 라우터 구조 | `/api/v1` prefix 없음, `CORSMiddleware` 미등록, 엔드포인트가 `main.py`에 직접 박힘 | prefix `/api/v1` 적용, CORS 오리진 `http://localhost:5173` 허용, 라우터를 `backend/api/` 하위 모듈로 분리하고 `main.py`는 앱 조립만 | §1 |
