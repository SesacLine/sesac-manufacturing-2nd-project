# SECS/GEM MCP 문서 ↔ KG 출력 정합성 검토

> 작성: 2026-07-11
> 대조 기준:
> - `SECS GEM MCP 문서_v0 1 (작업중).md` (최종 편집 2026-07-11 16:11)
> - `outputs/hypotheses.json` (2026-07-11 16:12 생성, 가설 175건)
> - `schema_v2.md` (v2.2)
>
> 이 문서는 **검토 결과만** 담는다. 코드·문서 수정은 하지 않았다.

---

## 0. 전제 경고 — 현재 그래프에 조작 문서 기반 엣지가 들어가 있음

검토 중 확인한 사실. 현재 Neo4j의 `ARISES_IN` 9건 중 **6건의 근거가 `pattern_process_extended.txt`**다
(Center→CMP/CLEAN, Edge-Ring→CMP/CLEAN, Scratch→CMP/CLEAN). 이 파일은 문헌 근거 없이
임의로 작성된 것으로, 폐기하고 형상(SpatialSignature) 노드 + 실제 레퍼런스로 대체하기로 결정된 상태다.

**영향:** 지금 `hypotheses.json`(175건)의 provenance 일부가 조작 문서를 가리킨다.
MCP 문서의 D3(Faithfulness)·E2(사실만 인용) 원칙과 정면 충돌하므로,
**형상 노드 작업 완료 후 재적재한 출력을 기준으로 agent 연동을 시작해야 한다.**
아래 항목들은 이 전제 위에서 읽을 것.

---

## 1. 정합 확인 (충돌 없음)

| # | 항목 | 근거 |
|---|---|---|
| OK-1 | **3클래스 명칭 일치** — VLM 출력 = MCP 문서(A0) = KG `DefectPattern.id` 모두 `Center`/`Edge-Ring`/`Scratch` | 시드 정렬 작업 완료됨 |
| OK-2 | **T5 호출 인자 공급 가능** — A3의 `params=[KG가 지목한 파라미터]`는 `hypotheses.json`의 `verification.fab_table` + `path.evidence` + `direction`으로 그대로 조립 가능 (E3의 "전체 덤프 금지"도 자연 충족) | `[자동]` 가설 구조 |
| OK-3 | **D3 Faithfulness 요건 충족** — "KG 메커니즘 연결 문장"은 `sentence`(합성 문장) + `path`(기계가독 경로) + `provenance`(chunk_ids/quotes)로 제공됨 | ① 작업 완료분 |
| OK-4 | **E2 원칙과 설계 철학 일치** — 툴은 사실만, 원인 서술은 KG 교차 후. KG 출력도 인스턴스 주장 없이 메커니즘만 담음 (lot/장비/시각 없음) | schema v2.2 |
| OK-5 | **C4 스코프 일치** — "전공정~wafer test" 스코프 = KG 6스텝. 후공정·RTP 등 스코프 밖 원인은 KG에서 `[근거없음]`으로 이미 격리됨 | 검증 등급 3단 |
| OK-6 | **B1(negative evidence)은 KG와 독립** — KG 출력이 방해하지 않음. 가설마다 필수 수행은 agent 몫 | — |
| OK-7 | **Scratch 원인 일부 실제 겹침** — 문서의 "CMP 패드 마모"↔KG `worn_pad→replace_polishing_pad`, "슬러리 대입자"↔KG `slurry_particle_agglomeration` | 교과서 CMP 표 |

---

## 2. 충돌 / 공백 목록

심각도: ■■■ 연동 차단급 / ■■ 설계 결정 필요 / ■ 소소한 규약 문제

### [X1] ■■■ 파라미터 어휘 불일치 — 문서의 예시 파라미터가 fab 어휘에 없음

- MCP 문서가 KG가 지목할 것으로 예시하는 파라미터:
  `에지 플라즈마 밀도`(A3), `샤워헤드 유량`(A3), `패드 사용 시간`(A6), `브러시 압력`(A6), 슬러리 `입자` 신호(A6)
- fab 어휘(`seeds/parameters.json` 20종 = `telemetry.param`)에 위 항목이 **없다**.
  CMP는 `down_force`/`slurry_flow` 둘뿐, CLEAN에 브러시 계열 없음, ETCH에 플라즈마 밀도 없음.
- KG는 fab 어휘만 지목할 수 있으므로(공정 조건부 resolver), A6의 "사용량 파라미터" 체인은
  현재 어휘로는 **성립 불가**. 실측: Scratch의 `[자동]` 가설 0건.
- **수정 위치:** 협의 필요 — ① fab.db generator에 파라미터 추가(→ `fab.md`, `seeds/parameters.json`,
  5번 `Literal` 동시 갱신) 또는 ② MCP 문서의 예시를 기존 20종으로 교체.
  **파라미터 어휘의 정본이 어디인지**를 먼저 정해야 함.

### [X2] ■■■ 클래스×원인 매핑표(3.1)와 KG 내용 불일치

- 문서의 후보 원인 9종(클래스당 3종, 배정 확률 포함)은 **fab 시나리오 설계 기준**이고,
  KG의 원인은 **교과서·논문 추출** 결과라 어휘와 구성이 다름.
  예: 문서 "샤워헤드 막힘"(Center 55%)에 해당하는 KG Cause 없음.
- 특히 **세정(CLEAN) 계열 3종**(노즐 이상·브러시 접촉·세정 문제)은 KG에 근거 문헌이 전혀 없음.
  CLEAN은 FailureMode 1개뿐(빈 공정) → `ARISES_IN → CLEAN` 엣지가 있어도(현재는 조작 문서 기반)
  완전 경로가 안 만들어져 **CLEAN 가설 0건**.
- 문서의 매핑표를 정답 시나리오로 쓴다면, agent가 KG에서 그 원인을 찾지 못해
  "KG 메커니즘 연결 문장 부재 → 재계획"(D3)에 걸리는 역설 발생.
- **수정 위치:** 협의 필요 —
  ① CLEAN(및 필요시 각 원인) troubleshooting 문서를 실제 레퍼런스로 추가 (STATUS P5, 사용자 예정 작업)
  ② 형상 노드 + 레퍼런스로 패턴→공정 커버리지 확보 (진행 예정)
  ③ 그래도 안 덮이는 원인은 문서 매핑표 쪽을 KG 실상에 맞춰 조정

### [X3] ■■ 가설 수(175건) × Hypothesis Loop = 툴 호출 폭발

- 문서 2장: "후보 원인마다 A1→A2~6→T4→T9" 체인 실행. 가설당 최소 4~6회 호출.
  175건 × 5회 ≈ **875회** — E3/E4가 막으려는 폭주가 루프 구조에서 재발.
- 실측 구조상 **고유 검증 단위는 훨씬 적다**: `(step, evidence)` 기준
  Center 4+41, Edge-Ring 8+64, Scratch 0+8. 같은 `(ETCH, rf_power)`를 지목하는 가설 여러 건이
  T5 호출 1회를 공유할 수 있음.
- **수정 위치:** KG 측(6번) — `hypotheses.json`에 검증 단위 그룹 키 또는 `checks[]` 인덱스 추가
  (가설 N건 → 고유 검증 M건 매핑). + agent 측 — 루프를 "가설별"이 아니라 "검증 단위별"로 돌도록 명시.
  STATUS ③(점수 재설계)의 Top-K/우선순위와도 직결.

### [X4] ■■ Alarm evidence 부재 — A4/B3가 요구하는 "신호→결함 KG 경로"가 알람엔 없음

- B3 판정 3문항 중 ③ "KG에 해당 신호→결함 메커니즘 경로가 있는가?"
  — 알람은 KG에 노드/경로가 전혀 없으므로 **모든 알람이 자동으로 '교란 신호' 판정**됨.
  A4(알람 동시성) 체인이 지지 증거를 만들 수 없는 구조.
- `schema_v2.md`에 "향후 확장: `alarm` 테이블용 `Alarm` evidence 노드" 로 이미 예고돼 있음.
- **수정 위치:** KG 측 — `Alarm` evidence 노드(`fab_table='alarm'`, `[반자동]`) 추가.
  단, 문헌에 알람 서술이 있어야 추출 가능 — 없으면 문서 B3 규칙을
  "Parameter 경로가 있는 장비의 알람은 간접 연결로 인정" 식으로 완화하는 협의 필요.

### [X5] ■■ 시나리오 체인 라우팅 정보가 KG 출력에 없음

- 문서는 원인 유형별 분기를 전제: 정비→A2, 파라미터→A3, 알람→A4, recipe→A5, 소모품→A6.
- `evidence_label`로 부분 유도 가능(Parameter→A3, Maintenance→A2, Recipe→A5)하지만:
  - **A2(일반 정비)와 A6(소모품 마모)을 구분할 정보가 없음** — 둘 다 `Maintenance`.
    A6은 Scratch 특화 체인이라 구분이 실전에서 중요.
  - `[근거없음]` 가설은 배정될 체인이 아예 없음 (아래 X6).
- **수정 위치:** KG 측(6번) — `scenario_hint` 필드 추가(evidence_label + 소모품 여부로 산출)
  또는 매핑 규칙을 별도 문서로 합의. Maintenance 노드에 `consumable: true/false` 속성 검토 (P3 dedup과 함께).

### [X6] ■■ `route=direct`(ATTRIBUTED_TO) 가설의 처리 절차가 문서에 없음

- direct 가설은 `step=null` — A1이 `step` 옵션으로 T3를 좁히는 첫 단계부터 어긋남
  (문서에 "결과 없으면 step 미지정 재호출" fallback은 있으나 direct 가설용 절차는 아님).
- `[근거없음]` 가설(evidence 없음)은 A 체인 어디에도 들어갈 수 없음.
  문서 C1(판단 불가)로 빠질 것도 아니고, C4(범위 밖)와도 다름 — **"검증 계획 없음, 문헌 참고용"**이라는
  제3의 처리 경로가 필요.
- **수정 위치:** MCP 문서 측 — A0~A1 사이에 "KG 후보 분류" 단계를 명시
  (step 보유→표준 루프 / direct+evidence→step 미지정 T3 / 근거없음→참고 정보로만 evidence table에 기재).

### [X7] ■ Maintenance id가 T7 `parts` 필드와 자동 대조 불가

- T7 반환의 "교체 부품" 텍스트와 KG `Maintenance.id`
  (예: `inspect_whether_residual_copper_cleaning_finished_on_patterned_wafer`)는 형태가 달라
  키워드 매칭조차 어려움. `[반자동]` 정의("판정은 사람")와는 일치하지만,
  A6처럼 agent가 "교체 부품 필드에서 패드/브러시 확인"을 하려면 검색 키워드가 필요.
- **수정 위치:** KG 측 — Maintenance dedup(P3) 시 `parts_keyword` 같은 정규화 속성 추가
  (예: `replace_polishing_pad` → `["pad"]`).

### [X8] ■ step 표기 규약 — 문서는 한국어, KG/fab은 코드

- 문서: `step=증착`, `step=세정`. KG·`lot_history.step`: `DEPO`, `CLEAN`.
  T3의 `step` 파라미터 규약을 코드(`LITHO/ETCH/DEPO/CMP/CLEAN/EDS`)로 통일 필요.
- **수정 위치:** MCP 문서 측 (표기만 바꾸면 됨).

### [X9] ■ 배정 확률(55%/60%…)의 출처가 KG에 없음

- 문서 매핑표의 수치 prior에 대응하는 KG 값은 `occurrence_prior`(high/mid/low, LLM 자기평가)뿐.
  수치 prior가 필요하면 출처를 정해야 함: 문서 하드코딩 유지 / KG 관계 속성으로 이관 /
  fab 검증 이력 기반 posterior(STATUS ③ 장기안)로 대체.
- **수정 위치:** 협의 필요. 단기적으론 문서 하드코딩을 유지하고 KG와 분리해 두는 것도 가능.

### [X10] ■ KG 질의 인터페이스 미정 (문서엔 "MCP 외부"라고만)

- A0은 VLM 클래스 **1건**으로 진입하는데, 현재 `hypotheses.json`은 3패턴 배치 생성물.
  agent가 (a) json에서 해당 `pattern` 섹션만 읽는 규약인지, (b) 패턴 단건 질의 모드
  (예: `PATTERN=Edge-Ring python 6_ask_graphrag.py`)인지, (c) Neo4j 직접 질의인지 미정.
- VLM이 3클래스 외/형상만 넘기는 경우(A0 분기 2)는 형상 노드 도입 후 "형상 단건 질의"도 필요해짐.
- **수정 위치:** 협의 필요 (STATUS ②). 배치 json 재사용이 가장 싸고, 실시간성이 필요하면 단건 모드 추가.

---

## 3. 결정 필요 사항 (요약)

| # | 질문 | 연관 항목 |
|---|---|---|
| Q1 | 파라미터 어휘의 정본은? fab.db generator를 늘릴 것인가, 문서 예시를 20종에 맞출 것인가 | X1 |
| Q2 | 문서의 클래스×원인 매핑표는 "정답 시나리오"인가 "예시"인가? 정답이면 KG 문헌을 그에 맞춰 보강해야 함 | X2 |
| Q3 | CLEAN troubleshooting 문서를 언제/어떤 레퍼런스로 추가할 것인가 | X2 |
| Q4 | `Alarm` evidence 노드를 추가할 것인가, B3 규칙을 완화할 것인가 | X4 |
| Q5 | agent 루프의 단위: 가설별인가 검증 단위(`step`×`evidence`)별인가 | X3 |
| Q6 | KG 질의 인터페이스: 배치 json / 단건 CLI / Neo4j 직접 | X10 |
| Q7 | 수치 prior의 출처 | X9 |

## 4. 권장 착수 순서

1. **`pattern_process_extended.txt` 제거 + 형상 노드 작업** (§0 전제 해소 — 이것 없이는 어떤 연동 테스트도 오염된 provenance 위에서 돈다)
2. X1 어휘 정본 결정 (fab generator와 시드를 한 번에 정렬)
3. X3+X5: `hypotheses.json`에 검증 단위 그룹 + `scenario_hint` 추가 (STATUS ①의 잔여분과 묶어서)
4. X6+X8: MCP 문서 측 소폭 보강 (KG 후보 분류 단계, step 코드 표기)
5. X2/X4: 문서 보강(CLEAN, 알람 서술) — 레퍼런스 확보되는 대로
