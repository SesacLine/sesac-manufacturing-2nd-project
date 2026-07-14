# Wafer Defect RCA — Knowledge Graph Schema

반도체 웨이퍼 결함 근본원인 분석(RCA)용 지식 그래프 스키마 명세.
GraphRAG(문서/도메인 지식) 기반의 **원인 가설 생성용** 그래프.
가설 검증은 별도 fab 데이터(SQL)가 담당하며, KG는 `Parameter` 노드로 그 SQL과 연결된다.

## 문서 소스와 결합 구조

두 종류의 문서를 수집하며, 서로 다른 진입점을 가진다. **`ProcessStep`이 둘을 잇는 join 노드다.**

- **문서 A (웨이퍼맵 패턴):** `DefectPattern → ProcessStep`
  "circular ring은 etch/deposition/anneal 공정을 의심" 처럼 패턴이 **어느 공정**을 가리키는지.
- **문서 B (공정 troubleshooting):** `FailureMode → Cause → Parameter`
  특정 공정 내부의 고장 모드 → 원인 → 관여 변수. (예: ETCH troubleshooting 표)

두 문서가 같은 `ProcessStep`(예: ETCH)을 언급하면 그래프에서 자동 결합된다.
스텝 이름은 통제된 소집합이라 정렬이 쉽다 (Cause 자유텍스트 대비 안정적인 join key).

**추출 전제:** 모든 엔티티·관계는 문서에서 추출한다.
단, `DefectPattern`과 `ProcessStep`은 **고정 vocabulary**로, 새로 만들지 않고 사전 정의된 라벨로 매핑만 한다.

---

## Node Types

| Label | id (예시) | Properties | 추출 방식 | 설명 |
|---|---|---|---|---|
| `DefectPattern` | `Edge-Ring` | `name` | **고정 목록** | 웨이퍼맵 패턴 (질의 진입점) |
| `ProcessStep` | `ETCH` | `name` | **고정 목록** | 공정군 (문서 A·B의 join 노드) |
| `FailureMode` | `post_etch_residue` | `name` | 문서 추출 | 공정 고장 모드 |
| `Cause` | `high_etch_rate` | `name` | 문서 추출 | 근본 원인 |
| `Parameter` | `etch_rate` | `name` | **고정 목록** | 검증 변수. **fab SQL 연결점** |
| `Equipment` | `ETCH-03` | `name`, `equip_group` | 문서 추출 | 장비 인스턴스 |

- 모든 노드는 `id`를 유일 키로 가진다 (라벨별 UNIQUE 제약).
- `Parameter.id`는 fab `telemetry.param` 값과 **동일 문자열**로 맞춘다 (join key).
- `FailureMode.id` / `Cause.id`는 소문자 snake_case로 정규화한다.

### 고정 vocabulary
추출기는 아래 목록 중 하나로만 매핑한다. 목록에 없으면 매핑 보류.

- **DefectPattern:** `Center`, `Scratch`, `Edge-Ring`
- **ProcessStep:** `LITHO`, `ETCH`, `DEPO`, `CMP`, `CLEAN`, `EDS`
- **Parameter:** `fab.md`의 장비군별 파라미터 20종 (`seeds/parameters.json`)

세 라벨의 노드는 적재 전 **사전 시딩**되며, ingest는 새로 생성하지 않고 연결만 한다.
`Parameter`도 join key를 지켜야 하므로 자유 추출이 아니라 고정 목록으로 다룬다.

**표기 흔들림 처리:**
`5_build_kg_from_chunks.py`가 시드의 `aliases`로 `alias → canonical id` 역인덱스를 만든다
(`resolve_anchor`). `validate_kg`는 앵커를 가리키는 관계를 버리기 전에 이 인덱스를 한 번 거친다.
대소문자·하이픈·밑줄·공백 차이를 흡수하므로 `edge-ring`, `edge_ring`, `circular ring`이 모두
`Edge-Ring`으로 붙는다. 못 붙이면 사유를 로그로 남기고 버린다(조용한 유실 금지).

`aliases`만 쓰고 `spatial_keywords`는 매칭에 쓰지 않는다. 후자는 여러 패턴에 동시에 걸린다.
`expected_zone` / `expected_shape`는 VLM 관측 정합성 체크용이며 아직 쓰이는 곳이 없다.

고정 목록의 id는 `5_build_kg_from_chunks.py`의 Literal에도 하드코딩돼 있다(LLM에 넘길 JSON
schema를 정적으로 만들어야 해서). 시드와 어긋나면 실행 즉시 `assert_enums_match_seeds`가 터진다.

> 참고: 문서 A가 RTA(anneal)를 언급하나 fab 6스텝 밖. anneal 스코프 포함 여부는 별도 결정.

---

## Relationship Types

| 소스 | Edge | Source | → | Target | 의미 |
|---|---|---|---|---|---|
| A | `ARISES_IN` | `DefectPattern` | → | `ProcessStep` | 이 패턴이 어느 공정을 의심케 하는가 |
| B | `OCCURS_IN` | `FailureMode` | → | `ProcessStep` | 이 고장이 어느 공정에서 일어나는가 |
| B | `CAUSED_BY` | `FailureMode` | → | `Cause` | 무엇이 원인인가 |
| B | `INVOLVES_PARAMETER` | `Cause` | → | `Parameter` | 어떤 변수가 관여하는가 |
| — | `PART_OF` | `Equipment` | → | `ProcessStep` | 장비가 어느 공정군에 속하는가 |

`PART_OF`는 LLM이 추출하지 않는다. `Equipment.equip_group`에서 규칙으로 파생한다.

### 방향 원칙
- `DefectPattern`과 `FailureMode`는 둘 다 `ProcessStep`으로 향한다 (join 노드로 수렴).
- `FailureMode`와 `Cause`는 분리 유지 (FMEA 고장 모드 / 근본 원인 구분). 병합하지 않는다.

### 관계 속성
- 공통: `extraction_confidence`(1~5), `description`, `quotes`, `chunk_ids`(근거 청크)
- `ARISES_IN` 전용: `occurrence_prior` (`high`/`mid`/`low`)
- `INVOLVES_PARAMETER` 전용: `direction` (`high`/`low`)

---

## Backbone 요약 (텍스트 다이어그램)

```
DefectPattern ──ARISES_IN──────────────┐
 (Edge-Ring)                            ▼
                                   ProcessStep ◄──OCCURS_IN── FailureMode
                                     (ETCH)      (join)       (post-etch residue)
                                                                    │ CAUSED_BY
                                                                    ▼
Equipment ──PART_OF──> ProcessStep                                Cause
 (ETCH-03)                                                    (high etch rate)
                                                                    │ INVOLVES_PARAMETER
                                                                    ▼
                                                                Parameter
                                                             (etch_rate → SQL)
```

- **질의 진입점:** `DefectPattern` (고정 3개)
- **join 노드:** `ProcessStep` — 문서 A·B가 만나는 지점
- **검증 종착점:** `Parameter` (`Parameter.id` ↔ `telemetry.param`)

## 가설 생성 순회

1. 관찰된 `DefectPattern`에서 `ARISES_IN`으로 의심 `ProcessStep` 집합을 얻는다.
2. 각 `ProcessStep`에 `OCCURS_IN`으로 걸린 `FailureMode`들을 후보로 모은다.
3. 각 `FailureMode` → `Cause` → `Parameter` 경로 하나하나가 **가설 1건**.
4. 그 `Parameter`(+향후 maintenance/recipe)를 fab SQL로 검증해 가설을 채택/기각.

---

## 예시 인스턴스 (Edge-Ring 시나리오)

- `DefectPattern` **Edge-Ring** `-ARISES_IN->` `ProcessStep` **ETCH**
- `FailureMode` **post-etch residue** `-OCCURS_IN->` `ProcessStep` **ETCH**
- **post-etch residue** `-CAUSED_BY->` `Cause` **high etch rate**
- **high etch rate** `-INVOLVES_PARAMETER->` `Parameter` **etch_rate**
- `Equipment` **ETCH-03** `-PART_OF->` `ProcessStep` **ETCH**