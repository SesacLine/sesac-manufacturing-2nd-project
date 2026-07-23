# ④ Hypothesis · ⑤ Critic 설계 공유 문서 v1.0

> **목적**: ④ Hypothesis와 ⑤ Critic이 어떻게 설계·구현·검증됐는지 한 문서로 이해할 수 있게.
> **작성**: 2026-07-23 (브랜치 `feat/#22-hypothesis_critic_implement`, PR #36 기준).
> **코드**: `backend/nodes/hypothesis.py` · `backend/nodes/critic.py` · `backend/state.py`.
> 내부 정책 결정 기록은 `docs/BACKEND_DECISIONS.md`(특히 D1·D8·D13~D16).

---

## 0. 요약

④ Hypothesis는 KG가 준 원인 후보들을 fab 운영데이터(MCP)로 조사해 증거를 수집하고,
증거 강도 순으로 정렬한다(soft — 기각 판정은 하지 않음). ⑤ Critic은 그 증거만 읽고
규칙대로 채택/기각/보류를 확정한다(hard — fab 재조회 없음). 판정 근거가 항상 도구 반환값에서
오도록 역할을 분리한 것이 환각 억제의 핵심 장치다.

검증 결과: **ground truth 시나리오 SC-CENTER-01에서 정답 근본원인을 top-1로 산출했고,
함정 장비(traps_to_reject)를 시간역전 규칙으로 명시 기각했다** (§7 테스트 결과).

---

## 1. 전체 파이프라인에서의 위치

배치 실행 시 파이프라인은 ⓪~⑥ 순서로 실행된다 (그룹 = 같은 결함 패턴으로 묶인 로트들):

```
⓪ 저수율 로트 선별 (lowyield.py)      fab.db SQL — 누적 구간
① 웨이퍼맵 판독   (vlm.py)           지금은 pattern="Center" 하드코딩
② 패턴별 그룹화   (grouper.py)       로트별 다수결 대표패턴
③ 원인 후보 조회  (graphrag.py)      kg_rca hypotheses.json 조회 — 문헌 기반 일반 원인
──────────────────────────────────────────────────────────────
④ Hypothesis     (hypothesis.py)    MCP로 증거 수집·검증·재랭킹 — 이번 배치의 실제 데이터   ★이 문서
⑤ Critic         (critic.py)        규칙 게이트 — 채택/기각/보류 확정                      ★이 문서
──────────────────────────────────────────────────────────────
⑥ 응답 생성      (response.py)      카드 조립 — hypotheses[0] = 대표원인
```

- ③까지는 문헌이 말하는 일반론(후보 수백 건, Center 기준 297건)이고, ④⑤가 그걸
  이번 배치의 fab 데이터로 검증해 추려낸다.
- **④의 출력 순서가 곧 최종 표시 순서다.** ⑤⑥은 순서를 보존만 하므로, ④가 1위로 정렬한
  가설이 프론트 대표원인 카드(`hypotheses[0]`)가 된다(BACKEND_DECISIONS D1).

---

## 2. 설계 원칙 — 왜 이렇게 나눴나

### 2-1. ④ soft / ⑤ hard (판정 책임 경계)

| | ④ Hypothesis | ⑤ Critic |
|---|---|---|
| 성격 | **선택·수집·랭킹** | **게이트·거부권(veto)** |
| 하는 일 | 어떤 후보를 어떻게 조사할지 결정, 증거 수집, fab 증거로 순위 산정 | 넘어온 후보를 규칙으로 채택/기각/보류 |
| 안 하는 일 | **기각 판정 안 함** | **순위 변경 안 함, 재조사 안 함** |
| 구현 | 자동 tier = LLM 에이전트 / 나머지 = 결정론 | 전부 결정론 (LLM 미사용) |

### 2-2. 옵션 A — 수치는 코드가, 서사만 LLM이

④의 자동 tier에 LLM 에이전트가 들어갔지만, **LLM은 수치를 생성하지 않는다**:
- 에이전트가 도구(query_telemetry)를 호출하면, 그 **도구의 원본 반환값(ToolMessage)에서
  코드가 결정론으로** drift 여부·방향 등을 재구성한다.
- LLM이 산출하는 것은 rationale(조사 과정을 설명하는 자연어 서술)뿐이다.

### 2-3. Faithfulness firewall

⑤ Critic은 **④가 채운 구조화 evidence만 읽는다** — LLM의 rationale은 판정에 사용하지 않고,
fab을 재조회하지도 않는다(실측: ⑤ 구간 MCP 호출 0회). 옵션 A에 의해 evidence의 모든 수치가
도구 출처이므로 이 방식이 성립한다. LLM이 잘못된 수치를 서술해도 판정에 유입되지 않는다.

### 2-4. 환각 억제 — 확인하지 못한 것은 판정하지 않는다

- 조사하지 못한 후보는 채택도 기각도 아닌 **보류(judge_unknown)** 로 분류한다 —
  "조사 안 됨"과 "반박됨"을 구분한다.
- 채택 후보가 0개면 재시도 없이 즉시 "판단 불가(insufficient_evidence)"를 반환한다 —
  근거 없이 답을 생성하지 않는다.
- 에이전트가 도구 호출을 누락하거나 스텝 상한을 초과해도 "조사됨"으로 잘못 기록되는 경로가
  구조적으로 없다(§4-6).

---

## 3. 사전 도메인 지식

### 3-1. 검증등급 tier 3단 — 어떤 도구로 확인 가능한가

KG가 각 후보에 빌드타임에 부여한다. ④가 어떤 MCP 도구를 호출할지 이 등급이 결정한다.

| tier | 증거 종류 | 의미 | ④의 처리 |
|---|---|---|---|
| `자동` | Parameter(센서값) | 정상범위 수치 기준이 있어 시스템이 판정 가능 | **LLM 에이전트**가 telemetry 조사 |
| `반자동` | Maintenance/Recipe | 조회는 되지만 판정엔 사람 필요(자유 텍스트) | 결정론으로 정황만 수집 → ⑤ 보류 |
| `근거없음` | 없음 | 문헌에만 있고 fab으로 확인 불가 | MCP 호출 없음 → ⑤ 보류 |

### 3-2. 핵심 신호 4개

| 신호 | 뜻 | 출처 도구 | 역할 |
|---|---|---|---|
| **commonality_ratio** | 불량 로트들이 그 장비를 공통으로 지난 비율 | run_commonality_analysis | 의심 장비(suspect) 지목 + **인과 필요조건**(원인 장비라면 불량 로트 전부가 지났어야 함) |
| **drift** | 센서값이 정상범위 [lo,hi]를 벗어남 | query_telemetry | 자동 tier의 직접 증거. 방향(high/low)까지 판정 |
| **normal_ratio** | 그 장비를 지난 **정상** 로트 비율 | get_normal_lot_ratio | **반대 증거** — 높으면 해당 장비가 정상 로트도 다수 생산했다는 뜻이므로 순위 할인 |
| **maintenance_ts / defect_ts** | 정비 시각 / 결함 확정(EDS) 시각 | get_maintenance_history / get_lot_timeline | **시간정합** — 정비가 결함보다 늦으면 원인일 수 없음 |

### 3-3. 검증단위(unit)와 클러스터 — fab 데이터가 구분할 수 있는 한계

- **unit** = `(step, evidence_label, evidence)`. 이 세 값이 같으면 fab.db에 던지는 조회가
  완전히 동일하다 — cause 이름이 달라도 같은 데이터로 판정된다.
- **클러스터** = unit + **direction**(KG가 예상한 drift 방향). 같은 unit이라도 예상 방향이
  다르면(예: slurry_flow "과다(high)" vs "부족(low)") 방향 대조로 판별되는 **경쟁 가설**이므로
  묶지 않는다.
- 같은 클러스터 안의 cause들은 **fab 데이터로는 어떤 방법으로도 구분할 수 없다.** 그래서
  구분 불가한 것들끼리 임의 순위를 매기지 않고 원인군 하나로 묶어서 내보낸다. Hypothesis
  행마다 `cluster_id`가 붙고, 프론트/⑥이 이걸로 원인군 카드를 묶을 수 있다.

### 3-4. 함정(trap) — 이 시스템이 걸러내야 하는 것

시뮬레이터 시나리오에는 **상관관계는 높지만 원인이 아닌 장비**가 의도적으로 포함돼 있다
(ground truth의 `traps_to_reject` 필드). 예: SC-CENTER-01의 LITHO-01은 불량 로트 8개가
전부 통과했고(공통률 1.0) 정비 기록도 있지만, 그 정비 시각이 **결함 발생 이후**다.
공통률만 보면 원인 후보로 보이지만 시간 순서상 원인일 수 없다 — 상관관계와 인과관계를
시스템이 구조적으로 구분하는지 검증하기 위한 장치다.

---

## 4. ④ Hypothesis 상세

### 4-1. 진입점 — build_hypotheses

LangGraph가 그룹당 1회 호출하는 함수. 내부의 다른 함수들은 전부 여기서 호출된다. 실행 순서:

```
build_hypotheses(state, group_id, mcp)
 ├ 1. step 폴백      _with_step_fallback — step=None 후보를 mapping.process로 보충 (D14)
 ├ 2. 시간창 준비     _group_time_range(전 로트 합집합, D15) · defect_ts · _maintenance_range(D13)
 ├ 3. tier 분기
 │    ├ 자동        → investigate_group (LLM 에이전트, step 배치)     ← §4-2
 │    └ 반자동·근거없음 → 결정론 루프 (unit 캐싱으로 중복 호출 방지)
 ├ 4. 원순서 조립     두 갈래 결과를 KG rank 순서로 한 리스트에
 ├ 5. 클러스터 주석   _annotate_clusters — cluster_id / is_primary (순서·행수 불변)
 ├ 6. fab 재랭킹     _rank_hypotheses — 여기서 최종 표시 순서 확정    ← §4-4
 └ 7. defect_ts 스탬프 → {"hypotheses": {group_id: [...]}}
```

### 4-2. investigate_group — 자동 tier의 LLM 에이전트 경로

자동 tier 후보 전부를 담당한다. **후보 1개씩이 아니라 step 단위 배치**로 처리한다:

```
자동 후보들을 step별로 묶음 (CMP 후보끼리, DEPO 후보끼리…)
 └ 배치(step)마다:
    1. pre-pass(결정론): commonality → 의심 장비(suspect) 확정 + normal_ratio 수집
       └ suspect를 특정하지 못하면 → 배치 전체 미조사 폴백 (investigated=False)
    2. 에이전트 1루프(create_react_agent, temp=0):
       프롬프트에 확정 사실(suspect·step·time_range·후보 목록)을 코드가 주입하고
       "query_telemetry를 한 번만, params 리스트로 전부, max_points=500×param수" 지시
    3. _to_hypotheses_batch(결정론): 도구 반환의 series를 param별로 분리해
       후보마다 자기 param 데이터로 drift·방향·일치를 판정 (옵션 A)
```

**배치로 처리하는 이유**: cause 수십 개가 같은 param을 가리킨다. 후보마다 telemetry를 1콜씩
호출하면 Center 244건에서 타임아웃이 발생했다(실측). 배치는 장비당 telemetry **1콜**로 여러
후보를 동시 판정한다 — 실측으로 후보 6개·step 2종에서 telemetry 5콜→2콜.

**에이전트를 쓰는 이유**: 현재 데이터 규모에서는 호출할 도구가 대체로 1개로 정해지지만,
도구 선택·순서·중단을 관측 결과에 따라 조정하는 능력은 tier·도구 종류가 늘어날 때 조건 분기
코드로는 유지하기 어려운 부분이다(도구 9종이 전부 노출돼 있음). 반면 오판 위험이 큰 수치
판정은 옵션 A로 결정론에 고정했다 — 도구 오케스트레이션은 LLM에 위임하고, 판정은 위임하지
않는 것이 원칙이다.

**폭주 방지**: 배치당 스텝 상한 `AGENT_RECURSION_LIMIT=8` (정상 경로는 agent→tools→agent
3스텝). 초과 시 해당 배치는 미조사 폴백으로 처리된다 — pre-pass가 채운 값은 보존되고
telemetry 판정만 비게 된다(실제로 조회하지 못했으므로 사실 그대로의 기록).

### 4-3. 방향 대조 — 경쟁 가설의 판별 신호

같은 param에 예상 방향이 정반대인 cause가 공존한다(예: `slurry_flow`에 "과다(high)" vs
"부족(low)"). drift 여부만 보면 둘 다 "이탈함"으로 동일하게 통과해 구분이 불가능하다 —
**방향이 유일한 판별 신호**다.

| telemetry 실측 | 예상 high인 후보 | 예상 low인 후보 |
|---|---|---|
| 위로 이탈 (high) | 지지 ✅ | **반박** ❌ |
| 아래로 이탈 (low) | **반박** ❌ | 지지 ✅ |

구현: `_drift_direction`(실측 방향 — hi만 초과=high, lo만 미달=low, 정상/양방향 혼재=None) +
`_direction_match`(실측↔KG 예상 비교 — 어느 한쪽이 None이면 판정하지 않고 None 반환).
판정 가능한 경우에만 값을 내고 불확실하면 None으로 두는 것이 전체 설계의 일관 원칙이다.

### 4-4. fab 재랭킹 — _rank_hypotheses (대표원인이 결정되는 곳)

KG가 준 순위(문헌 근거량 기반)는 조사 순서로만 쓰고, **최종 순위는 fab 증거로 다시 계산한다**.
행 단위가 아니라 클러스터(§3-3) 단위로 정렬하고, 클러스터 내부는 KG 순위를 유지한다:

```
정렬 키 (위가 우선):
 ① 증거 세기 내림차순     drift+방향일치(5) > 방향불명(4) > 방향반박(3) > 정상범위(2) > 정비정황(1) > 무신호(0)
 ② commonality_ratio ↓   인과 필요조건 — 공통률이 높은 장비가 우선 (8/8이 5/8을 이김)
 ③ normal_ratio ↑        반대증거 할인 — 정상 로트 비율이 높은 장비는 뒤로
 ④ KG rank               완전 동률일 때만 문헌 순위가 타이브레이커
```

②는 SC-CENTER-01 평가에서 정답(공통률 1.0)과 오답(0.625)을 가른 결정 요인이었다(§7).
②③④ 전부 **이미 수집하고 있던 신호를 랭킹에 연결한 것**이지 특정 시나리오에 맞춘 튜닝이
아니다.

### 4-5. 시간창 설계 — 지지 증거와 반박 증거는 조회 구간이 다르다 (D13·D15)

- **telemetry 창** = 그룹 **전체 로트**의 공정 구간 합집합(D15). 처음엔 첫 로트 구간만
  사용했는데, 시나리오의 의도적 telemetry 공백(coverage_gap)과 구간이 겹쳐 원인 장비의
  시계열이 0포인트가 되는 문제가 실측돼 합집합으로 변경했다.
- **maintenance 창** = 공정 시작 ~ **결함 이후 +14일**(D13, 비대칭 연장). 이유: "그 정비는
  결함 이후였다"는 시간역전 반박 재료는 결함 이후 구간을 조회해야만 수집된다. 결함 이전만
  조회하면 "정비 기록 없음(→보류 사유)"과 "정비가 결함 이후에 있음(→기각 사유)"이 둘 다
  "조회 결과 0건"으로 나타나 구분할 수 없다. **telemetry 창은 연장하지 않는다** — 결함
  이후의 drift는 원인일 수 없는데 창을 넓히면 무관한 이탈값이 지지 증거로 잘못 수집된다.

### 4-6. investigated 마커 — 실제 조사 여부의 기록

각 Hypothesis에 `investigated: bool`이 실린다. 판별 기준은 LLM 서술이 아니라 **도구 반환의
사실**(서버가 요청받은 param마다 normal_ranges 엔트리를 생성하는 성질)이다. 에이전트가
param을 누락하면 그 후보만 False, 도구를 아예 호출하지 않으면 전원 False가 된다 — 어떤
경우에도 조사하지 않은 후보가 "조사됨"으로 기록되는 경로가 없다. False인 행은 ⑤에서
보류(judge_unknown)로 분류된다.

---

## 5. ⑤ Critic 상세

### 5-1. 규칙 체인 — 먼저 걸리는 규칙이 판정을 결정한다

가설 1건씩 아래 순서로 검사한다. 전부 결정론이며 fab 재조회는 없다(firewall):

```
가설 1건
 ↓ ① 시간정합     maintenance_ts > defect_ts (정비가 결함보다 늦음)?  → P2 rejected   ← 함정 기각 지점
 ↓ ② 반대근거     normal_ratio 수집 안 됨(None)?                     → P3 rejected
 ↓ ③ faithfulness 자동 tier & 조사됐는데 drift 판정이 비어 있음?       → P4 rejected
 ↓ ④ KG메커니즘   tier가 근거없음?                                   → P5 judge_unknown
 ↓ ⑤ 미조사       investigated=False?                               → judge_unknown (보류)
 ↓
 accepted
```

결과는 3분류: **accepted**(증거로 지지됨) / **rejected**(증거로 반박됨 — P2·P3·P4) /
**judge_unknown**(조사 안 됐거나 판정 불가 — P5·미조사). 반박과 판정 불가를 구분하는 것이
핵심이다.

### 5-2. 규칙 순서의 의미 — 반박 판정이 보류보다 우선

미조사 검사(⑤)가 체인 **맨 뒤**에 있는 것이 의도된 설계다: 반자동 후보는 항상 미조사지만,
`maintenance_ts`는 결정론(pre-pass)이 수집한 사실이므로 미조사 여부와 무관하게 유효하다.
함정 장비의 시간역전(①)은 보류가 아니라 명시 기각으로 먼저 판정돼야 한다 — 미조사를 먼저
검사하는 설계였다면 반자동 함정 후보가 전부 보류로 빠져 시간역전 규칙이 적용될 기회가
없었을 것이다.

### 5-3. 고정 사유 토큰과 verdict 매핑

⑤는 기각/보류 행에 고정 토큰을 부여하고(P2_TIME_ORDER · P3_NO_COUNTER_EVIDENCE ·
P4_FAITHFULNESS · P5_NO_KG_MECHANISM · SEMI_AUTO_PENDING · NOT_INVESTIGATED),
⑥ response가 토큰만 보고 프론트 verdict 3값(accepted/rejected/judge_unknown)으로 매핑한다.
자연어 사유 문구는 매칭하지 않으므로 문구를 수정해도 프론트 표시가 깨지지 않는다.

---

## 6. 작업 히스토리 — 구현 순서

수직 슬라이스 방식으로 진행했다: 최소 범위의 end-to-end 경로를 먼저 구현해 검증하고,
그 위에 기능을 단계적으로 추가했다. 매 스텝마다 단위 테스트 + 실LLM/MCP 스모크로 검증.

### 슬라이스1 (0721) — 최소 경로 검증
자동 tier 후보 **1개**만 에이전트로 end-to-end. "에이전트 경로가 실행되고, evidence를 도구
반환에서 재구성(옵션 A)할 수 있는가"만 확인.

### 슬라이스2 (0722~23) — 본체 6단계

| 스텝 | 내용 | 핵심 |
|---|---|---|
| S2-1 | 방향 대조 | `_drift_direction`/`_direction_match` — 경쟁 가설 판별 신호 도입 |
| S2-2 | 배치 telemetry + investigate_group | 후보 단위 → step 배치 1콜. 슬라이스1 코드는 배치에 흡수 |
| S2-3 | 클러스터 주석 | `cluster_id`(unit+direction) + `is_primary`(cause 대표 행) |
| S2-4 | fab 재랭킹 | `_rank_hypotheses` — 최종 순서를 fab 증거로 결정. D1 개정 동반 |
| S2-5 | 스텝 상한 | `AGENT_RECURSION_LIMIT=8` + 초과 시 미조사 폴백 |
| S2-6 | ⑤ investigated 소비 | 미조사 보류 분기 도입 + 미조사 행의 P4 오기각 제거. ⑤ 첫 전용 테스트 8개 |

### 슬라이스3 (0723) — E2E 평가와 평가 기반 수정 4건

ground truth 시나리오(`secsgem-mcp/datasets/ground_truth/`, 11개)로 ③→④→⑤→⑥ 전체를
처음 실행해 정답과 대조했다. **1차 결과는 오답이었고, 원인을 추적해 결함 4개를 특정·수정했다**:

| 수정 | 발견된 결함 | 내용 |
|---|---|---|
| 1 (D13) | 함정 PM이 조회 창 밖 → 시간역전 규칙 미적용 | maintenance 창을 결함 후 +14d까지 비대칭 연장 |
| 2-b (D14) | step=None 후보 161건이 전부 함정 장비로 집중 → 정답이 잘못된 장비에서 검증돼 기각 | mapping.process로 step 폴백 (KG 측 근본 수정은 #34로 반영됨) |
| 3 (D15) | 첫 로트만의 시간창이 telemetry 공백과 겹침 → 원인 시계열 0포인트 | 전 로트 합집합 창 |
| 4 (D16) | 증거 세기 동률에서 오답(공통률 0.625)이 정답(1.0)보다 상위 | 랭킹 2순위 키 = commonality_ratio |

4건 전부 일반 원칙(시간 비대칭 조회 / KG 자기 정보 보충 / 커버리지 강건성 / 인과 필요조건)에서
유도했고, 적용 전에 fab.db 직접 조회로 근거를 확인했다 — 특정 시나리오에 맞춘 조정이 아니다.

---

## 7. 테스트 결과

### 7-1. 단위 테스트 — 37건 통과

`backend/tests/test_hypothesis_agent.py`(29) + `test_critic.py`(8). 배치 판정 분배·방향
대조·클러스터·재랭킹 4단 키·스텝 상한 폴백·시간창·⑤ 규칙 체인 전체를 고정. fab.db 없이
실행된다(`pytest -q -m "not data"` — CI와 동일 조건).

### 7-2. E2E 시나리오 평가 — SC-CENTER-01 (1/11 완료)

시나리오: Center 결함 로트 8개. 정답 `clean_nozzle_clog`(CLEAN-01 flow_rate 하강 드리프트),
함정 LITHO-01(전 로트 통과 + 결함 6일 뒤 PM = 시간역전).

**최종 결과 (수정 4건 적용 후):**

| 지표 | 1차(수정 전) | 최종(수정 후) |
|---|---|---|
| 대표원인 top-1 | ❌ DEPO 오답 | ✅ **clean_nozzle_clog** |
| 정답 순위/판정 | 193위 · rejected | **0위 · accepted** (drift low + 방향일치 + 공통률 1.0) |
| 함정 시간역전 기각 | 0건 | **44건 P2 명시 기각** |
| 함정이 상위 12위 내 | 다수 | **0건** |
| ⑤ firewall (재조회) | 0회 ✅ | 0회 ✅ 유지 |

- 평가 대조 키는 `matched_cause`(kg cause→시뮬레이터 어휘 변환표, kg_rca mapping 블록) —
  cause 문자열 직접 비교 시 표기 차이로 0%가 나오는 문제를 해결. 빌드타임 어휘 대응표라
  시나리오 정답의 사전 노출이 아니다.
- 평가 스크립트는 ⓪①②를 우회하고 ground truth의 lot_ids·pattern을 직접 주입해 ③~⑥만
  실행한다 — vlm 하드코딩과 무관하게 Edge-Ring/Scratch 시나리오도 평가 가능한 구조.
- **나머지 10개 시나리오(Center 2·3, Edge-Ring 3, Scratch 3, Unmatched 2)는 미실행** —
  수정 4건이 다른 시나리오에서도 유효한지 검증하는 것이 다음 단계다.

---

## 8. 남은 과제 / 팀 논의 필요 항목

| # | 항목 | 성격 |
|---|---|---|
| 1 | **시나리오 확장** (10개 잔여) + 단일경로 baseline 비교(기획안 §10 핵심 실험) | 다음 작업 |
| 2 | **drift=False(범위 내 정상)도 accepted되는 판정 기준** — 현 설계 문언대로지만 채택 수가 많음(Center 51건). 반대증거 게이트(normal_ratio 임계, D6의 50%와 정렬?) 검토 | **팀 안건** |
| 3 | **반자동 실제 조사 경로** — 지금은 전원 judge_unknown 보류. Maintenance 텍스트 판정 주체(사람 판정 API §4-2 vs LLM 의미매칭) 미정 | **팀 안건** |
| 4 | **LiveKGClient에 matched_cause/mapped_process 동일 필드 추가** — 라이브 순회 경로에는 mapping 블록이 없어 매칭을 조회 시점에 계산해야 함(설계 필요). PR #36 머지 후 별도 이슈 | 후속 이슈 |
| 5 | KG step 오연결(정답 cause의 DEPO 행) — 문헌 어휘↔fab 어휘 정합 문제, `MCP_KG_정합성검토.md` 트랙 | **팀 안건** |
| 6 | eval/metrics.py 지표 함수 수리(현재 스텁) + test_e2e_samples.py 연결 | 다음 작업 |

---

## 부록 A. 용어 요약

| 용어 | 뜻 |
|---|---|
| suspect | commonality 분석이 지목한 의심 장비(equipment_id) |
| pre-pass | 에이전트 실행 전에 결정론 코드가 수행하는 공통 조회(commonality→suspect, normal_ratio) |
| 옵션 A | 수치(evidence)는 도구 반환에서 코드가 재구성, LLM은 서술(rationale)만 담당 |
| firewall | ⑤가 fab 재조회 없이 ④의 evidence만 읽는 계약 |
| unit / 클러스터 | (step, evidence_label, evidence) / unit+direction — fab 데이터로 구분 가능한 최소 단위 |
| investigated | ④가 실제 조사했는지 여부. False → ⑤에서 judge_unknown 보류 |
| judge_unknown | 조사 안 됐거나 판정 불가 = 판단 보류 (기각 아님) |
| prior | fab 조회 전의 문헌 근거량 기반 순위(KG rank) — 조사 순서와 동률 타이브레이커로만 사용 |
| 함정(trap) | 상관관계는 높지만 원인이 아닌 장비 — ground truth `traps_to_reject`에 명시, 시나리오가 의도적으로 포함 |

## 부록 B. 코드 진입점 맵

| 찾는 것 | 위치 |
|---|---|
| ④ 전체 흐름 | `hypothesis.py` `build_hypotheses` |
| 에이전트 배치 조사 | `investigate_group` → `_build_group_prompt` → `_to_hypotheses_batch` |
| 방향 대조 | `_drift_direction` / `_direction_match` |
| 클러스터/대표 행 | `_cluster_key` / `_evidence_strength` / `_annotate_clusters` |
| 재랭킹 4단 키 | `_rank_hypotheses` |
| 시간창 | `_group_time_range` / `_maintenance_range` |
| step 폴백 | `_with_step_fallback` |
| ⑤ 규칙 체인 | `critic.py` `review_hypotheses` + `_check_*` 4개 |
| verdict 매핑 | `response.py` `_JUDGE_UNKNOWN_TOKENS` |
| 정책 결정 이력 | `docs/BACKEND_DECISIONS.md` D1·D8·D13~D16 |
