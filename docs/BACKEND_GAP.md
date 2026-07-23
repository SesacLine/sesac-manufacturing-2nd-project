# 백엔드 갭 목록

> **이 표와 `docs/API_명세서_v1.0.md`가 어긋나면 명세서가 이긴다.** 계약은 이미 확정이고 여기 적힌 것은 "값이 아직 안 채워진 구간"일 뿐이다 — 이 표를 두 번째 정본으로 쓰지 마라.
> **갭이 메워지면 해당 행을 지운다.** 행이 줄어드는 문서다.
> 착수 전 확인 절차는 `AGENT_GUIDE.md` §1-a의 3등급 표를 따른다. `§n`은 전부 명세서 절 번호다.
>
> 2026-07-20 API 8종 구현 세션에서 다수 행 해소(채번·EVENT_DATE·진행 방출·409·stage·verdict
> 토큰·hypothesis_id·정렬·citations·리치 근거 보존·tier 정규화·sentence 오타·yield-summary·
> 대기열·웨이퍼맵·CORS/라우터 분리). 그때의 내부 정책 기록은 `BACKEND_DECISIONS.md` 참고.

## A. 명세서 `🔲` 마커 유래

| 대상 필드/섹션 | 현재 상태 | 필요한 변경 | 관련 절 |
|---|---|---|---|
| `description` (VLM 서술) | VLM 미연동 — API는 `description: null`을 반환하고 프론트는 `summary_line`으로 fallback 중(구현됨). 그룹 대표 서술을 만드는 단계(=§2.4 `vlm_describe`)가 코드에 없다 | 그룹 대표 서술 정의(대표 웨이퍼 선정 vs 그룹 단위 재생성) 후 그룹화 **뒤** 단계로 VLM 연동 | §2.5 · §2.4 · §3.2 |
| `tier: semi_auto` 판정 | Critic이 judge_unknown **보류**(`SEMI_AUTO_PENDING` 토큰, `investigated` 마커 기반 — BACKEND_DECISIONS.md D8). 기각 아님 | 사람 판정 수신 엔드포인트는 §4-2 미결정이라 **구현 금지**(3등급 "정지"). 경로가 생기면 반자동을 fab 증거로 조사해 보류 해소 | §2.5 · §4-2 |
| `events`(alarm) | 미연동 — `get_alarm_history` 호출 지점이 파이프라인에 없다(events 섹션은 maintenance rows만 담김) | 파이프라인에 알람 조회 추가(단서: fab.db 알람은 `lot_id=NULL`이라 `equipment_id`로 조회). 미연동 동안 events에 alarm rows 없음 — 미구현을 계약으로 노출하지 않는다 | §2.7 |
| `unverified[]` | 추적 필드 없음 — API는 항상 `[]` 반환(계약상 유효) | ⑤Hypothesis·⑥Critic에서 "인용은 했으나 검증 제외" 항목을 `{ref, reason}`으로 기록 | §2.7 |
| `next_actions[]` | 생성 주체 없음 — API는 항상 `[]` 반환(계약상 유효, 키 생략 아님) | kg_rca candidate 또는 ⑦응답생성에서 생성해 주입 | §2.5 · §2.7 |

## B. 코드 확인 추가 갭 (명세 `🔲`에 안 잡힌 것)

| 대상 필드/섹션 | 현재 상태 | 필요한 변경 | 관련 절 |
|---|---|---|---|
| `pattern` 5종 | ①이 `"Center"` 고정(`vlm.py`)이라 `Edge-Ring`/`Scratch`/`Unknown`/`Normal` 그룹이 생기지 않는다(API 정규화 로직은 `schemas.py`에 구현됨 — 실데이터 경로 미검증) | VLM/CNN 연동 후 `Unknown` → `status:"unmapped"` 경로 실검증 | §2.2 · §2.6 · §3 |
| telemetry `t0` · `unit` | 항상 `null` / `""` (계약상 유효 — BACKEND_DECISIONS.md D7·D11) | 변화점 탐지 연동 시 `t0` 채움, 시뮬레이터에 단위 메타 추가 시 `unit` 채움 | §2.7 |
| 실서버 E2E 미검증 | fab.db 부재로 배치 실행~근거 조회 전 구간을 실데이터로 못 돌렸다(fab.db 없이 가능한 스모크는 통과: 202→failed 흐름·404/422/빈 목록·CORS) | fab.db 빌드 후 AGENT_GUIDE §3 슬라이스별 curl + 화면 확인 | 전 절 |
