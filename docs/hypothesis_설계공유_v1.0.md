# ⑤ Hypothesis (build_hypotheses) 설계 공유 문서 v1.0

> **목적**: 이 노드를 열어보지 않고도 ①무엇을 받아 무엇을 내놓는지 ②실패하면 어떻게 되는지
> ③왜 그렇게 설계했는지를 알 수 있게 한다. 코드 설명서가 아니라 **계약서 + 설계 의도**다.
>
> **번호 주의**: 현행 파이프라인 번호(⓪~⑦) 기준으로 이 노드는 **⑤**다. 구 문서의
> "④ Hypothesis"와 같은 노드다 — 07-23에 VLM 관측 노드가 중간에 들어오며 번호가 한 칸 밀렸다.
>
> **짝 노드**: ⑥ Critic(`critic.py`) → `critic_설계공유_v1.0.md`. ⑤가 증거를 모으고 ⑥이
> 그 증거로 판정한다. 둘이 붙어서 하나의 "조사 → 판정" 흐름을 이룬다.

---

## 0. 요약

- **노드**: ⑤ `build_hypotheses`
- **파일**: `backend/nodes/hypothesis.py`
- **담당**: 안지운
- **한 줄 역할**: KG(문헌으로 만든 지식그래프)가 준 "일반적으로 이런 원인이 있을 수 있다"는 원인
  후보들을, 이번 배치의 실제 fab 운영데이터(MCP 도구)로 하나씩 조사해 증거를 붙이고, 증거가 강한
  순서로 정렬한다. **이 노드가 없으면** 문헌 일반론만 남고 "이번 불량 로트에서 실제로 무슨 일이
  있었는가"를 후보에 붙이지 못한다.
- **상태**: 구현 완료. 다만 (a) `반자동` 등급 후보의 실제 판정 경로는 아직 없다(정황만 수집하고
  판정은 ⑥이 보류), (b) VLM 자연어 관측은 ③ 노드 소관이라 이 노드 범위 밖.
- **작성일 / 대상**: 2026-07-24 / 브랜치 `refactor/#45-llm-eng-and-docs-edit`
  (LLM 서사 `rationale`와 표시 문자열을 영문으로 통일한 #45 반영, 작성 시점 미커밋)

**이 문서에서 쓰는 용어** (첫 등장 순, 자세한 정의는 부록 B):
`suspect`(의심 장비) · `commonality_ratio`(공통률) · `drift`(정상범위 이탈) ·
`normal_ratio`(정상 로트 비율) · `tier`(검증등급) · `unit`/`클러스터` · `investigated`(조사 여부) ·
`옵션 A` · `함정`.

---

## 1. 입출력 계약 (필수)

이 노드는 그룹(같은 결함 패턴으로 묶인 로트들) 하나마다 1회 실행된다. 아래 키는 그룹 단위
상태(`state.py`의 `GroupState`) 기준이다.

### 1-1. 입력

| state 키 | 타입 | 채우는 주체 | 없으면 / None이면 |
|---|---|---|---|
| `candidates` | `list[GraphRAGCandidate]` | ④ fetch_graphrag_candidates | 빈 리스트면 이 노드에 **도달하지 않는다**(④ 뒤 조건부 엣지가 ⑦'로 보냄). 그래도 도달하면 `hypotheses=[]` 반환 |
| `lot_ids` | `list[str]` | ⓪~② | 필수 — 조사 대상 로트. 없으면 조사할 게 없음 |
| `pattern` | `str` | ② grouper | 로그·표시용 |
| `mcp` (주입) | `MCPClient` 싱글턴 | `deps.py` | 없으면 fab 증거 수집 불가 |

- **전제조건**: `candidates`는 ④가 이미 패턴 필터 + 형상 재랭킹까지 끝낸 상태다. 각
  `candidate.tier`는 `자동`/`반자동`/`근거없음` 중 하나다. `candidate.evidence`는 fab.db와
  실제로 결합(join)하는 키(Parameter/Maintenance/Recipe 식별자)다 — cause 이름 문자열은 join 키가 아니다.
- **가정이 깨지면**: candidate에 필수 키(`step`/`evidence`/`tier`/`cause`)가 없으면 `KeyError`로
  **그 그룹 배치만 중단**된다(조용히 통과하지 않는다 — 계약 위반은 눈에 띄게 실패시킨다).

### 1-2. 출력

| state 키 | 타입 | 비고 |
|---|---|---|
| `hypotheses` | `list[Hypothesis]` | 최종 표시 순서로 정렬됨. 행 수 = 입력 후보 수(1:1 대응, 후보를 버리지 않음) |

**하위 노드(⑥·⑦)가 믿어도 되는 불변식** — 여기 쓴 문장이 곧 테스트다:
- **`hypotheses`의 순서가 곧 최종 표시 순서다.** ⑥·⑦은 순서를 보존만 하므로 `hypotheses[0]`이
  프론트 대표원인 카드가 된다(BACKEND_DECISIONS D1).
- **`evidence`의 모든 수치는 도구 반환값에서 온다**(옵션 A). LLM이 만든 수치는 하나도 없다.
- `investigated=False`인 행은 telemetry 판정 필드(`drift_detected` 등)가 비어 있을 수 있다 —
  "조사하지 못했다"는 사실을 그대로 기록한 것이지 오류가 아니다.
- 모든 행에 `cluster_id`(str)·`is_primary`(bool)가 붙는다. `자동` 등급 조사 행에는
  `rationale`(LLM 서술)이 붙는다.
- **내가 건드리지 않는 키**: `critic_result`, `final_response`.

### 1-3. 새로 도입/변경한 필드 (`state.py`)

| 필드 | 타입 | 왜 필요한가 |
|---|---|---|
| `investigated` | `bool` | 그 후보를 실제로 조사(도구 조회)했는지. ⑥이 "반박"과 "미조사 보류"를 가르는 입력 |
| `cluster_id` | `str` | fab 데이터로 서로 구분 불가한 후보들의 묶음 표식(원인군 카드) |
| `is_primary` | `bool` | 같은 cause가 여러 장비에 걸칠 때 대표 행 1개 표시 |
| `rationale` | `str` | LLM 에이전트의 조사 서술. **판정 근거로는 안 씀**(옵션 A). #45로 영문 |
| `matched_cause` | `str \| None` | E2E 평가 전용(운반만, 표시·판정에는 안 씀) |
| `evidence` 하위 | — | `drift_direction`, `direction_match`, `telemetry_*`(series/normal_range/summary), `commonality_rows` 등 근거 모달용 리치 필드 |

---

## 2. 실패·경계 케이스 계약 (필수)

| 상황 | 이 노드의 동작 | 하위 노드(⑥)가 보게 되는 것 |
|---|---|---|
| 입력 `candidates`가 빔 | `hypotheses=[]` 반환 | 채택 0건 → ⑥ status `insufficient` |
| MCP 조회 실패 / 의심 장비(suspect) 특정 불가 | 그 step 배치를 **미조사 폴백**(`investigated=False`), pre-pass로 얻은 값은 보존 | ⑥이 판단 보류(judge_unknown)로 분류 |
| LLM 에이전트 폭주(스텝 상한 8 초과) | `GraphRecursionError`를 잡아 그 배치 미조사 폴백 | 위와 동일 |
| telemetry 0포인트 / 정상범위 없음 | `drift_detected=None`(판정 안 함) | 조사됐는데 None이면 ⑥ P4 기각, 미조사면 보류 |
| candidate 필수 키 누락 | `KeyError`(계약 위반) | 그 그룹 배치만 중단 |

- **예외를 던지는 경우**: `KeyError`(계약 위반)뿐이며 **그 그룹만** 죽는다 — 배치 전체는 안 죽는다.
  그 외 외부 실패(MCP/LLM)는 전부 폴백으로 흡수한다.
- **타임아웃·재시도**: **재시도 없음.** telemetry는 step 배치당 1콜, 에이전트 스텝 상한은 8.
  근거를 못 모으면 재시도하지 않고 미조사로 남긴다(이것이 환각 억제 원칙).

---

## 3. 내부 플로우

```
build_hypotheses(candidates, lot_ids, mcp)
 1. step 폴백        step=None 후보를 mapping.process로 보충 (_with_step_fallback, D14)
 2. 시간창 준비      telemetry창 = 전 로트 공정구간 합집합 (D15)
                    maintenance창 = 공정시작 ~ 결함시각+14일 (D13, 비대칭)
 3. tier 분기
    ├ 자동         → investigate_group  (LLM 에이전트, step 단위 배치)      ← 아래 상세
    └ 반자동·근거없음 → 결정론 루프 (같은 unit은 캐싱해 중복 호출 방지)
 4. 원순서 조립      두 갈래 결과를 KG 순위 순서로 한 리스트에
 5. 클러스터 주석    cluster_id / is_primary 부여 (순서·행 수 안 바뀜)
 6. fab 재랭킹      _rank_hypotheses — 여기서 최종 표시 순서가 정해진다  ← 대표원인 결정
 7. defect_ts 스탬프 → {"hypotheses": [...]}
```

`자동` 등급 후보를 조사하는 `investigate_group` 내부:

```
자동 후보들을 step별로 묶는다 (CMP 후보끼리, DEPO 후보끼리…)
 └ 배치(step)마다:
    1. pre-pass(결정론): commonality 분석 → 의심 장비(suspect) 확정 + normal_ratio 수집
       └ suspect를 못 정하면 → 배치 전체 미조사 폴백
    2. 에이전트 1루프(create_react_agent, temp=0):
       코드가 확정 사실(suspect·step·시간창·후보 목록)을 프롬프트에 주입하고
       "query_telemetry를 한 번만, params를 리스트로 전부" 지시
    3. 도구 반환에서 판정(결정론): series를 param별로 나눠 후보마다 drift·방향·일치 계산
```

- **분기 근거**: `tier`는 "그 후보를 어떤 도구로 확인할 수 있는가"를 KG가 빌드타임에 매긴
  등급이다. `자동`(센서값=Parameter)만 정상범위 기준이 있어 시스템이 수치로 판정할 수 있고,
  그래서 `자동`만 telemetry 조사 경로로 보낸다.

---

## 4. 설계에서 중요하게 고려한 것 (필수)

### 4-1. 자동 tier에 LLM 에이전트를 쓰되, 수치 판정은 코드가 한다 (옵션 A)

- **문제**: fab 조회 도구가 9종 노출돼 있고, tier·도구 종류가 늘면 "어떤 도구를 어떤 순서로
  부를지"를 조건 분기 코드로 유지하기 어렵다. 반대로 drift 여부 같은 수치 판정을 LLM에 맡기면
  오판·환각의 여지가 생기고 재현성도 깨진다.
- **선택**: 도구 오케스트레이션(어떤 도구를 부를지)은 LLM 에이전트(`create_react_agent`)에
  위임하고, drift·방향 등 **수치 판정은 도구 원본 반환값(ToolMessage)에서 코드가 결정론으로
  재구성**한다. LLM이 만드는 것은 `rationale`(서술)뿐이다.
- **대안과 기각**: 전면 결정론 → 도구 선택 유연성을 잃음. 전면 LLM 판정 → 재현성 0, 뒤의 ⑥이
  evidence만 읽는 방식이 성립 불가.
- **되돌릴 조건**: 조사에 쓰는 도구가 사실상 1종으로 굳으면 에이전트를 빼고 결정론 단일 호출로
  단순화할 수 있다.

### 4-2. 후보 단위가 아니라 step 배치로 조사한다 (성능)

- **문제**: cause 수십 개가 같은 센서(param)를 가리킨다. 후보마다 telemetry를 1콜씩 부르면
  Center 244건 기준 타임아웃이 났다(실측).
- **선택**: `자동` 후보를 step별로 묶어, **장비당 telemetry 1콜**(params 전부)로 여러 후보를
  동시에 판정한다. 실측으로 후보 6개·step 2종에서 telemetry 5콜 → 2콜.
- **대안과 기각**: 후보 단위 캐싱만 적용 → 부분 완화에 그침, 여전히 느림.
- **되돌릴 조건**: 후보 수가 적은 소규모 데이터면 배치 이득이 미미해진다.

### 4-3. 최종 순위를 fab 증거로 다시 계산한다 — 대표원인이 여기서 정해진다 (D1·D16)

- **문제**: KG가 준 순위는 "문헌에 얼마나 많이 나오나"(근거량) 기준이라, 이번 배치의 실제
  원인과는 무관하다.
- **선택**: 조사가 끝난 뒤 **클러스터 단위로 4단계 키를 적용해 다시 정렬**한다
  (증거 세기 → `commonality_ratio` → `normal_ratio` → KG 순위). 정확한 키 정의는 D1·D16.
- **대안과 기각**: KG 순위를 그대로 사용 → SC-CENTER-01에서 정답이 193위로 밀렸다.
- **되돌릴 조건**: 증거 세기 산식(`_evidence_strength`)을 다시 설계하면 이 정렬도 함께 봐야 한다.

### 4-4. 지지 증거와 반박 증거는 조회 구간이 다르다 (D13·D15)

- **문제**: "결함 전에 센서가 이상했다"(지지)와 "그 정비는 결함 이후였다"(반박=시간역전)는 봐야
  하는 시간 구간이 다르다. 결함 이전만 조회하면 시간역전 반박 재료를 못 모은다.
- **선택**: telemetry 창은 결함 이전 구간(전 로트 합집합, 커버리지 공백에 강건), maintenance 창만
  결함 이후 +14일까지 비대칭으로 넓힌다. **telemetry 창은 넓히지 않는다** — 결함 이후의 이탈은
  원인일 수 없어서 지지 증거로 잘못 잡히면 안 된다.
- **되돌릴 조건**: 결함 확정 시각(defect_ts, EDS 이벤트)이 없으면 연장 기준점이 없어 원래 창 유지.

### 4-5. 같은 신호에 정반대 방향을 예상하는 후보는 "방향"으로 가른다

- **문제**: 같은 센서에 "값이 높아야 원인"인 cause와 "낮아야 원인"인 cause가 공존한다. 이탈
  여부만 보면 둘 다 통과해 구분이 안 된다.
- **선택**: 실측 방향(`_drift_direction`)과 KG 예상 방향을 대조(`_direction_match`)한다. 어느
  한쪽이라도 불확실하면 판정하지 않고 `None`으로 둔다("확실할 때만 판정" 원칙).
- **되돌릴 조건**: KG가 방향을 안 준 후보(`direction=null`)는 여전히 판정 불가(n/a)로 남는다.

---

## 5. 외부 의존 (LLM · MCP · 파일)

| 무엇 | 어디 | 결정적인가 | 없으면 |
|---|---|---|---|
| KG 후보(`hypotheses.json`) | ④가 이미 조회해 `candidates`로 넘김 | 결정적 | 후보 없음 → 이 노드 미도달 |
| LLM (`create_react_agent`) | `자동` tier 조사 | **비결정적** (temp=0으로 완화) | 폴백: 미조사로 남김 |
| MCP `run_commonality_analysis` / `get_normal_lot_ratio` | pre-pass(모든 후보 공통) | 결정적 | suspect 못 정함 → 미조사 |
| MCP `query_telemetry` | `자동` tier | 결정적 | drift 판정 불가 |
| MCP `get_maintenance_history` | `반자동`(Maintenance) | 결정적 | 정황 미수집 |
| MCP `get_lot_history` / `get_lot_timeline` | 시간창·defect_ts | 결정적 | 기본 창으로 대체 |

- **비결정 요소**: 에이전트의 도구 호출 순서와 `rationale` 문장은 매 실행 달라질 수 있다. 그러나
  **수치(evidence)는 도구 반환에서 코드가 계산하므로 판정 결과는 재현된다.**
- **호출량(대략)**: 그룹당 commonality/normal_ratio는 step 배치 수만큼, telemetry는 step 배치당
  1콜, `get_lot_history`는 로트 수만큼.

---

## 6. 튜닝 상수 · 매직넘버

| 이름 | 값 | 위치 | 근거 |
|---|---|---|---|
| `AGENT_RECURSION_LIMIT` | 8 | `hypothesis.py` | 정상 경로는 3스텝(agent→tool→agent). 예상 밖 재호출 2~3회는 허용하되 폭주는 끊음 |
| `MAINT_LOOKAHEAD_DAYS` | 14 | `hypothesis.py` | 결함 이후 정비(시간역전 반박 재료) 수집 창 (D13) |
| `max_points` | 500 × param 수 | `_build_group_prompt` | 서버 다운샘플에서 특정 param이 통째로 빠지는 것 방지 |
| `temperature` | 0 | `_make_model` | 재현성(같은 입력 → 같은 결과) |

---

## 7. 테스트 현황

- **단위 테스트**: `backend/tests/test_hypothesis_agent.py`(테스트 함수 17개). 배치 판정 분배,
  방향 대조, 클러스터 주석, 재랭킹 4단 키, 스텝 상한 초과 시 미조사 폴백, 시간창 계산을 고정한다.
  fab.db 없이 mock으로 실행된다(`pytest -q -m "not data"` = CI와 동일 조건).
- **아직 검증 못 한 케이스**:
  - `반자동` 실제 조사 경로(현재는 전원 판단 보류로만 나감).
  - Edge-Ring/Scratch E2E(지금은 SC-CENTER-01 1개 시나리오만 실행).
  - 실제 LLM이 여러 후보의 `rationale`을 어떻게 분담하는지(현재 배치 1루프가 서술을 공유).

---

## 8. 알려진 한계 · 팀 논의 필요

| # | 항목 | 내 제안 | 결정 필요 |
|---|---|---|---|
| 1 | `반자동` 실제 판정 경로 없음(전원 보류) | Maintenance 텍스트 판정 주체(사람 API vs LLM 의미매칭) 결정 후 구현 | **팀 안건** |
| 2 | `drift=False`(정상범위 안)도 채택되는 기준 — 채택 수가 많음 | 반대증거 게이트(`normal_ratio` 임계) 도입 검토 | **팀 안건** |
| 3 | 라이브 KG 경로(LiveKGClient)엔 `matched_cause`/`mapped_process`가 없음 | 조회 시점에 계산하도록 설계 | 후속 이슈 |
| 4 | 시나리오 10개 잔여 + 단일경로 baseline 비교(기획안 §10 핵심 실험) | 다음 작업으로 진행 | 다음 작업 |

---

## 부록 A. 코드 진입점 맵

| 하고 싶은 일 | 볼 곳 |
|---|---|
| 노드 전체 흐름 | `hypothesis.py` `build_hypotheses` |
| 에이전트 배치 조사 | `investigate_group` → `_build_group_prompt` → `_to_hypotheses_batch` |
| 방향 대조 | `_drift_direction` / `_direction_match` |
| 클러스터 / 대표 행 | `_cluster_key` / `_evidence_strength` / `_annotate_clusters` |
| 재랭킹 4단 키 | `_rank_hypotheses` |
| 시간창 | `_group_time_range` / `_maintenance_range` |
| step 폴백 | `_with_step_fallback` |
| 정책 결정 이력 | `docs/BACKEND_DECISIONS.md` D1 · D13~D16 |

## 부록 B. 용어

| 용어 | 뜻 (Plain) |
|---|---|
| suspect(의심 장비) | commonality 분석이 "불량 로트들이 공통으로 지난 장비"로 지목한 `equipment_id` |
| commonality_ratio(공통률) | 불량 로트 중 그 장비를 지난 비율. 1.0이면 불량 로트 전부가 그 장비를 지남 |
| drift | 센서 측정값이 정상범위 `[lo, hi]`를 벗어난 상태. 방향(high/low)까지 본다 |
| normal_ratio(정상 로트 비율) | 그 장비를 지난 로트 중 정상(불량 아님) 비율. 높으면 그 장비가 원인일 가능성을 낮추는 반대 증거 |
| tier(검증등급) | KG가 후보마다 매긴 "어떤 도구로 확인 가능한가" 등급. `자동`(센서값)/`반자동`(정비·레시피)/`근거없음` |
| unit(검증단위) | `(step, evidence_label, evidence)` 세 값. 같으면 fab에 던지는 조회가 동일하다 |
| 클러스터 | unit + KG 예상 방향. fab 데이터로는 서로 구분할 수 없는 후보 묶음 |
| investigated | 그 후보를 실제로 도구 조회했는지 여부(bool). False면 ⑥이 판단 보류 |
| 옵션 A | 수치는 코드가 도구 반환에서 계산하고, LLM은 서술(rationale)만 담당하는 방식 |
| 함정(trap) | 상관관계는 높지만 실제 원인이 아닌 장비. ground truth `traps_to_reject`에 명시돼 있고, 시뮬레이터가 의도적으로 넣는다 |
