# SECS/GEM MCP 문서 ↔ KG 출력 정합성 검토

> 갱신: 2026-07-13 (MCP 문서 07-13 12:22 개정판 반영)
> 대조 기준:
> - `SECS GEM MCP 문서_v0 1.md` (2026-07-13 12:22 — §5 E2E 시나리오 3종·§6 Agent 결합 신설,
>   매핑표에서 Center-세정 노즐 행 및 Edge-bead removal 취소선 삭제)
> - `outputs/hypotheses.json` (schema **v2.4**, 가설 642건 — CLEAN·Edge-Ring-CMP 문서 반영) + `KG_output_명세.md`
> - `mapping_table.yaml` (원본 유지 — KG 매칭 키워드는 KG 모듈 소유)

---

## 1. 미해소 항목 (우선순위 순)

| # | 항목 | 내용 · 필요한 조치 |
|---|---|---|
| X3 | **가설 수 × 루프 비용** | 가설 368건을 "후보 원인마다" 체인 실행하면 툴 호출 폭주 (E3/E4의 정신에 반함). 고유 검증 단위는 훨씬 적음 — Center 88 / Edge-Ring 31 / Scratch 16. **개정판에서 구체화**: §5 시나리오의 KG 질의는 **"후보 원인 3종"** 형태를 기대 (5.x 2단계), §6 Agent 결합도 "후보 원인 공정 확보" 수준. **조치**: `hypotheses.json`에 시나리오용 요약 후보 뷰(`candidates[]` — mapping_table 항목 단위) + 상세 `checks[]` 그룹 뷰 추가 (→ Q3) |
| X4 | **Alarm evidence 부재** | 알람은 KG에 노드/경로가 없어 B3 판정 ③("KG에 신호→결함 경로 있는가")에서 **모든 알람이 자동으로 교란 신호 판정**. **개정판 5.1이 이 위험을 실증**: 교란 알람 `HEATER_TEMP_DEV`는 KG 부재로 배제(의도대로)되지만, 같은 논리로 **관련 알람 `FLOW_LOW`도 배제될 것** — 시나리오는 이를 A4 보조 증거로 기대함. **조치**: `Alarm` evidence 노드(`fab_table='alarm'`, `[반자동]`) 추가 또는 B3 규칙 완화 (→ Q2) |
| N3 | **VLM 형상 분류 모듈 미구현** | VLM은 형상을 **자유 서술**로 출력 — 미지 패턴 진입(A0 분기 2)에는 서술 → shape/zone enum 분류기가 전제. 문서 추출(5번)과 같은 분류 계약이라 프롬프트 재사용 가능. **조치**: 모듈 소유·위치 결정 (→ Q5) |
| X7 | **Maintenance id ↔ T7 `parts` 매칭 불가** | `inspect_whether_residual_copper_...` 같은 id는 T7 반환의 "교체 부품" 텍스트와 자동 대조 불가. **조치**: Maintenance dedup 시 `parts_keyword` 정규화 속성 추가 |
| N1 | **재적재 간 앵커 비결정성** | 앵커 보강 패스로 실행 내 합집합은 확보했으나, **전체 재적재 간** 엣지 구성이 변동 (예: `Edge-Ring→CLEAN`이 실행에 따라 있다가 없다가). **조치(운영 규칙)**: agent 연동 테스트는 그래프 스냅샷 고정 + `meta.generated_at` 신선도 검사 |
| N2 | **`[근거없음]`이 상위 rank에 올 수 있음** | 순위가 tier 무관(의도된 설계 — 그럴듯함 ≠ 확인 용이성). **조치(agent 규칙)**: rank 순회가 아니라 **tier로 실행 계획을 세우고 rank는 tier 내 순서로** 사용 |
| X6잔여 | **KG 후보 분류 단계가 MCP 문서에 없음** | direct 가설(step=null)과 `[근거없음]` 가설의 처리 절차가 시나리오에 미명문화. **조치(문서 측)**: A0~A1 사이에 분류 단계 추가 — step 보유→표준 루프 / direct→step 미지정 T3 / 근거없음→evidence table 참고 정보 |

## 2. 결정 필요 사항

| # | 질문 | 연관 |
|---|---|---|
| Q3 | agent 루프 단위 — 가설별 vs 고유 검증 단위(`step`×`evidence`)별. `checks[]` 뷰를 KG가 제공할지 | X3 |
| Q2 | `Alarm` evidence 노드 추가 vs B3 규칙 완화 | X4 |
| Q5 | VLM 형상 서술 → enum 분류 모듈의 소유와 위치 (KG측 유틸 vs agent 내부) | N3 |
| Q6 | 실시간 단건 질의 모드(패턴 1건 입력) 필요 여부 — 현재는 배치 json에서 `questions[].pattern` 섹션 참조 | — |

## 3. 권장 착수 순서

1. Q3 `candidates[]`(시나리오용 후보 요약 뷰) + `checks[]` 그룹 뷰 — agent 루프 비용 확정 (STATUS ②와 병행)
2. Q2 Alarm evidence — 5.1이 관련 알람(`FLOW_LOW`)의 KG 연결을 실제로 요구
3. X7 `parts_keyword` — Maintenance dedup(P3)과 한 묶음
4. X6잔여(MCP 문서 측 — KG 후보 분류 단계 명문화) / Q5 VLM 분류기

---

## 4. 완화·운영 방침 확정 항목 (기록)

| # | 항목 | 확정된 방침 |
|---|---|---|
| X1 | **파라미터 어휘 불일치 — 출력 처리 방침** (⚠ 어휘 확장 자체는 X1E로 재격상됨) | (a) 어휘 밖 신호는 `[근거없음]` 유지 — 자동/반자동으로 새지 않음. (b) '지식 없음'이 아니라 '계측 없음'이므로 **C2(부분 커버리지)로 처리** — agent는 `verification.unverifiable_signals` 또는 `mapping.param_in_fab_vocab=false`를 evidence table "부족한 데이터"란에 기록. (c) 버려지던 신호명 **보존** — `Cause.unverifiable_signals` → 출력 (실측: Cause 18개, 가설 20건). 이 방침은 어휘가 확장돼도 잔여 밖 신호에 계속 적용됨 |
| X1E | **E2E 정답 신호 fab 어휘 (Q1 결정 반영, 07-13)** | **대부분 해소.** ① `pad_usage_hours`는 fab에 실재(git pull 갭) → `seeds/parameters.json`(21종)·`fab.md` CMP 행·5번 Literal에 추가, `cmp_pad_wear` 매핑 가설이 `[자동]`(hint A3) 승격 실측. ② `shower_flow`/`pressure`는 `chamber_pressure` 별칭으로 처리 — 5.1 Center 정답 검증 가능. ③ **잔여(해결 불가)**: `motor_torque`·`slurry_particle`은 제거 결정(고려 불가 변수) — 5.3의 슬러리 대입자 변별 신호 절반이 계측 불가로 남음(slurry_flow 반쪽만 가능). 해당 신호는 X1 방침대로 [근거없음]+C2 처리. MCP 문서 5.1/5.3의 시나리오 본문 표기(shower_flow, motor_torque, slurry_particle 언급) 정리는 문서 소유자 몫 |
| X2 | **클래스×원인 매핑표 커버리지** | **해소 (07-13).** 매핑표(취소선 제외 8항목)의 모든 패턴→공정 조합이 KG에 존재 — 누락 0. 마지막 공백이던 `Edge-Ring→CMP`는 `edgering-cmp.txt`(Xie & Boning, MIT/MRS 2005 + 큐레이션 메타데이터 "Related Defect: Edge Ring")로 확보. 근거 강도 주의: 본문은 기전(edge over-polish→주변부 불균일)까지만 말하고 패턴 연결은 메타데이터 큐레이션임. retaining ring(부품)↔ring(패턴) 어휘 함정은 프롬프트 가드로 차단 확인. CLEAN 계열은 `...TABLE+CLEAN.md`로 해소 (재구성 표, provenance 주의 명기). ※ 07-13 N4 결정으로 Center-세정 행이 복원됐으나(9항목), 해당 행은 문헌 무근거 큐레이션 전용(함정 후보)으로 합의돼 문헌 커버리지 잣대에서 제외 — "누락 0"은 문헌 기대 8항목 기준으로 유지 |
| X5 | **시나리오 체인 라우팅** | **해소 (07-13).** 출력에 `scenario_hint` 필드 신설 — Parameter→A3, Recipe→A5, Maintenance→`consumable`(추출 시 LLM 판단, 노드 속성)이면 A6·아니면 A2, 근거없음→null. 소급 노드는 키워드 휴리스틱(pad/brush/slurry/filter/conditioner) 임시 판정, 재추출 시 정식 값으로 대체. 실측 분포: A2 209 / A3 97 / A5 32 / A6 44 / null 260 |
| X8 | **표기 규약** | **해소 (07-13, KG측이 문서 수정).** MCP 문서의 식별자 표기를 코드에 정렬 — `step=증착/식각/세정` → `step=DEPO/ETCH/CLEAN`(11건), `params=[RF_power]` → `[rf_power]`. 산문(한국어 서술)은 유지. T8의 `metric=수율` 같은 툴 자체 계약값은 X8 범위 밖으로 보존 |
| N4 | **매핑표 취소선 ↔ yaml 정합 (07-13 의사결정)** | **해소.** 취소선 사유 = "형상 서술 RAG 문서를 못 찾음". KG측 무이상 확인 후 **취소선 해제, 행 유지**로 결정 — 문서와 yaml 재정렬. 역할 분담 합의: Center-세정은 **문헌 무근거 큐레이션 항목**(5.1 함정 후보 H3 용도)으로, 후보 공급은 문헌 그래프가 아니라 `mapping_table.yaml`→`candidates[]` 뷰(Q3)가 담당. KG 그래프의 Center→CLEAN 경로는 0건이며 문헌이 생기기 전까지 0건이 정상 |
| X9 | 수치 prior 출처 | 정본 = `mapping_table.yaml`의 `prob`. KG는 `mapping.prob`로 노출만 |
| X10 | KG 질의 인터페이스 | 계약 = `hypotheses.json` + `KG_output_명세.md`. agent는 `questions[].pattern`으로 자기 섹션을 읽음. 잔여는 Q6 |

## 5. 정합 확인 (충돌 없음)

| # | 항목 | 근거 |
|---|---|---|
| OK-1 | 3클래스 명칭 일치 — VLM = MCP(A0) = KG `DefectPattern.id` (`Center`/`Scratch`/`Edge-Ring`) | 시드 계약 |
| OK-2 | T5 호출 인자 공급 — `verification.fab_table` + `path.evidence` + `direction` (E3 "전체 덤프 금지" 충족) | 출력 구조 |
| OK-3 | D3 Faithfulness 요건 — `sentence` + `path` + `provenance`(경로 전체 chunk_ids) | 출력 구조 |
| OK-4 | E2 원칙 — KG 출력에 인스턴스 주장 없음. 문헌 근거(provenance)와 큐레이션 근거(`mapping`) 구분 | 설계 |
| OK-5 | C4 스코프 일치 — 후공정·RTP 등은 `[근거없음]` 격리 | 검증 등급 |
| OK-6 | B1(negative evidence)은 KG와 독립 — 출력이 방해하지 않음 | — |
| OK-7 | Scratch 원인 실제 겹침 — 패드 마모·슬러리 대입자가 문서 매핑표와 KG 양쪽에 존재 | 교과서 CMP 표 |
| OK-8 | MCP 3.1 매핑표와 직접 연동 — `mapping_table.yaml`을 오버레이로 소비, `prob`·`citation`·신호가 가설에 실림 | 매핑 오버레이 |
| OK-9 | 순위가 측정값 기반 — `(occurrence_prior, evidence_docs, evidence_chunks)`. "그럴듯한 순서"(rank)와 "확인 방법"(tier)이 독립 | v2.4 출력 |
| OK-10 | 미지 패턴 대응 기반 — 형상 관측을 shape/zone enum으로 분류하면 `SpatialSignature`부터 순회 가능 (A0 분기 2 지원) | v2.4 형상 레이어 |
| OK-11 | **Edge-bead removal 취소선 삭제** — KG가 스코프 밖으로 버려온 판단과 문서가 일치하게 됨 | 개정판 §3.1 |
| OK-12 | **Center-세정 행의 역할 합의** — 취소선 해제로 복원하되 문헌 무근거 큐레이션 항목(함정 후보)으로 위치 확정. yaml과 재정렬 (N4 해소) | 07-13 결정 |
| OK-13 | **§6 Agent 결합 1단계와 부합** — "KG/문헌에서 후보 원인 공정 확보"는 `hypotheses.json`의 `pattern`→`path.step`/`cause`로 충족 | 개정판 §6 |
