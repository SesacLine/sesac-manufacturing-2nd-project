# KG Output (`outputs/hypotheses.json`) 구조 명세

> 생성: `6_ask_graphrag.py` · 스키마 정본: `../docs/KG_schema_v1.4.md` · hypothesis agent 입력용

## 대표 키 역할

- **`tier`** — 이 가설을 *어떻게 확인하느냐*의 분류 (자동/반자동/근거없음). 검증 시나리오 분기용이며 순위와 무관.
- **`scenario_hint`** — MCP 검증 체인 라우팅 (A3/A5/A2/A6/null). evidence 종류 + `Maintenance.consumable`(소모품 여부, 추출 시 LLM 판단)로 계산. agent는 이 키만 보고 체인에 배정하면 된다.
- **`path`** — 그래프에서 이 가설이 지나온 경로의 노드 id들. fab 조인 키(step, evidence)와 그래프 역추적 키(failure_mode, cause)를 담는다.
- **`verification`** — agent가 검증 쿼리를 조립하는 데 필요한 인자: 조회할 fab 테이블과 예상 이탈 방향.
- **`score`** — 순위 성분. 전부 문헌에서 측정한 값이며 LLM 자기평가는 없다.
- **`provenance`** — 이 가설이 어느 문헌 청크에서 왔는지. Critic의 인용 검사(D3)와 사람의 근거 확인용.
- **`provenance.quotes`** — 인과 서술의 원문 스니펫. 그래프를 열지 않고도 근거를 즉시 읽을 수 있게.
- **`mapping`** — 검증 신호가 문헌이 아니라 큐레이션 표(`mapping_table.yaml`)에서 채워졌을 때만 non-null. 근거 출처의 구분선.

## score 계산 메커니즘

```
순위 = (occurrence_prior, evidence_docs, evidence_chunks) 내림차순
       동점이면 cause 이름순으로 고정 (실행마다 순서가 바뀌지 않게)
```

- `occurrence_prior` — 진입 엣지(ARISES_IN/FORMS_IN)에 기록된 문헌의 빈도 서술 해석 (`commonly → high`, `can also → mid`, `rare → low`).
- `evidence_docs` / `evidence_chunks` — **경로 전체**(진입 엣지 + CAUSED_BY + VERIFIED_BY)의 `chunk_ids` 합집합에서 센 서로 다른 문서 수 / 청크 수. 여러 문헌이 교차로 뒷받침할수록 위로 올라간다.
- 검증 등급(tier)과 LLM 자기평가(extraction_confidence)는 **순위에 반영하지 않는다** — 전자는 확인 방법의 분류일 뿐이고, 후자는 측정값이 아니다.

## tier별 검증 시나리오

- **`자동`** — agent가 끝까지: `telemetry`를 `path.evidence`로 조인(T5) → 정상범위 대비 `direction` 이탈 판정 → 채택/기각 (MCP 시나리오 A3).
- **`반자동`** — agent는 조회까지만: `maintenance`(T7) 또는 `lot_history.recipe_id`(T2)를 뽑아 근거로 첨부하고, 채택/기각 판정은 사람이 (A2·A6 / A5).
- **`근거없음`** — fab 연결 자체가 없음: 문헌 서술로만 제시되며 검증 체인에 배정되지 않는다. evidence table의 참고 정보로만 쓴다.
  단, `verification.unverifiable_signals`가 있으면 "지식은 있는데 fab이 계측하지 않는" 경우이므로 C2(부족한 데이터)로 구분해 기록한다.

| 키 | 값 (예시) | 왜 필요한가 |
|---|---|---|
| `meta.generated_at` | `2026-07-13T11:40:02+09:00` | 그래프 재적재 후 낡은 출력을 쓰는 사고 방지 (신선도 검사) |
| `meta.model` | `gpt-5.4-mini` | 추출·합성 품질의 재현 조건 기록 |
| `meta.neo4j_database` | `neo4j` | 어느 그래프 스냅샷에서 나왔는지 |
| `meta.top_k` | `null` | 상한 여부 — `null`이면 전건 출력 (잘린 목록인지 판별) |
| `meta.tier_legend` | 등급별 설명 | 등급 의미를 소비 측이 재해석하지 않도록 동봉 |
| `meta.score_note` | 순위 규칙 설명 | 순위 계약의 명시 |
| `questions[].pattern` | `Edge-Ring` | VLM 클래스 출력과 조인하는 키 (A0 진입점) |
| `questions[].counts` | `{total, by_tier}` | agent가 루프 예산·커버리지를 계획하는 요약 |
| `hypotheses[].rank` | `1` | 검증 착수 순서 (문헌 근거 빈도순) |
| `hypotheses[].sentence` | 한국어 가설 문장 | 사람 보고용 · Critic의 faithfulness 대조 대상 |
| `hypotheses[].tier` | `자동` \| `반자동` \| `근거없음` | 검증 시나리오 분기 (agent 판정 / 조회 후 사람 / 검증 불가). **순위와 무관** |
| `hypotheses[].scenario_hint` | `A3` \| `A5` \| `A2` \| `A6` \| `null` | MCP 검증 체인 배정: Parameter→A3, Recipe→A5, Maintenance→consumable이면 A6·아니면 A2, 근거없음→null. 소급 노드(consumable 미저장)는 키워드 휴리스틱 임시 판정 — 재추출 시 노드 속성으로 대체 |
| `path.signature` | `ring@edge` \| `null` | 형상 경유 여부와 통과 시그니처 (경로 종류는 path의 null 패턴으로 판별) |
| `path.step` | `ETCH` \| `null` | T3 commonality의 `step` 옵션 값 · `lot_history.step` 조인 키. `null`이면 문헌 직결. 단 **direct 경로라도 mapping_table 매칭이 되면 그 `process`로 보충된다**(backend가 올바른 공정 장비를 조사하게 — apply_mapping_fill) |
| `path.failure_mode` | `incorrect_etch_rate` | 어떤 고장 모드를 경유했는지 (그래프 역추적 키) |
| `path.cause` | `etching_non_uniformities` | 가설의 본체 — 검증 대상 원인의 그래프 id |
| `path.evidence` | `rf_power` \| `null` | 검증 신호 id. Parameter면 `telemetry.param` 조인 키 |
| `path.evidence_label` | `Parameter` \| `Maintenance` \| `Recipe` \| `None` | 검증 시나리오 라우팅 (A3 / A2·A6 / A5) |
| `verification.fab_table` | `telemetry` \| `maintenance` \| `lot_history` \| `null` | agent가 조회할 fab 테이블 지정 |
| `verification.direction` | `high` \| `low` \| `null` | T5 결과의 이탈 방향 판정 기준 |
| `verification.unverifiable_signals` | `["gas_flow"]` \| `null` | 문헌이 지목했지만 fab 어휘에 없어 붙이지 못한 신호. '지식 없음'이 아니라 '계측 없음' — **C2(부족한 데이터)로 기록**할 것 |
| `score.occurrence_prior` | `high` \| `mid` \| `low` | 문헌상 빈도 서술 (commonly/rare) — 순위 제1성분 |
| `score.evidence_docs` | `3` | 경로 전체를 뒷받침하는 **서로 다른 문서** 수 — 교차 검증 강도 |
| `score.evidence_chunks` | `10` | 경로 전체를 뒷받침하는 근거 청크 수 |
| `provenance.chunk_ids` | `["...#c07", ...]` | 경로 전체(진입 엣지+인과+검증)의 근거 청크 — Critic D3 인용 검사 |
| `provenance.quotes` | 원문 스니펫 | 그래프 조회 없이 근거 원문 즉시 확인 |
| `mapping` | 객체 \| `null` | 검증 신호가 문헌이 아니라 `mapping_table.yaml`에서 왔음을 명시 (`null`이면 순수 문헌 근거) |
| `mapping.matched_cause` | `etch_nonuniformity` | 매칭된 테이블 항목 id — 테이블 측 역추적 키 |
| `mapping.score` | `1.0` | 유사도 매칭 강도 (오매칭 감사용) |
| `mapping.process` | `ETCH` | 테이블이 지정한 공정 (문헌 직결 가설의 공정 힌트) |
| `mapping.prob` | `0.6` | 큐레이션된 수치 prior — 시나리오 배정 확률 |
| `mapping.param` / `mapping.drift` | `rf_power` / `step_up` | 테이블 원본 신호 (drift는 T8 변화점 유형 힌트) |
| `mapping.citation` | `Wang et al., IEEE TSM 2020` | 큐레이션 근거 출처 — 보고서 인용용 |
| `mapping.param_in_fab_vocab` | `true` | fab 어휘 검증 결과 — `false`면 T5 호출 불가(승격 안 됨) |
