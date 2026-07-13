# RCA GraphRAG 파이프라인 — 진행 상황 & 남은 문제

> 마지막 업데이트: 2026-07-10
> 웨이퍼맵 불량 원인분석(RCA) 지식그래프 파이프라인. **스키마 정본은 `schema_v2.md` (v2.2).**
> `schema.md`는 v1 기록용. 옛 Text2Cypher 질의 코드는 `6_ask_graphrag_backup.py`.

---

## 1. 현재 상태 (요약)

```
data/raw/ 문헌 → 표 행 단위 청킹 → Neo4j 적재 → LLM KG 추출(+검증 규칙) → 결정적 순회 + LLM 문장 합성
```

**전 단계 실행 검증 완료.** 최신 실행 수치 (문헌 5편 → 청크 95개):

| | (v2.3, 2026-07-12 앵커 보강 후) |
|---|---|
| 노드 | FailureMode 112 · Cause 234+ · Maintenance 108 · Recipe 20 (+시드: DefectPattern 3 · **SpatialSignature 3** · ProcessStep 6 · Parameter 20) |
| 앵커 엣지 | ARISES_IN: Center→{CMP,DEPO,LITHO} · Edge-Ring→{CLEAN,ETCH} · Scratch→{CMP} / **FORMS_IN: ring@edge→{CLEAN,ETCH}** / ATTRIBUTED_TO 34 |
| 가설 | **총 381건** — Center 255 (자동29/반자동117/근거없음109) · Edge-Ring 79 (5/32/42) · Scratch 47 (3/13/31) |

가설 수가 는 주원인은 `[근거없음]` 노출 (공정 경유 경로의 VERIFIED_BY를 OPTIONAL로 —
evidence 없는 원인이 통째로 사라지던 비대칭 제거). 형상 경유 가설이 표면상 0건인 것은
현재 FORMS_IN이 닿는 공정을 ARISES_IN도 전부 덮어서 dedup이 step 경로를 대표로 남기기 때문
(설계 의도. 형상 경로의 독립 가치는 미지 패턴 + ARISES_IN 부재 시의 fallback).

질문은 `"{패턴} 결함 패턴이 나타나는 근본 원인은 무엇인가요?"` 하나로 고정.
그래프 순회는 고정 Cypher(결정적), LLM은 경로를 한국어 가설 문장으로 옮기는 역할만.

**가설이 125건인 이유 (설계 의도):** 경로 수 = 각 홉 팬아웃의 곱
(`패턴 → 공정 1~2 × 공정당 FailureMode 8~37 × FM당 Cause ~2 × Cause당 Evidence ~1.4`).
`ProcessStep` join에는 의미 필터가 없어서, 의심 공정의 **모든** 고장 모드가 후보가 된다
(막 균열이 Center 후보로 올라오는 이유). recall을 취하고 precision은 fab 검증에 미루는 설계.

---

## 2. 파일 구조

### 데이터 (`data/`)
- `raw/` — 실문헌 5편 (파이프라인 입력)
  - `center_pattern_cause.txt`, `pattern_cause`, `scratch_pattern_cause` — 문서 A (패턴→공정 산문)
  - `Semiconductor Devices..._troubleshootingTABLE.md` — 문서 B (교과서 트러블슈팅 표 82행, DEPO/LITHO/ETCH/CMP)
  - `ref56_table1_pattern_causes.md` — 문서 C (ref56 논문 Table 1, 패턴→원인 직결)
  - `_reference/` — 교과서 본문 339KB. **로더가 읽지 않음** (하위 디렉토리 제외)
- `seeds/` — 고정 vocabulary 3종
  - `defect_patterns.json` (3종, VLM 출력 클래스와 동일해야 함)
  - `process_steps.json` (6종, join key: `lot_history.step`)
  - `parameters.json` (20종, join key: `telemetry.param`, `steps` 필드가 별칭 해석 스코프)

### 파이프라인 코드 (루트)
- `0_reset.py` — Neo4j DB 전체 초기화 (스키마 변경 후 필수)
- `1_test_connection.py` — 연결 확인
- `2_load_txt.py` — `data/raw/` 로드 (.txt/.md/무확장자, 빈 파일·하위 디렉토리 제외)
- `3_split.py` — 표 행 단위 청킹 (표 유형 3종 판별: troubleshooting/quality/pattern_cause) + 산문 재귀 분할
- `4_ingest_chunks_to_neo4j.py` — 제약 + 시드 앵커(:Evidence 슈퍼라벨 포함) + Document/Chunk
- `5_build_kg_from_chunks.py` — LLM 추출 + 검증 규칙 6종(`schema_v2.md` 참조) + 저장
- `6_ask_graphrag.py` — 패턴별 가설 전건 출력 (`TOP_K` 환경변수로 상한 조절 가능)

---

## 3. 작업 로그 (2026-07-10, 시간순 압축)

1. **v1 → v2.1**: `Equipment`/`PART_OF` 제거, `INVOLVES_PARAMETER` → **`VERIFIED_BY`** 다형화
   (`Parameter`/`Maintenance`/`Recipe`, `:Evidence` 슈퍼라벨). v1에서 고아로 버려지던
   `improper maintenance`·`incorrect process recipe` 원인이 검증 종착점을 얻음.
2. **Parameter 해석을 ProcessStep 조건부로**: `temperature`가 공정마다 다른 변수
   (LITHO `stage_temp` / ETCH `temperature` / DEPO `susceptor_temp` / CLEAN `chemical_temp` / EDS `chuck_temp`).
   `validate_kg`를 두 패스로 분리(Cause→공정 파악 후 Parameter 해석). 공정-변수 불일치 0건 확인.
3. **문서 소스를 `data/raw/`로 전환**: 표 행 단위 청커(행=청크, 열 역할 이름표),
   교과서 본문 제외, `OCCURS_IN` grounding 가드 추가, 산문 DefectPattern 인식 개선.
4. **`ATTRIBUTED_TO` 신설 (v2.2)**: ref56 Table 1(패턴→원인 직결, 공정 미상)을 담는 엣지.
   Scratch 행이 CMP를 명시해 `ARISES_IN: Scratch→CMP`도 정당하게 성립 → Scratch 가설 0건 문제 해소.
5. **검증 등급 3단**: `[자동]`(Parameter, agent가 판정) / `[반자동]`(Maintenance·Recipe,
   agent 조회+사람 판정) / `[근거없음]`(evidence 없는 문헌 직결). 축은 "fab.db에 있느냐"가
   아니라 **"agent가 스스로 판정할 수 있느냐"**.
6. **출력 상한 제거**: `TOP_K=3` 삭제(환경변수로만 조절). dedup 키를 전체 경로로 교정해
   뭉개지던 15건 복원. 문장 합성을 배치(12건)로 나누고 부족분은 사실 기반 문장으로 채움 → 125건 전부 출력.
7. **(07-12) v2.3 형상 레이어**: `SpatialSignature` 노드(고정 3종, (형상,구역) 쌍) +
   `HAS_SIGNATURE`(시드 결정적) + `FORMS_IN`(문서 D 추출). 조작 문서
   `pattern_process_extended.txt` **삭제** — 그것이 위조하던 커버리지를 Liao et al. 2026 문서
   (문서 D, 섹션 헤딩 추가)가 정당하게 대체. **앵커 보강 패스** 도입(`ANCHOR_PASSES`, 기본 3):
   패턴/형상 언급 청크만 K회 재추출·합집합해 진입점 엣지의 비결정성 완화(P4 부분 해소).
   공정 경유 쿼리의 `VERIFIED_BY`를 OPTIONAL로 바꿔 evidence 없는 원인도 `[근거없음]`으로 노출
   (direct 경로와의 비대칭 제거 — 가설 수가 크게 는 주원인).
8. **(07-12) 매핑 테이블 오버레이**: `mapping_table.yaml`(MCP 문서 3.1 표 기반, 패턴별 큐레이션
   원인 + telemetry_signature + prob + citation)을 6번이 읽어, `[근거없음]` 가설의 Cause를
   매칭 키워드/유사도(부분일치 > 자카드 > difflib, 임계 0.55)로 대조해 검증 신호를 채운다.
   (07-13) yaml은 MCP/fab 소유라 **원본 그대로 유지** — 매칭 키워드는 KG 모듈의
   `MAPPING_MATCH_KEYWORDS` 상수(키 = 표의 cause id)로 이전. 표 항목이 늘면 이 상수만 확장.
   **그래프는 건드리지 않음** — 출력 조립 시점 오버레이. 채워진 가설은 `mapping` 블록으로 출처 명시.
   param이 fab 20종 안에 있을 때만 `[자동]` 승격 (pad_usage_hours는 힌트만, 정합성검토 X1 가드).
   실측: 381건 중 27건 채움, 26건 승격 (자동 37→63건). prob 노출로 X9(수치 prior 출처)도 부분 해소.
9. **(07-13) v2.4 형상 레이어를 추출 방식으로 전환**: 결정적 시딩을 **3앵커로 축소**
   (DefectPattern/ProcessStep/Parameter — 전부 외부 시스템과 문자열 join하는 것들).
   `seeds/signatures.json` 삭제, `HAS_SIGNATURE`도 문서에서 LLM 추출.
   VLM 출력이 **자유 서술**로 확정되면서 정리된 설계: 텍스트→어휘 분류 층이 어차피 필요하므로
   어휘만 코드 enum(shape 6종 × zone 4종)으로 닫고 id는 `{shape}@{zone}` 조합 —
   허브 노드 파편화가 구조적으로 불가능. 가드: 형상 표현이 원문에 있어야 인정 + 국소성.
   VLM 입력 모듈(미래)은 자유 서술을 같은 enum으로 분류해 진입 (문서 추출과 동일한 분류 계약).


---

## 4. 남은 문제

### [P1] 검증 신호가 `Maintenance`로 쏠림 (143건 중 Maintenance 110 : Recipe 17 : Parameter 16)
- `[원인] A. Change in RF power`가 `Parameter rf_power`로 가야 하는데, LLM이 조치 열의
  `Check RF generator`를 보고 `Maintenance`로 붙이는 추출 편향.
- `[자동]` 가설이 그만큼 희소해짐 (Edge-Ring 53건 중 자동 3건뿐).
- **해결안**: 프롬프트에 우선순위 명시 — "원인이 계측 변수의 이상이면 반드시 Parameter 우선,
  Maintenance는 원인이 정비 그 자체일 때만".

### [P2] 가설 점수 체계가 타당성이 없음 — 재설계 필요
현재 점수 = `(검증등급, occurrence_prior, confidence평균)` 튜플 내림차순. **믿을 만한 성분이
검증등급 하나뿐**이고, 그마저 "확인하기 쉬운 순서"이지 "그럴듯한 순서"가 아니다.

무엇이 잘못됐나:
- **뒤 두 성분은 LLM 자기평가다.** 계산도 통계도 아니고, 근거 수·교차검증이 반영되지 않는다.
  실측상 거의 전부 `5.0`/`high` 동점이라 같은 등급 안 순서는 Neo4j 반환 순서에 가깝다.
- **평균이 약한 고리를 감춘다.** `(5,5,2)` 경로와 `(4,4,4)` 경로가 똑같이 4.0.
  인과 사슬은 가장 약한 고리만큼만 믿을 수 있으므로 최솟값이 맞다.
- **경로 4개 관계 중 3개만 집계.** `OCCURS_IN`의 confidence가 점수에 안 들어간다.
- **근거의 양이 무시된다.** 문서 세 곳이 말하는 원인과 한 문장이 스친 원인이 같은 점수.
  `chunk_ids`로 기록은 하면서 쓰지 않는다.
- **저장 버그가 점수를 오염시킨다.** 같은 관계가 여러 청크에서 나오면 `SET`이 confidence를
  마지막 값으로 덮어쓴다 (chunk_ids는 누적되는데 confidence는 아님) → 처리 순서에 따라 점수가 달라짐.
- **`coalesce(..., 3)`이 결측을 "보통 신뢰도"로 둔갑시킨다.**

재설계 방향 (→ Next Action Steps ③):
1. confidence: 평균 → **경로 최솟값**, `OCCURS_IN` 포함, 저장 시 `max()` 유지, coalesce 제거
2. **근거 강도**를 독립 성분으로: 근거 청크 수 + 출처 문서 다양성 (같은 문서 반복 < 서로 다른 문서)
3. 결정적 tiebreak (이름순) — 실행마다 순서가 바뀌지 않게
4. 장기적으로는 **fab 검증 결과가 사후 점수(posterior)** — 채택/기각 이력이 쌓이면
   그것이 진짜 순위이고, 문헌 기반 점수는 prior 역할로 물러난다 (②의 Hypothesis 노드와 연결)

### [P3] Maintenance 노드 과다 + 미중복제거 (106개)
- `chamber_wet_clean`처럼 유의미한 것과 `inspect_whether_residual_copper_cleaning_finished...`
  같은 일회성 장문 표현이 섞임. 임베딩 기반 dedup / 정규화 필요.

### [P4] 추출 비결정성 — 앵커에 한해 완화됨
- 같은 청크에서 실행마다 결과가 다름 (`temperature=0`으로도 안 잡힘). 실측: 한 실행에서
  Scratch의 ARISES_IN이 전부 증발해 가설 4건으로 붕괴한 적 있음.
- **완화**: 진입점 엣지(ARISES_IN/FORMS_IN/ATTRIBUTED_TO)는 패턴/형상 언급 청크(~19개)만
  `ANCHOR_PASSES`회 재추출해 합집합 (5번에 내장, MERGE라 중복 없음, grounding 가드 매 패스 적용).
- **잔여**: FailureMode/Cause/VERIFIED_BY 층은 여전히 1패스. 예: "insufficient rinsing"→`rinse_time`
  매핑을 프롬프트에 예시까지 줬는데도 gpt-5.4-mini가 안 만든다. 모델 업그레이드 또는 전층 다회화 검토.

### [P5] 커버리지 공백
- `CLEAN`/`EDS`: 트러블슈팅 문헌 없음 (결정: 빈 공정으로 두고 문서 추가 예정).
- ref56 Table 1의 5개 패턴(`Donut`, `Edge-Loc`, `Loc`, `Near-Full`, `Random`)은 고정 3종 밖이라 버려짐.
  VLM 클래스를 9종으로 늘리면 그대로 살아남는 구조.
- 표에 있으나 fab에 없는 변수(`gas flow @ ETCH`, `film stress` 등)는 옳게 버려지지만 가설도 줄어듦.

### [P6] ProcessStep join에 의미 필터 없음
- 의심 공정의 모든 고장 모드가 패턴의 후보가 됨 (Center에 막 균열이 1순위로 올라옴).
- 설계 의도(recall 우선)이나, 노이즈가 크면 `FailureMode`에 공간 시그니처 속성을 붙이거나
  LLM 재랭킹을 얹는 방안 검토.


---

## 5. Next Action Steps

### ① `6_ask_graphrag.py` 출력에 메타정보·로그 구조 추가 ← **일부 완료**
- **완료:** 사람용 stdout과 병행해 **`outputs/hypotheses.json`** 저장 (가설 125건 확인).
  구조: `meta`(생성 시각, 모델, DB, TOP_K, 등급 범례, 점수 주의문) +
  `questions[]`(패턴별 counts) + `hypotheses[]`(rank / sentence / tier / route /
  path{step, failure_mode, cause, evidence, evidence_label} / verification{fab_table, direction} /
  score{tier, occurrence_prior, confidence} / detail / **provenance{chunk_ids, quotes}**).
  `[근거없음]`은 `evidence: null`, `fab_table: null`로 명시.
- **남음:** 실행 로그(5번의 버림 사유, 6번의 배치 경고)를 파일로 남기는 부분.
  그래프 스냅샷 수치(라벨/관계 카운트)를 meta에 포함할지도 ②에서 결정.

### ② hypothesis agent와의 연결고리 설계 ← **다음 작업**
- `[자동]` 가설: `Parameter.id` + `direction` + lot_id → `lot_history`로 equipment_id/ts 바인딩
  → `telemetry` 조회 → `fab_model.yaml` 정상범위 비교 → 채택/기각. **agent가 끝까지.**
- `[반자동]` 가설: agent가 `maintenance`/`lot_history` 조회 결과를 첨부해 사람에게 전달.
- 인터페이스 결정 필요: ①의 jsonl을 agent 입력으로 쓸지, agent가 Neo4j를 직접 순회할지.
- `Hypothesis` 투영 노드(경로를 평탄화한 노드로 굳혀 검증 결과를 기록할 자리)를 만들지 여부도
  이때 함께 결정하는 게 자연스러움.

### ③ 가설 점수 체계 재설계 (P2) ← **다음 작업**
현행 점수는 검증등급 외에는 순위 근거가 없다 (상세는 P2).
- 단기: min-confidence(OCCURS_IN 포함) + 근거 청크 수·문서 다양성 + 결정적 tiebreak
  + 저장 시 confidence `max()` 유지. 전부 `6_ask_graphrag.py`/`5번` 소폭 수정으로 가능.
- 장기: fab 검증 채택/기각 이력을 사후 점수로 (②의 `Hypothesis` 노드에 기록 → 문헌 점수는 prior).
- ①의 jsonl에 점수 성분을 분해해서 담아야 agent와 사람이 순위 근거를 검산할 수 있다.

### ④ 그 외 후보 (우선순위 낮음, P1·P3~P6 대응)
1. Maintenance 편향 프롬프트 수정 (P1) — `[자동]` 가설을 늘리는 가장 싼 수
2. Maintenance dedup (P3)
3. CLEAN/EDS 트러블슈팅 문서 추가 (P5)
4. DefectPattern 9종 확장 — VLM 클래스와 정렬 (P5)
5. VLM 관측 입력(JSON) 처리 — 현재는 고정 질문 3개 순회
