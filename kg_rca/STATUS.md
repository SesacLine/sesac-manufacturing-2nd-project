# RCA GraphRAG 파이프라인 — 진행 상황 & 남은 문제

> 마지막 업데이트: 2026-07-22
> 웨이퍼맵 불량 원인분석(RCA) 지식그래프 파이프라인. **스키마 정본은 `../docs/KG_schema_v1.2.md` (v2.4).**
> 데이터 모델 정본은 `데이터 모델 설계_v3.0.md`(07-22, 형상 진입점 + 모폴로지).
> `backup/schema.md`는 v1 기록용. 옛 Text2Cypher 질의 코드는 `backup/6_ask_graphrag_backup.py`.

---

## 1. 현재 상태 (요약)

```
data/raw/ 문헌 → 표 행 단위 청킹 → Neo4j 적재 → LLM KG 추출(+검증 규칙) → 결정적 순회 + LLM 문장 합성
```

**전 단계 실행 검증 완료.** 최신 실행 수치 (v2.4 + CLEAN 문서, 2026-07-13 / 문헌 6편 → 청크 111개):

| | |
|---|---|
| 노드 | FailureMode 120 · Cause 272 · Maintenance 134 · Recipe 18 · SpatialSignature(추출) 4 (+시드: DefectPattern 3 · ProcessStep 6 · Parameter 21) |
| 앵커 엣지 | ARISES_IN: Center→{CMP,DEPO,LITHO} · Edge-Ring→{CLEAN,DEPO,ETCH} · Scratch→{CLEAN,CMP} / FORMS_IN: blob@center→{CMP,DEPO} |
| 가설 | **총 642건** — Center 297 · Edge-Ring 249 (CMP 경유 51 포함) · Scratch 96 |
| 매핑표 대응 | MCP 매핑표(취소선 제외 8항목) 패턴→공정 **누락 0** — X2 완전 해소 |

`[근거없음]`이 큰 비중인 것은 의도된 노출(evidence 없는 원인도 가설로 냄).
CLEAN 경유 가설 72건(Scratch 36 + Edge-Ring 36), CLEAN 최초의 `[자동]` 경로
(`insufficient_rinsing→rinse_time low`) 확보. 형상 경유 가설이 표면상 0건인 것은
FORMS_IN이 닿는 공정을 ARISES_IN도 덮어서 dedup이 step 경로를 대표로 남기기 때문
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
  - `cause_center.txt`, `cause_edgering.txt`, `cause_scratch.txt` — 문서 A (패턴→공정 산문)
  - `table_sze_troubleshooting.md` — 문서 B (교과서 트러블슈팅 표 82행, DEPO/LITHO/ETCH/CMP)
  - `table_ref56_patterns.md` — 문서 C (ref56 논문 Table 1, 패턴→원인 직결)
  - `paper_liao_rag.txt` — 문서 D (Liao et al. 2026, 패턴/형상→공정)
  - `paper_edgering_cmp.txt` — 문서 E (Xie & Boning 2005, Edge-Ring→CMP)
  - `_reference/` — 교과서 본문 339KB. **로더가 읽지 않음** (하위 디렉토리 제외)
- `docs/` — **[v3.0] 전문가 암묵지 목업 8편** (파이프라인 입력, 07-22 로더 편입)
  - `doc_A_wafermap_patterns.txt` — 패턴→공정 + `HAS_SIGNATURE`(형상노드 정의)
  - `doc_B~G_*_troubleshooting.txt` — 공정별 내부 체인(`OCCURS_IN`/`CAUSED_BY`/`VERIFIED_BY`)
  - `doc_H_spatial_morphology_heuristics.txt` — **형상·모폴로지→공정**(`FORMS_IN` + density/continuity/angular_coverage/clock_positions)
- `seeds/` — 고정 vocabulary 3종
  - `defect_patterns.json` (3종, VLM 출력 클래스와 동일해야 함)
  - `process_steps.json` (6종, join key: `lot_history.step`)
  - `parameters.json` (21종 — 07-13 `pad_usage_hours` 추가, join key: `telemetry.param`, `steps` 필드가 별칭 해석 스코프)

### 파이프라인 코드 (루트)
- `0_reset.py` — Neo4j DB 전체 초기화 (스키마 변경 후 필수)
- `1_test_connection.py` — 연결 확인
- `2_load_txt.py` — **[v3.0] `data/raw/` + `data/docs/` 로드** (.txt/.md, 빈 파일·하위 디렉토리 제외)
- `3_split.py` — 표 행 단위 청킹 (표 유형 3종 판별: troubleshooting/quality/pattern_cause) + 산문 재귀 분할
- `4_ingest_chunks_to_neo4j.py` — 제약 + 시드 앵커(:Evidence 슈퍼라벨 포함) + Document/Chunk
- `5_build_kg_from_chunks.py` — LLM 추출 + 검증 규칙 6종(`../docs/KG_schema_v1.2.md` 참조) + 저장
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
10. **(07-13) CLEAN 커버리지 확보 + 앵커 모델 옵션**: `...TABLE+CLEAN.md`(6장 산문 재구성
   표 6행) 투입 → CLEAN FailureMode 7종, Scratch·Edge-Ring의 CLEAN 경유 가설 각 36건.
   진입점 재발 문제 둘을 함께 해결: ① 프롬프트에 **헤딩 규칙** 추가("## Scratch pattern —
   Cleaning" 헤딩 = 그 단락은 해당 패턴 서술 → ARISES_IN 생성), ② mini가 예시를 줘도 못 만드는
   엣지는 **`ANCHOR_MODEL`** 환경변수로 보강 패스만 상위 모델 사용 (gpt-5.5가 c09에서 1회에
   `Scratch→CLEAN` + `insufficient_rinsing→rinse_time`[CLEAN 최초 자동] 추출 성공).
   구판 표 문서는 `_reference/`로 이동(이중 적재 방지). X2잔여는 `Edge-Ring→CMP`만 남음.
11. **(07-13) `Edge-Ring→CMP` 확보 → X2 완전 해소**: `edgering-cmp.txt`(Xie & Boning,
   MIT/MRS 2005 — CMP edge over-polish 기전 + 큐레이션 메타데이터 "Related Defect: Edge Ring")
   투입. retaining ring(부품)↔ring(패턴) 어휘 함정은 프롬프트 가드로 선차단, gpt-5.5 2패스로
   추출 — 본문 청크에서 가짜 패턴 0건 확인. 개명 중복 문서(`pattern_cause`→
   `edge-ring_pattern_cause.txt`)의 그래프 잔재 정리. **MCP 매핑표 8항목 패턴→공정 누락 0** —
   Edge-Ring이 4공정(CLEAN/CMP/DEPO/ETCH) 도달, 가설 총 642건.
12. **(07-13) `scenario_hint` + `Maintenance.consumable` — 정합성검토 X5/Q4 해소**:
   사실은 그래프에(`consumable`, 추출 시 LLM 판단), 라우팅은 출력에(`scenario_hint` =
   Parameter→A3 / Recipe→A5 / Maintenance→consumable?A6:A2 / 근거없음→null).
   소급 노드는 6번의 키워드 휴리스틱(pad/brush/slurry/filter/conditioner) 임시 판정 —
   다음 재추출 시 노드 속성으로 대체. 실측 분포: A2 209 / A3 97 / A5 32 / A6 44 / null 260.
13. **(07-13) X1E 해소 — fab 어휘 정렬 (Q1 결정 반영)**: `pad_usage_hours`는 fab에 실재(git pull 갭)
   → 시드 21종·`fab.md` CMP 3종·5번 Literal 동기 추가, `cmp_pad_wear` 매핑 가설 `[자동]` 승격 실측
   (자동 99건). `shower_flow`/`pressure`는 `chamber_pressure` 별칭 처리. **잔여**: `motor_torque`·
   `slurry_particle` 제거 결정 — [근거없음]+C2 방침 적용, 정합성검토 §4 X1E 기록.
14. **(07-13) N4/Q7 해소 — Center-세정 취소선 해제 결정**: 취소선 사유가 "형상 서술 RAG 문서
   부재"였음이 확인됨. KG측 무이상(그래프 경로 0건이 정상) 판정 후 MCP 문서 취소선 4곳 해제 —
   문서↔yaml 재정렬. 역할 합의: 해당 행은 **문헌 무근거 큐레이션 항목**(5.1 함정 후보)으로,
   후보 공급은 `candidates[]` 뷰(Q3)가 담당. Edge-bead removal 취소선은 유지(스코프 밖 별건).
15. **(07-22) v3.0 — 형상 진입점 + 모폴로지(설계 B)**: 관측의 `SpatialSignature`(`shape@zone`)를
   `DefectPattern`과 함께 **두 번째 하드 진입점**으로 확립(미지 패턴=`Unknown` 대응). 관측 모폴로지
   (`density`/`continuity`/`angular_coverage`/`clock_positions`)를 **노드가 아니라 `FORMS_IN` 엣지
   속성**으로 추가 — 노드 정체성 `shape@zone` 유지로 clobber·조합폭증 회피. `5_build`에 enum 3종
   (`Density`/`Continuity`/`AngularCoverage`) + `Relationship` 4필드 + 프롬프트 + `FORMS_IN` MERGE SET,
   `6_ask` `SIGNATURE_QUERY` 반환 + `path.morphology` 출력. **`data/docs`(doc_A~H) 로더 편입**
   (`2_load_txt` raw+docs), doc_H가 형상·모폴로지 `FORMS_IN` 공급. backend에 **angular 판별자
   재랭킹**(`morphology_rank.py`, 감점 전용: angular 상충 −10 / clock 불일치 −3 / density·continuity
   상충 −1, 일치·무관측 0) + `get_candidates(pattern, observation)` + `graphrag.py` 배선 + 단위 테스트.
   ⚠ **재빌드 미실행**(그래프 반영 대기) · **관측층(`group["observation"]`) 미배선**(현재 no-op 통과).
   상세: `데이터 모델 설계_v3.0.md`.

---

## 4. 남은 문제

### [P1] 검증 신호가 `Maintenance`로 쏠림 (143건 중 Maintenance 110 : Recipe 17 : Parameter 16)
- `[원인] A. Change in RF power`가 `Parameter rf_power`로 가야 하는데, LLM이 조치 열의
  `Check RF generator`를 보고 `Maintenance`로 붙이는 추출 편향.
- `[자동]` 가설이 그만큼 희소해짐 (Edge-Ring 53건 중 자동 3건뿐).
- **해결안**: 프롬프트에 우선순위 명시 — "원인이 계측 변수의 이상이면 반드시 Parameter 우선,
  Maintenance는 원인이 정비 그 자체일 때만".

### [P2] 가설 점수 체계 — 1차 재설계 완료 (07-13), 잔여 과제 아래
**(07-13 반영)** 순위에서 **tier와 confidence를 제거**하고 측정값만 남김:
`(occurrence_prior, evidence_docs, evidence_chunks)` 내림차순 + cause 이름순 결정적 tiebreak.
- 근거 빈도는 **경로 전체**(진입 엣지 + CAUSED_BY + VERIFIED_BY)의 chunk_ids 합집합에서 계산.
  실측 분포 (1,1)~(4,8)로 실질 변별 — Center 1위가 3문서·10청크 근거의 `incorrect_process_recipe`.
- 철학: 검증 등급(tier)은 "어떻게 확인하느냐"의 분류이지 그럴듯함이 아니다. tier는 필드로만 유지.
- 출력도 함께 축소: `route`(path의 null 패턴으로 유도), `detail` 블록, `path.pattern`,
  `questions[].question`, `counts.by_route`, `score.confidence` 삭제. `KG_output_명세.md` 갱신됨.

**잔여 과제 (아직 유효한 것):**
- **제1성분 `occurrence_prior`도 LLM 산출이다** (문헌의 commonly/rare 서술 해석).
  실측상 대부분 `high`라 변별은 사실상 evidence_docs/chunks가 담당. 장기적으로 개선 대상.
- **저장 버그**: 같은 관계가 여러 청크에서 나오면 `SET`이 `extraction_confidence`를 마지막 값으로
  덮어씀 (chunk_ids는 누적되는데 confidence는 아님). 순위에서는 빠졌지만 그래프 데이터 품질 문제로 잔존.
- 장기적으로는 **fab 검증 결과가 사후 점수(posterior)** — 채택/기각 이력이 쌓이면 그것이 진짜
  순위이고, 문헌 기반 점수는 prior 역할로 물러난다 (②의 Hypothesis 노드와 연결).

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
- ~~`CLEAN`: 트러블슈팅 문헌 없음~~ → **(07-13) 해소.** `...TABLE+CLEAN.md`(6장 산문 재구성 표 6행)로
  CLEAN FailureMode 7종·CLEAN 경유 가설 72건(Scratch 36 + Edge-Ring 36) 확보.
  `insufficient_rinsing→rinse_time`으로 CLEAN 최초의 `[자동]` 경로도 생김.
- `EDS`: 트러블슈팅 문헌 여전히 없음 (빈 공정).
- ref56 Table 1의 5개 패턴(`Donut`, `Edge-Loc`, `Loc`, `Near-Full`, `Random`)은 고정 3종 밖이라 버려짐.
  VLM 클래스를 9종으로 늘리면 그대로 살아남는 구조.
- 표에 있으나 fab에 없는 변수(`gas flow @ ETCH`, `film stress` 등)는 관계로는 옳게 버려지되,
  **(07-13) 신호명은 이제 보존됨** — `Cause.unverifiable_signals` → 출력 `verification.unverifiable_signals`.
  agent는 C2(부족한 데이터)로 기록 (정합성검토 X1 운영 방침).

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

### ③ 가설 점수 체계 재설계 (P2) ← **1차 완료 (07-13)**
- **완료**: 순위에서 tier·confidence 제거, `(occurrence_prior, evidence_docs, evidence_chunks)`
  측정값 순위 + 결정적 tiebreak. 출력 구조 축소 (`KG_output_명세.md` 참조).
- **남음**: 저장 시 confidence `max()` 유지(그래프 품질), occurrence_prior의 LLM 의존 개선,
  장기적으로 fab 검증 이력 기반 posterior (②의 `Hypothesis` 노드에 기록 → 문헌 점수는 prior).

### ④ 그 외 후보 (우선순위 낮음, P1·P3~P6 대응)
1. Maintenance 편향 프롬프트 수정 (P1) — `[자동]` 가설을 늘리는 가장 싼 수
2. Maintenance dedup (P3)
3. CLEAN/EDS 트러블슈팅 문서 추가 (P5)
4. DefectPattern 9종 확장 — VLM 클래스와 정렬 (P5)
5. VLM 관측 입력(JSON) 처리 — **[v3.0 부분 착수]** 모폴로지 스키마(`FORMS_IN` 속성) + angular
   판별자 재랭킹은 배선됨. **남은 것**: ① `0_reset→3→4→5→6` 재빌드로 실제 적재, ② 관측층
   (VLM/die-matrix → `group["observation"]`) 배선, ③ `6_ask`가 pattern이 아니라 관측 `shape@zone`
   에서 진입하는 런타임 경로(미지 패턴 조회). 현재는 여전히 고정 3패턴 순회.
