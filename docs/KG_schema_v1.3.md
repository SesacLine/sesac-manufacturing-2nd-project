# Wafer Defect RCA — Knowledge Graph Schema (v2.5)

반도체 웨이퍼 결함 근본원인 분석(RCA)용 지식 그래프 스키마 명세.
문헌 기반 **원인 가설 생성용** 그래프. 가설 검증은 별도 fab 데이터(SQL)가 담당하며,
KG는 **evidence 노드**로 그 SQL과 연결된다.

> ⚠ **이 문서는 기록용이다 — 정본은 `KG_schema_v1.4.md`로 대체됐다.** `KG_schema_v1.2.md`·`kg_rca/backup/schema.md`는 더 옛 기록.
> 구현: `5_build_kg_from_chunks.py`(추출·검증), `4_ingest_chunks_to_neo4j.py`(시딩), `6_ask_graphrag.py`(순회),
> `backend/graph_client/`(런타임 라이브 조회 — live_kg_client / morphology_rank / semantic_entry).
> 관측 입력 계약: `kg_rca/VLM_output - KG 연결.md`, 데이터 모델: `kg_rca/데이터 모델 설계_v3.0.md`.

## 변경 이력

**v2.4 → v2.5 (2026-07-22, 형상 진입 실전화 + 모폴로지 레이어)**

- **엣지 속성 +4 (설계 B):** `FORMS_IN`에 **`density` / `continuity` / `angular_coverage` /
  `clock_positions`** 추가. 문헌의 형상 서술에서 LLM이 함께 추출한다.
  **노드는 그대로다** — `SpatialSignature` id는 여전히 `{shape}@{zone}`이고 모폴로지는 노드에
  넣지 않는다(같은 형상노드에 문서마다 다른 모폴로지가 MERGE되며 덮어쓰는 clobber,
  복합키化 시 조합 폭증을 피하기 위함).
- **형상 직접 진입:** 패턴을 거치지 않고 `SpatialSignature`에서 바로 순회하는
  `SIGNATURE_ENTRY_QUERY` / `fetch_hypotheses_by_signature` 신설 — 미지 패턴(CNN=`Unknown`)
  대응이 실제 코드로 열림. 패턴 진입의 dedup(공정 경로 우선)에 형상 경로가 먹히지 않아
  **모든 FORMS_IN 엣지의 모폴로지가 후보에 보존**된다.
- **의미(semantic) 진입 (런타임, backend):** VLM 자연어(`location_text`+`morphology_text`)를
  임베딩해 시그니처 서술과 코사인 매칭으로 진입 노드를 고른다(`semantic_entry.py`).
  기지 패턴이면 그 패턴의 `HAS_SIGNATURE` 시그니처로 **범위를 좁힌 뒤** 매칭한다((A) 방식).
  순회 본체는 여전히 고정 Cypher(Text2Cypher 아님 — 환각·비결정 없음).
- **런타임 재랭킹 (판별자):** 관측 모폴로지와 후보 `FORMS_IN` 모폴로지를 비교해 **감점 전용**으로
  재정렬(`morphology_rank.py`). `angular_coverage` full↔partial 상충 −10(판별자),
  clock 완전 불일치 −3, density/continuity 상충 각 −1. 일치·무관측은 0(중립).
- **문서 소스 확장:** 전문가 암묵지 목업 `data/docs/doc_A~H` 파이프라인 편입
  (`2_load_txt.py`가 raw+docs 두 폴더 로드). `doc_H`가 형상·모폴로지 수준 `FORMS_IN`을 공급.
  `data/raw` 파일명을 접두어 규칙(`cause_`/`table_`/`paper_`)으로 정리.
- **정정(v2.4 문서의 낡은 서술):** Parameter는 **21종**(`pad_usage_hours` 포함).
  순위는 07-13 개편대로 **측정값 순위**(`occurrence_prior`, `evidence_docs`, `evidence_chunks`) —
  tier·confidence는 순위에서 빠졌다. dedup 키에서 `route` 제외(같은 꼬리면 강한 경로를 대표로).

이전 이력(v2 → v2.4)은 `KG_schema_v1.2.md` 참조.

---

## 진입점(질의 입력) — v2.5 기준

KG 조회의 관측 입력은 **그룹(스택맵) 단위 1건**이다(웨이퍼별 집계 없음 — CNN이 웨이퍼를 개별
분류하고, 같은 라벨 웨이퍼의 die_map을 오버레이한 **스택맵**에 VLM·die-matrix가 1회 적용된다.
상세: `데이터 모델 설계_v3.0.md` §3.0).

| # | 진입 | 키/방식 | 언제 |
| --- | --- | --- | --- |
| ① | `DefectPattern` | CNN 라벨 정확일치 (`Center`/`Scratch`/`Edge-Ring`) | 기지 패턴. 공정·직결 경로의 진입 |
| ② | `SpatialSignature` | (a) enum 정확일치 `{shape}@{zone}` 또는 (b) **의미 매칭**: 자연어 임베딩 → 시그니처 서술 코사인 top-k | 형상 경로 진입. `Unknown`이면 유일한 진입 |

- (A) 방식: 기지 패턴이면 ①이 `HAS_SIGNATURE`로 ②의 **검색 범위를 좁히고**, 자연어가 그 안에서
  진입 시그니처를 고른다. 패턴 레벨 원인(ARISES_IN/ATTRIBUTED_TO)은 별도로 항상 나온다.
- 관측 모폴로지(`angular_coverage` 등)는 **진입 매칭이 아니라** 조회 후 재랭킹(판별자)에 쓰인다.

---

## 문서 소스와 결합 구조

`ProcessStep`이 A와 B를 잇는 join 노드다. **실문헌(`data/raw/`)과 전문가 암묵지 목업(`data/docs/`)
두 폴더를 모두 로드한다.**

|  | 문서 | 담는 것 | 실제 파일 |
| --- | --- | --- | --- |
| **A** | 웨이퍼맵 패턴 | `DefectPattern → ProcessStep` (+`HAS_SIGNATURE`) | `raw/cause_center.txt`, `raw/cause_edgering.txt`, `raw/cause_scratch.txt`, `docs/doc_A_wafermap_patterns.txt` |
| **B** | 공정 troubleshooting | `FailureMode → Cause → Evidence` | `raw/table_sze_troubleshooting.md`, `docs/doc_B~G_*_troubleshooting.txt` |
| **C** | 패턴→원인 직결 | `DefectPattern → Cause` | `raw/table_ref56_patterns.md` |
| **D** | 형상 수준 서술 | `SpatialSignature → ProcessStep` (+모폴로지) | `raw/paper_liao_rag.txt` (Liao 2026), `raw/paper_edgering_cmp.txt` (Xie & Boning 2005), **`docs/doc_H_spatial_morphology_heuristics.txt`** |

**추출 전제:** 모든 엔티티·관계는 문서에서 추출한다.
단, `DefectPattern` / `ProcessStep` / `Parameter`는 고정 vocabulary로, 사전 정의된 id로 **매핑만** 한다.

---

## Node Types

**v2.5에서 노드 구성 변화 없음** — 모폴로지는 노드가 아니라 `FORMS_IN` 엣지 속성이다(설계 B).

| Label | id (예시) | Properties | 추출 방식 | 설명 |
| --- | --- | --- | --- | --- |
| `DefectPattern` | `Edge-Ring` | `name`, `aliases`, `spatial_keywords`, `expected_zone`, `expected_shape` | **고정 목록** | 웨이퍼맵 패턴 (진입점 ①) |
| `SpatialSignature` | `ring@edge` | `name`, `shape`, `zone` — **모폴로지 속성 없음** | **문서 추출** (id는 enum 조합) | (형상,구역) 쌍 (진입점 ②) |
| `ProcessStep` | `ETCH` | `name`, `aliases` | **고정 목록** | 공정군 (A·B의 join 노드) |
| `FailureMode` | `incorrect_etch_rate` | `name`, `description`, `aliases` | 문서 추출 | 공정 고장 모드 |
| `Cause` | `rf_power_drift` | `name`, `description`, `aliases`, `unverifiable_signals` | 문서 추출 | 근본 원인 |
| `Parameter` | `rf_power` | `name`, `steps`, `aliases`, `fab_table` | **고정 목록** | **[evidence]** telemetry 변수 |
| `Maintenance` | `chamber_wet_clean` | `name`, `description`, `consumable`, `fab_table` | 문서 추출 | **[evidence]** 정비 이력 |
| `Recipe` | `process_recipe` | `name`, `description`, `fab_table` | 문서 추출 | **[evidence]** 레시피 |

- 모든 노드는 `id` 유일 키(라벨별 UNIQUE 제약). `FailureMode`/`Cause`/`Maintenance`/`Recipe` id는 snake_case 정규화.
- 세 evidence 라벨은 공통 슈퍼라벨 **`:Evidence`** 를 함께 갖는다. `fab_table`이 조회 대상 테이블 명시.
- `Maintenance.consumable`(bool): 소모품(패드/브러시/슬러리/필터/컨디셔너) 계열 여부 — 추출 시 LLM 판단.
  scenario_hint(A6/A2) 분기에 쓰인다.
- `Cause.unverifiable_signals`: 문헌이 지목했지만 fab 어휘에 없어 VERIFIED_BY로 잇지 못한 신호명 보존(C2).

### 근거 보존용 인프라 노드 *(변화 없음)*

| Label | Properties | 관계 |
| --- | --- | --- |
| `Document` | `id`, `title`, `source` | `(:Document)-[:HAS_CHUNK]->(:Chunk)` |
| `Chunk` | `id`, `text`, `chunk_index`, `doc_id`, `source`, `char_count` | `(:Chunk)-[:NEXT_CHUNK]->(:Chunk)`, `(:Chunk)-[:MENTIONS]->(백본 노드)` |

### 고정 vocabulary

- **DefectPattern:** `Center`, `Scratch`, `Edge-Ring`
- **ProcessStep:** `LITHO`, `ETCH`, `DEPO`, `CMP`, `CLEAN`, `EDS`
- **Parameter:** **21종** (`seeds/parameters.json` — 07-13 `pad_usage_hours` 추가)
- **SpatialSignature 어휘 (코드 enum, 시딩 안 함):** `shape ∈ {ring, cluster, line, blob, global, random}` ×
  `zone ∈ {center, mid, edge, any}`, id = `{shape}@{zone}`
- **FORMS_IN 모폴로지 어휘 (코드 enum, v2.5 신설):**
  `density ∈ {high, medium, low, unknown}` /
  `continuity ∈ {continuous, intermittent, discontinuous, not_applicable, unknown}` /
  `angular_coverage ∈ {full, partial, unknown}` / `clock_positions ⊆ [1..12]` (partial일 때만)

시딩은 세 앵커(`DefectPattern`/`ProcessStep`/`Parameter`)뿐. 시드와 코드 Literal이 어긋나면
`assert_enums_match_seeds()`가 실행 즉시 예외를 던진다.
**VLM은 형상을 자유 서술로 출력한다** — enum 분류를 VLM에 강제하지 않고, 런타임 의미 진입
(임베딩 매칭)이 서술을 시그니처로 잇는다. enum 정규화 값(`signature`)을 직접 주는 경로도 병존.

### `Parameter` 해석은 `ProcessStep` 조건부다 *(v2.4와 동일 — 상세는 v1.2 참조)*

`temperature`가 공정마다 다른 변수를 가리킨다(LITHO `stage_temp` / ETCH `temperature` / …).
Cause의 공정은 `OCCURS_IN`을 타고 물려받고, 그 공정에서 계측되지 않는 변수는 버린다.
`ATTRIBUTED_TO`로만 연결된 Cause는 공정을 몰라 `Parameter`에 닿지 못한다.

---

## Relationship Types

| 소스 | Edge | Source | → | Target | 의미 |
| --- | --- | --- | --- | --- | --- |
| A | `ARISES_IN` | `DefectPattern` | → | `ProcessStep` | 이 패턴이 어느 공정을 의심케 하는가 |
| B | `OCCURS_IN` | `FailureMode` | → | `ProcessStep` | 이 고장이 어느 공정에서 일어나는가 |
| B | `CAUSED_BY` | `FailureMode` | → | `Cause` | 무엇이 원인인가 |
| B | `VERIFIED_BY` | `Cause` | → | `Parameter` \| `Maintenance` \| `Recipe` | 어떤 fab 신호로 검증하는가 |
| C | `ATTRIBUTED_TO` | `DefectPattern` | → | `Cause` | 문헌이 공정을 거치지 않고 지목한 원인 |
| D | `HAS_SIGNATURE` | `DefectPattern` | → | `SpatialSignature` | 이 패턴은 이런 형상으로 나타난다 |
| D | `FORMS_IN` | `SpatialSignature` | → | `ProcessStep` | 이 형상은 주로 어느 공정에서 생기는가 |

### 관계 속성 — **[v2.5 갱신]**

- **공통:** `extraction_confidence`(1~5, LLM 자기평가), `description`, `quotes`,
  `chunk_ids`(근거 청크, 중복 없이 누적)
- `ARISES_IN` / `FORMS_IN`: `occurrence_prior` (`high`/`mid`/`low` — 문헌의 commonly/rare 해석)
- **`FORMS_IN` 전용 (v2.5 신설):** `density`, `continuity`, `angular_coverage`, `clock_positions`
  — 문헌이 형상의 모폴로지를 서술할 때만 채워짐(없으면 null). 런타임 판별자 재랭킹의 비교 대상.
- `VERIFIED_BY` 전용: `target_label`, `direction` (`high`/`low`, Parameter일 때만)

> ⚠ **FORMS_IN 모폴로지의 clobber 주의**: `FORMS_IN`은 `(signature, step)` 쌍으로 MERGE되므로,
> 같은 `ring@edge→ETCH`를 서로 다른 모폴로지로 서술한 문서가 여럿이면 **마지막 SET이 덮어쓴다**
> (`chunk_ids`만 리스트 누적). 현 목업은 일관 작성으로 회피 — 실문헌 확장 시 누적 방식 재검토.

---

## 추출 검증 규칙 (graph pruning) *(v2.4와 동일 — 6종, 상세는 v1.2 참조)*

신뢰도(<2 폐기) / 앵커 정규화(aliases 역인덱스) / grounding 가드(공정명이 청크 원문에 있어야) /
국소성(같은 청크 노드만) / 공정-변수 정합성 / 고아 제거. 시그니처는 형상 표현이 원문에 있어야
인정(`SHAPE_SURFACES` 가드). 버릴 땐 반드시 사유 로그(조용한 유실 금지).

진입점 엣지(ARISES_IN/FORMS_IN/ATTRIBUTED_TO)는 비결정성 완화를 위해 패턴/형상 언급 청크만
`ANCHOR_PASSES`(기본 3)회 재추출·합집합.

---

## 검증 등급 (verification tier) *(v2.4와 동일)*

축은 "fab.db에 있느냐"가 아니라 **agent가 스스로 채택/기각을 판정할 수 있느냐**.

| 등급 | Evidence | 조인 키 | 판정 규칙 | 누가 |
| --- | --- | --- | --- | --- |
| `[자동]` | `Parameter` | `telemetry.param` ✔ | 정상범위 대비 이탈 ✔ | agent가 결론까지 |
| `[반자동]` | `Maintenance` / `Recipe` | 필터 힌트/실값 조회만 | 판정 규칙 없음 | agent 조회, 사람 판정 |
| `[근거없음]` | 없음 | — | — | 문헌 서술로만 |

`scenario_hint`(MCP 체인 라우팅): Parameter→A3, Recipe→A5, Maintenance→`consumable`?A6:A2, 근거없음→null.

---

## Backbone 요약

```
                        ┌──ATTRIBUTED_TO────────────────────────────┐   (문서 C: 공정 우회)
                        │                                           ▼
DefectPattern ──ARISES_IN──────────────┐                          Cause
 (Edge-Ring)                            ▼                           ▲
     │                             ProcessStep ◄──OCCURS_IN── FailureMode
     │ HAS_SIGNATURE (문서 추출)        (ETCH)      (join)       (incorrect_etch_rate)
     ▼                                  ▲                           │ CAUSED_BY
SpatialSignature ──FORMS_IN─────────────┘                           ▼
 (ring@edge)   {density, continuity,                              Cause
     ▲          angular_coverage, clock_positions}                  │ VERIFIED_BY
     │ (v2.5: 미지 패턴은 여기로 직접 진입 —          ┌──────────────┼──────────────┐
     │  enum 정확일치 or 자연어 의미 매칭)            ▼              ▼              ▼
                                                Parameter      Maintenance      Recipe
                                             → telemetry.param → maintenance → lot_history.recipe_id
                                                 [자동]           [반자동]       [반자동]
```

---

## 가설 생성·검증 순회 — **[v2.5 갱신]**

순회는 결정적 고정 Cypher다. LLM은 (빌드타임) 관계 추출과 문장 합성에만 쓴다.
**퍼지(유사도)는 오직 런타임 "진입 시그니처 선정" 단계에만 존재한다.**

**경로 1 — 공정 경유** `DefectPattern -ARISES_IN-> ProcessStep <-OCCURS_IN- FailureMode -CAUSED_BY-> Cause -VERIFIED_BY-> Evidence`

**경로 2 — 형상 경유 (패턴 진입)** `DefectPattern -HAS_SIGNATURE-> SpatialSignature -FORMS_IN-> ProcessStep -...`
같은 꼬리를 경로 1도 찾으면 한 가설로 합치고 경로 1을 대표로 남긴다.

**경로 2b — 형상 직접 진입 (v2.5 신설, `SIGNATURE_ENTRY_QUERY`)**
`SpatialSignature -FORMS_IN-> ProcessStep -...` — **패턴 없이** 시작. 미지 패턴(`Unknown`)의 진입이며,
경로 1과의 dedup이 없어 FORMS_IN 모폴로지가 모든 후보에 보존된다(판별자의 전제).
진입 시그니처는 (a) enum 정확일치 또는 (b) 의미 매칭(자연어 임베딩 ↔ 시그니처 서술
[FORMS_IN description+quotes+MENTIONS 청크] 코사인 top-k)으로 고른다.
기지 패턴이면 `HAS_SIGNATURE`가 매칭 범위를 좁힌다((A) 방식) — 이때 패턴 레벨 원인
(경로 1·3)은 별도 유지하고, 같은 꼬리는 **모폴로지 있는 후보를 대표로** dedup한다.

**경로 3 — 문헌 직결** `DefectPattern -ATTRIBUTED_TO-> Cause` (evidence 없으면 `[근거없음]`)

**중복 제거** — `(step, failure_mode, cause, evidence)` 같을 때만 합침(**route는 키에서 제외** —
같은 꼬리면 더 강한 경로가 대표: step > signature > direct).

**순위 (빌드타임, 07-13 개편)** — `(occurrence_prior, evidence_docs, evidence_chunks)` 내림차순
+ cause 이름순 결정적 tiebreak. **tier·confidence는 순위에서 제외**(tier는 검증 방법 분류이지
그럴듯함이 아니고, confidence는 LLM 자기평가라 신뢰 불가). 근거 빈도는 경로 전체 chunk_ids
합집합에서 계산한 측정값.

**재랭킹 (런타임, v2.5 신설)** — 관측 모폴로지 vs 후보 `FORMS_IN` 모폴로지, **감점 전용**:

| 비교 | 감점 | 성격 |
| --- | --- | --- |
| `angular_coverage` full↔partial 상충 | **−10** | 판별자(강) — 인과가 갈림 |
| 둘 다 partial + `clock_positions` 완전 불일치 | −3 | 소프트 |
| `density` 상충 / `continuity` 상충 | 각 −1 | 소프트(VLM 노이즈 감안) |
| 일치 / unknown / not_applicable / 무관측 | 0 | 중립 — 원래 순위 보존(안정 정렬) |

**출력** — 탐색된 모든 가설(기본 상한 없음, `TOP_K`로 제한 가능). 배치 출력은
`outputs/hypotheses.json`(형상 경유 가설에 `path.morphology` 포함), 런타임은 backend
`LiveKGClient.get_candidates(pattern, observation)`가 동일 순회를 라이브로 수행.

---

## 예시 인스턴스 (v2.5 재빌드 실측)

재빌드(2026-07-22, 문헌 15편·154청크): 가설 772건(Center 375 / Scratch 107 / Edge-Ring 290),
`SpatialSignature` 8종, `FORMS_IN` 10엣지 전부 모폴로지 적재.

**같은 `ring@edge`가 모폴로지로 갈라지는 실측 예 (판별자의 근거):**

- `ring@edge` `-FORMS_IN->` **ETCH** `{angular: full, density: high, continuity: continuous}`
  — "가장자리 전체를 두른 조밀한 연속 링" → 식각 불균일
- `ring@edge` `-FORMS_IN->` **CMP** `{angular: partial, clock: [5,6,7], density: low, continuity: discontinuous}`
  — "하부 5~7시에만 걸린 성긴 끊긴 호" → 비대칭 엣지 연마

관측이 partial arc면 ETCH 후보(-10 이하)가 가라앉고 CMP 후보가 떠오른다 — 라이브 검증 완료.
