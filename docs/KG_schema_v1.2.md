# Wafer Defect RCA — Knowledge Graph Schema (v2.4)

반도체 웨이퍼 결함 근본원인 분석(RCA)용 지식 그래프 스키마 명세.
GraphRAG(문서/도메인 지식) 기반의 **원인 가설 생성용** 그래프.
가설 검증은 별도 fab 데이터(SQL)가 담당하며, KG는 **evidence 노드**로 그 SQL과 연결된다.

> 이 문서가 정본이다. `schema.md`는 v1 기록용.
구현: `5_build_kg_from_chunks.py`(추출·검증), `4_ingest_chunks_to_neo4j.py`(시딩), `6_ask_graphrag.py`(순회).
> 

## 변경 이력

**v2 → v2.1**

- **노드 -1:** `Equipment` 제거. **엣지 -1:** `PART_OF` 제거.
장비 인스턴스(예: `ETCH-03`)는 **문서에 없는 fab 데이터 값**이라 문서 추출로 성립하지 않는다.
장비↔공정 매핑은 `lot_history`(equipment_id, step)에 이미 있어 검증 단계에서 자연 조인된다.
- **엣지 변경:** `INVOLVES_PARAMETER` → `VERIFIED_BY`로 일반화. 대상이 세 evidence 라벨로 갈린다.
- 원칙: KG에는 **문서에서 실제 추출되는 것만** 둔다.

**v2.1 → v2.2**

- **엣지 +1:** `ATTRIBUTED_TO` (`DefectPattern` → `Cause`). 공정을 거치지 않는 직결 서술을 담는다.
- `Parameter` 해석을 **`ProcessStep` 조건부**로 변경.
- `ARISES_IN`/`OCCURS_IN`에 **grounding 가드** 도입 (원문에 공정 이름이 있어야 인정).
- `DefectPattern` 고정 목록을 `Center` / `Scratch` / `Edge-Ring`로 확정 (`Donut` 제외).

**v2.2 → v2.3 (형상 레이어)**

- **노드 +1:** `SpatialSignature` — (형상, 구역) 쌍. 4번째 고정 vocabulary.
형상 단독이 아니라 쌍인 이유: 9종 확장 시 Edge-Ring(ring@edge)과 Donut(ring@mid)이 뭉개지지 않게.
- **엣지 +2:** `HAS_SIGNATURE` (`DefectPattern`→`SpatialSignature`, **시드에서 결정적**, LLM 불개입) /
`FORMS_IN` (`SpatialSignature`→`ProcessStep`, 문서 D 추출 + grounding 가드).
- 근거: ① 문헌이 형상 수준으로 말한다 ("ring-shaped pattern ... reflects issues in cleaning steps") —
강제로 패턴 클래스에 매핑하지 않고 제 층위에 붙인다. ② VLM이 형상 관측을 넘긴다.
③ **미지 패턴**: 3클래스 외 패턴도 VLM이 형상만 넘기면 signature부터 순회해 가설을 얻는다.
- **앵커 보강 패스** 도입: 진입점 엣지(ARISES_IN/FORMS_IN/ATTRIBUTED_TO)의 추출 비결정성 완화를 위해
패턴/형상을 언급하는 청크만 `ANCHOR_PASSES`(기본 3)회 재추출해 합집합 (MERGE라 중복 없음).

**v2.3 → v2.4 (형상 레이어를 추출 방식으로 전환)**

- **결정적 시딩은 세 앵커로 축소: `DefectPattern` / `ProcessStep` / `Parameter`.**`SpatialSignature`는 더 이상 시딩하지 않는다 — `seeds/signatures.json` 삭제,
`HAS_SIGNATURE`도 문서의 형상 서술에서 **LLM이 추출**한다.
- 단, **어휘는 코드 enum으로 닫는다**: `shape ∈ {ring, cluster, line, blob, global, random}`,
`zone ∈ {center, mid, edge, any}`. 노드 id는 코드가 `{shape}@{zone}`으로 조합한다.
→ 표현이 달라도 id가 파편화될 수 없고(허브 join 보전), VLM의 **자유 서술** 형상 관측도
같은 enum으로 분류해 진입하면 된다 (문서 추출과 VLM 입력이 동일한 분류 계약을 공유).
- 가드: 시그니처는 형상 표현이 원문에 있어야 인정(환각 차단),
`HAS_SIGNATURE`/`FORMS_IN`은 같은 청크에서 추출된 시그니처만 가리킬 수 있다(국소성).

---

## 문서 소스와 결합 구조

**세 종류**의 문서를 수집한다. `ProcessStep`이 A와 B를 잇는 join 노드다.

|  | 문서 | 담는 것 | 실제 파일 |
| --- | --- | --- | --- |
| **A** | 웨이퍼맵 패턴 | `DefectPattern → ProcessStep` | `raw/center_pattern_cause.txt`, `raw/pattern_cause`, `raw/scratch_pattern_cause` |
| **B** | 공정 troubleshooting | `FailureMode → Cause → Evidence` | `raw/..._troubleshootingTABLE.md` |
| **C** | 패턴→원인 직결 | `DefectPattern → Cause` | `raw/ref56_table1_pattern_causes.md` |
| **D** | 형상 수준 서술 | `SpatialSignature → ProcessStep` | `raw/Wafer defect semantic reasoning....txt` (Liao et al. 2026) |

A와 B가 같은 `ProcessStep`을 언급하면 그래프에서 자동 결합된다.
C는 공정을 우회한다. 문헌이 패턴의 원인을 말하되 **어느 공정인지는 말하지 않을 때** 쓴다.

**추출 전제:** 모든 엔티티·관계는 문서에서 추출한다.
단, `DefectPattern` / `ProcessStep` / `Parameter`는 고정 vocabulary로, 사전 정의된 id로 **매핑만** 한다.

---

## Node Types

| Label | id (예시) | Properties | 추출 방식 | 설명 |
| --- | --- | --- | --- | --- |
| `DefectPattern` | `Edge-Ring` | `name`, `aliases`, `spatial_keywords`, `expected_zone`, `expected_shape` | **고정 목록** | 웨이퍼맵 패턴 (질의 진입점) |
| `SpatialSignature` | `ring@edge` | `name`, `shape`, `zone` | **문서 추출** (id는 enum 조합) | (형상,구역) 쌍. 형상 관측의 진입점 |
| `ProcessStep` | `ETCH` | `name`, `aliases` | **고정 목록** | 공정군 (문서 A·B의 join 노드) |
| `FailureMode` | `incorrect_etch_rate` | `name`, `description`, `aliases` | 문서 추출 | 공정 고장 모드 |
| `Cause` | `rf_power_drift` | `name`, `description`, `aliases` | 문서 추출 | 근본 원인 |
| `Parameter` | `rf_power` | `name`, `steps`, `aliases`, `fab_table` | **고정 목록** | **[evidence]** telemetry 변수 |
| `Maintenance` | `chamber_wet_clean` | `name`, `description`, `fab_table` | 문서 추출 | **[evidence]** 정비 이력 |
| `Recipe` | `process_recipe` | `name`, `description`, `fab_table` | 문서 추출 | **[evidence]** 레시피 |
- 모든 노드는 `id`를 유일 키로 가진다 (라벨별 UNIQUE 제약).
- `FailureMode` / `Cause` / `Maintenance` / `Recipe`의 `id`는 소문자 snake_case로 정규화한다.
- 세 evidence 라벨(`Parameter`/`Maintenance`/`Recipe`)은 공통 슈퍼라벨 **`:Evidence`를 함께 갖는다**(선택 아님).
없으면 순회 쿼리가 라벨별로 갈라진다. `fab_table` 프로퍼티가 조회 대상 테이블을 명시한다.

### 근거 보존용 인프라 노드

문헌 추적을 위해 별도로 적재한다. 스키마 백본은 아니다.

| Label | Properties | 관계 |
| --- | --- | --- |
| `Document` | `id`, `title`, `source` | `(:Document)-[:HAS_CHUNK]->(:Chunk)` |
| `Chunk` | `id`, `text`, `chunk_index`, `doc_id`, `source`, `char_count` | `(:Chunk)-[:NEXT_CHUNK]->(:Chunk)` |

`(:Chunk)-[:MENTIONS]->(:FailureMode | :Cause | :Maintenance | :Recipe)` 로 어느 청크가 그 노드를 언급했는지 남긴다.

### 고정 vocabulary

- **DefectPattern:** `Center`, `Scratch`, `Edge-Ring`
- **ProcessStep:** `LITHO`, `ETCH`, `DEPO`, `CMP`, `CLEAN`, `EDS`
- **Parameter:** `fab.md`의 장비군별 파라미터 20종 (`seeds/parameters.json`)

시딩은 위 세 앵커뿐이다. `SpatialSignature`는 문서에서 추출되며, 어휘만 코드 enum으로 닫힌다:
`shape ∈ {ring, cluster, line, blob, global, random}` × `zone ∈ {center, mid, edge, any}`.
VLM은 형상을 **자유 서술 텍스트**로 출력하므로, VLM 입력 모듈(미구현)이 그 텍스트를
같은 shape/zone enum으로 분류해 `{shape}@{zone}` id로 그래프에 진입한다.

세 라벨은 적재 전 사전 시딩되며(`4_ingest_chunks_to_neo4j.py`), ingest는 새로 생성하지 않고 연결만 한다.

id는 코드의 `Literal`에도 하드코딩돼 있다(LLM에 넘길 JSON schema를 정적으로 만들어야 해서).
시드와 어긋나면 `assert_enums_match_seeds()`가 **실행 즉시 예외를 던진다**.

> `CLEAN`/`EDS`는 현재 트러블슈팅 문헌 근거가 없어 빈 공정으로 남아 있다(문서 추가 예정).
문서 C(ref56 Table 1)는 WM-811K 8클래스를 담고 있으나, 고정 목록 3종 밖의 5개
(`Donut`, `Edge-Loc`, `Loc`, `Near-Full`, `Random`)는 사유를 남기고 버려진다.
> 

### `Parameter` 해석은 `ProcessStep` 조건부다

같은 표현이 공정마다 다른 변수를 가리킨다. 전역 사전 하나로는 항상 한쪽으로만 붙어 조용히 틀린다.

| 표현 | LITHO | ETCH | DEPO | CMP | CLEAN | EDS |
| --- | --- | --- | --- | --- | --- | --- |
| `temperature` | `stage_temp` | `temperature` | `susceptor_temp` | — | `chemical_temp` | `chuck_temp` |
| `pressure` | — | `chamber_pressure` | `chamber_pressure` | `down_force` | — | — |
- Cause가 속한 공정은 `FailureMode -[OCCURS_IN]-> ProcessStep`을 타고 물려받는다.
- 그 공정에서 계측되지 않는 변수를 가리키면 관계를 버린다 (예: CMP의 `rf_power`).
- **공정을 모르는 Cause는 `Parameter`에 닿지 못한다.** `ATTRIBUTED_TO`로만 연결된 Cause가 여기 해당한다.
- 같은 공정 안에서 한 표현이 두 파라미터를 가리키면 시드 버그이므로 import 시점에 예외를 던진다.

### `Maintenance`는 조치 열에서 뽑는다

문헌의 **원인 열**에는 `Improper maintenance`라는 뭉뚱그린 표현만 있고,
구체적 정비 행위(`chamber wet clean`, `replace defective thermocouple`)는 **조치 열**에 적혀 있다.
따라서 `Cause`는 원인 열에서, `Maintenance.name`은 조치 열에서 뽑는다.
조치 문장 자체(`~를 점검하라`)를 `Cause`로 만들면 안 된다.

---

## Relationship Types

| 소스 | Edge | Source | → | Target | 의미 |
| --- | --- | --- | --- | --- | --- |
| A | `ARISES_IN` | `DefectPattern` | → | `ProcessStep` | 이 패턴이 어느 공정을 의심케 하는가 |
| B | `OCCURS_IN` | `FailureMode` | → | `ProcessStep` | 이 고장이 어느 공정에서 일어나는가 |
| B | `CAUSED_BY` | `FailureMode` | → | `Cause` | 무엇이 원인인가 |
| B | `VERIFIED_BY` | `Cause` | → | `Parameter` | `Maintenance` | `Recipe` | 어떤 fab 신호로 검증하는가 |
| C | `ATTRIBUTED_TO` | `DefectPattern` | → | `Cause` | 문헌이 공정을 거치지 않고 지목한 원인 |
| D | `HAS_SIGNATURE` | `DefectPattern` | → | `SpatialSignature` | 이 패턴은 이런 형상으로 나타난다 (문서 추출) |
| D | `FORMS_IN` | `SpatialSignature` | → | `ProcessStep` | 이 형상은 주로 어느 공정에서 생기는가 |

### 관계 속성

- **공통:** `extraction_confidence`(1~5, LLM 자기평가), `description`, `quotes`, `chunk_ids`(근거 청크, 중복 없이 누적)
- `ARISES_IN` 전용: `occurrence_prior` (`high`/`mid`/`low`)
- `VERIFIED_BY` 전용: `target_label` (`Parameter`/`Maintenance`/`Recipe`), `direction` (`high`/`low`, **Parameter일 때만**)

> `extraction_confidence`는 계산값이 아니라 LLM이 스스로 매긴 점수다. 통계적 근거가 없다.
현재 거의 모든 관계가 `5.0`이라, 순위 정보보다는 "2 미만 폐기" 필터로 기능한다.
> 

### 방향 원칙

- `DefectPattern`과 `FailureMode`는 둘 다 `ProcessStep`으로 수렴 (join 노드).
- `ATTRIBUTED_TO`만 그 수렴을 우회한다. 문헌이 공정을 말하지 않을 때의 도피처다.
- `VERIFIED_BY`는 대상 노드 라벨로 검증 방식이 갈린다 (아래 바인딩 표 참조).
- `FailureMode`와 `Cause`는 분리 유지 (FMEA 구분). 병합하지 않는다.

### 문서 C 처리 규칙

`ATTRIBUTED_TO`로 연결된 `Cause`는 공정을 모르므로 `Parameter`(공정 조건부 해석)에 닿지 못하고
**`[반자동]` 또는 `[근거없음]` 가설**로만 남는다.

단, 원인 문장이 공정을 명시하면 `ARISES_IN`도 함께 만들어 공정 경유 경로가 열린다.
실제 예: ref56 Table 1의 Scratch 행이 `chemical–mechanical polishing (CMP)`를 명시하므로
`ARISES_IN: Scratch → CMP`가 성립한다.

---

## 추출 검증 규칙 (graph pruning)

`5_build_kg_from_chunks.py`의 `validate_kg()`가 저장 전에 적용한다.
버린 것은 **반드시 사유를 로그로 남긴다**(조용한 유실 금지).

1. **신뢰도 필터** — `extraction_confidence < 2`이면 폐기.
2. **앵커 정규화** — `DefectPattern`/`ProcessStep`/`Parameter` 표기를 시드 `aliases` 역인덱스로
canonical id에 갈아끼운다. 대소문자·하이픈·밑줄·공백 차이를 흡수한다
(`edge-ring` → `Edge-Ring`, `etching` → `ETCH`, `RF Power` → `rf_power`).
못 붙이면 버린다.
3. **grounding 가드** — `ARISES_IN`과 `OCCURS_IN`은 **대상 공정의 표기가 그 청크 원문에 실제로 등장할 때만** 인정한다.
공정 이름이 없는 서론·요약 문단에서 LLM이 아무 공정이나 골라 붙이는 것을 막는다.
4. **국소성** — `CAUSED_BY`/`ATTRIBUTED_TO`/`VERIFIED_BY`의 대상은 **같은 청크에서 추출된 노드**여야 한다
(`Parameter`는 고정 목록이므로 예외).
5. **공정-변수 정합성** — `VERIFIED_BY → Parameter`는 Cause의 공정에서 계측되는 변수여야 한다.
6. **고아 제거** — `CAUSED_BY`나 `ATTRIBUTED_TO` 어느 쪽에서도 지목되지 않은 `Cause`는 도달 불가이므로 버린다.
그 Cause에서 출발하던 `VERIFIED_BY`와, 아무도 가리키지 않는 evidence 노드도 함께 버린다.

---

## 검증 등급 (verification tier)

가설마다 "이걸 어떻게 확인할 것인가"가 다르다. 출력에 `[자동]` / `[반자동]` / `[근거없음]`으로 표시한다.

**흔한 오해부터 짚는다.** 가르는 축은 *"fab.db에 데이터가 있느냐"*가 **아니다.**
세 evidence 라벨 모두 fab 테이블에 붙어 있다 (`telemetry`, `maintenance`, `lot_history`).

진짜 축은 **hypothesis agent가 스스로 채택/기각을 판정할 수 있느냐**다.
그러려면 두 가지가 필요하다.

1. **결정적 조인 키** — 그래프의 id로 fab 행을 정확히 집어낼 수 있는가
2. **판정 규칙** — 집어낸 값을 무엇과 비교해 정상/이상을 가를 것인가

| 등급 | Evidence | fab 테이블 | 조인 키 | 판정 규칙 | 누가 |
| --- | --- | --- | --- | --- | --- |
| **`[자동]`** | `Parameter` | `telemetry(equipment_id, ts, param, value)` | `Parameter.id` = `telemetry.param` ✔ | 정상범위(`fab_model.yaml`) 대비 이탈 ✔ | **agent가 결론까지** |
| **`[반자동]`** | `Maintenance` | `maintenance(equipment_id, ts, type, parts)` | ✘ `parts`가 자유 텍스트. id는 **필터 힌트**일 뿐 | ✘ PM 지연·직전 BM 여부는 규칙화 안 됨 | agent가 조회, **사람이 판정** |
| **`[반자동]`** | `Recipe` | `lot_history.recipe_id` | ✔ 실제 레시피는 읽힘 | ✘ **기대값이 KG에 없어** 비교 대상이 없음 | agent가 조회, **사람이 판정** |
| **`[근거없음]`** | 없음 | — | — | — | **사람만**. 문헌 서술로만 존재 |

`[근거없음]`은 evidence 노드 자체가 없는 가설이다. `ATTRIBUTED_TO`로만 붙은 `Cause`가 여기 해당한다.
`surface_damage_by_humans`처럼 fab에 대응물이 없거나, RTP처럼 6스텝 밖이라 계측이 없는 경우다.

순위는 `자동 > 반자동 > 근거없음` 순으로 올린다 (`6_ask_graphrag.py`의 `TIER_OF_LABEL`).

> **현재 분포가 `Maintenance`로 크게 쏠려 있다** (Maintenance 110 : Recipe 17 : Parameter 16).
교과서의 조치 열이 대부분 점검·정비·교정이라 자연스러운 면이 있으나, 추출 편향도 섞여 있다.
예: `[원인] A. Change in RF power`는 `Parameter rf_power`로 가야 하는데,
LLM이 조치 열의 `Check RF generator`를 보고 `Maintenance`로 붙인다.
`[자동]` 가설이 그만큼 줄어든다. 개선 과제.
> 

> 모든 evidence는 런타임에 `lot_history`(lot_id → equipment_id, step, ts, recipe_id)로
컨텍스트를 바인딩한 뒤 조회한다. 장비 인스턴스(equipment_id)는 KG에 없고 여기서 조달된다.
anneal(RTP)은 fab 6스텝 밖이라 **스코프 밖**이다. 관련 원인은 `[근거없음]`으로 남는다.
향후 확장: `alarm` 테이블용 `Alarm` evidence 노드를 추가하면 `[반자동]`이 하나 늘어난다.
> 

---

## Backbone 요약 (텍스트 다이어그램)

```
                        ┌──ATTRIBUTED_TO────────────────────────────┐   (문서 C: 공정 우회)
                        │                                           ▼
DefectPattern ──ARISES_IN──────────────┐                          Cause
 (Edge-Ring)                            ▼                           ▲
     │                             ProcessStep ◄──OCCURS_IN── FailureMode
     │ HAS_SIGNATURE (문서 D 추출)      (ETCH)      (join)       (incorrect_etch_rate)
     ▼                                  ▲                           │ CAUSED_BY
SpatialSignature ──FORMS_IN─────────────┘                           ▼
 (ring@edge)      (문서 D: 형상 수준)                              Cause
                                                                    │ VERIFIED_BY
                                            ┌───────────────────────┼───────────────────────┐
                                            ▼                       ▼                       ▼
                                       Parameter               Maintenance               Recipe
                                    → telemetry.param        → maintenance           → lot_history.recipe_id
                                        [자동]                   [반자동]                 [반자동]
```

- **질의 진입점:** `DefectPattern` (고정 3개)
- **join 노드:** `ProcessStep`
- **검증 종착점:** `Parameter` / `Maintenance` / `Recipe` (`:Evidence`)

---

## 가설 생성·검증 순회

질문은 하나로 고정된다: **"{패턴} 결함 패턴이 나타나는 근본 원인은 무엇인가요?"**
Cypher를 LLM에게 생성시키지 않는다. 순회는 결정적이고, LLM은 뽑아온 사실을 문장으로 옮기기만 한다.

**경로 1 — 공정 경유 (기본)**

1. 관찰된 `DefectPattern`에서 `ARISES_IN`으로 의심 `ProcessStep` 집합을 얻는다.
2. 각 `ProcessStep`에 `OCCURS_IN`으로 걸린 `FailureMode`들을 후보로 모은다.
3. 각 `FailureMode` → `Cause` → `Evidence` 경로 하나하나가 **가설 1건**.

**경로 2 — 형상 경유 (문서 D)**

1. `DefectPattern -[HAS_SIGNATURE]-> SpatialSignature -[FORMS_IN]-> ProcessStep`
2. 이후는 경로 1과 동일. 같은 꼬리(공정·고장·원인·신호)를 경로 1도 찾으면 **한 가설로 합치고
경로 1을 대표로** 남긴다 (패턴을 직접 지목한 문헌이 형상 서술보다 강한 근거).
3. **미지 패턴 대응의 기반**: VLM이 3클래스 외 패턴의 형상만 넘겨도 signature부터 순회 가능.

**경로 3 — 문헌 직결 (문서 C)**

1. `DefectPattern`에서 `ATTRIBUTED_TO`로 `Cause`를 바로 얻는다.
2. 그 `Cause`에 `VERIFIED_BY`가 있으면 붙이고, 없으면 `[근거없음]` 등급으로 둔다.

공정 경유(1·2) 경로도 `VERIFIED_BY`가 없는 `Cause`를 `[근거없음]`으로 낸다
(OPTIONAL MATCH — evidence 없는 원인이 경로에서 통째로 사라지던 비대칭 제거).

**출력 범위** — 탐색된 **모든** 가설을 낸다. 기본 상한 없음.
잘라 보고 싶으면 환경변수 `TOP_K=3`을 준다.

**중복 제거** — `(route, step, failure_mode, cause, evidence)`가 완전히 같을 때만 합친다.
같은 `Cause`·`Evidence`라도 다른 공정·고장 모드를 거쳤다면 **별개의 가설**이다
(예: 같은 `rf_power`가 ETCH와 DEPO 양쪽에서 나올 수 있다).

**순위** — `(검증 등급, occurrence_prior, 평균 extraction_confidence)` 튜플 내림차순.

| 성분 | 값 | 출처 |
| --- | --- | --- |
| 검증 등급 | `자동(2) > 반자동(1) > 근거없음(0)` | evidence 라벨에서 결정적으로 계산 |
| `occurrence_prior` | `high(3) / mid(2) / low(1)`, 없으면 `1` | `ARISES_IN` 관계 속성. **LLM이 매김** |
| `confidence` | 경로 위 세 관계의 `extraction_confidence` 평균 | **LLM 자기평가**. `coalesce(..., 3)` |

튜플 비교라 **검증 등급이 절대 우선**이고, 나머지는 동점을 가르는 데만 쓰인다.

> **점수의 신뢰도 자체가 낮다.** 뒤의 두 성분은 LLM이 스스로 매긴 값이고,
현재 거의 모든 관계가 `5.0` / `high`라 사실상 동점이다.
그 결과 같은 등급 안에서의 순서는 Neo4j가 행을 돌려주는 순서에 가깝다.
등급(`자동`/`반자동`/`근거없음`)만 신뢰할 만한 신호다.
진짜 순위는 fab SQL 검증 결과가 돌아와야 정해진다.
> 

**문장 합성** — 경로가 수십 개일 수 있어 `SYNTHESIS_BATCH`(12개)씩 나눠 LLM을 부른다.
LLM이 문장을 덜 돌려주면 부족분을 사실 기반 문장으로 채운다. 가설을 조용히 버리지 않는다.
`(Cause, Evidence)` 쌍으로 중복 제거 후 상위 3건을 낸다.

**검증** — 진단 대상 lot으로 `lot_history`를 조회해 equipment_id·ts를 바인딩하고,
Evidence 라벨에 따라 fab 테이블을 조회해 가설을 채택/기각한다.

---

## 예시 인스턴스

### Edge-Ring (공정 경유)

실제 그래프에서 뽑은 인스턴스다.

- `DefectPattern` **Edge-Ring** `ARISES_IN->` `ProcessStep` **ETCH**
- `FailureMode` **incorrect_etch_rate** `OCCURS_IN->` `ProcessStep` **ETCH**
    - `CAUSED_BY->` `Cause` **improper_maintenance** `VERIFIED_BY->` `Maintenance` **chamber_wet_clean** `[반자동]`
    - `CAUSED_BY->` `Cause` **incorrect_process_recipe** `VERIFIED_BY->` `Recipe` **process_recipe** `[반자동]`
- `FailureMode` **excessive_post_etch_residue** `OCCURS_IN->` **ETCH**
    - `CAUSED_BY->` `Cause` **incorrect_process_parameter_high_etch_rate**`VERIFIED_BY->` `Parameter` **etch_rate** (`direction=high`) `[자동]`

### Scratch (두 경로가 함께 성립)

문서 C의 Scratch 행이 CMP를 명시하므로 공정 경유 경로도 열린다.

- `DefectPattern` **Scratch** `ARISES_IN->` `ProcessStep` **CMP**
→ `FailureMode` **pad_polishing** `CAUSED_BY->` `Cause` **worn_pad**`VERIFIED_BY->` `Maintenance` **replace_polishing_pad** `[반자동]`
- **Scratch** `ATTRIBUTED_TO->` `Cause` **scratches_caused_by_polishing_during_cmp** `[근거없음]`
- **Scratch** `ATTRIBUTED_TO->` `Cause` **scratches_on_wafer_surface_by_transfer_robots** `[근거없음]`

### Edge-Ring (직결, anneal 스코프 밖)

- **Edge-Ring** `ATTRIBUTED_TO->` `Cause` **anomalous_temperature_regulation_during_rapid_thermal_process_rtp**
→ RTP는 fab 6스텝 밖이라 계측이 없다. evidence 노드가 없어 `[근거없음]`.