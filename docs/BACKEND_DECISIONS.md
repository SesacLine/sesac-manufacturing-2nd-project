# 백엔드 잠정 결정 기록 (AGENT_GUIDE §1-a "잠정+기록" 등급)

> 계약(`docs/API_명세서_v1.0.md`)이 규정하지 않는 **내부 구현 정책**을 여기 남긴다.
> 계약과 어긋나 보이면 계약이 이긴다. 각 항목은 팀 검토 후 확정하거나 뒤집을 수 있다.
> 작성: 2026-07-20 API 8종 + 프론트 구현 세션.

| # | 결정 | 근거 / 되돌릴 조건 |
|---|---|---|
| D1 | **대표 원인(`hypotheses[0]`) = accepted 중 ④ fab 재랭킹 최상위** — ④ `hypothesis.py`의 `_rank_hypotheses`가 클러스터(unit+direction) 단위로 증거 세기 내림차순(동률: commonality_ratio 내림차순 → normal_ratio 오름차순 → kg rank) 정렬해 내보내고, ⑤ Critic·⑥ response는 순서를 보존만 한다(`accepted[0]` = ④의 1위). kg_rca 순위(`rank` = candidates 배열 순서)는 조사 순서·동률 타이브레이커로만 쓴다. 비채택 후보는 accepted 뒤에 같은 순서로 잇고, 정렬 확정 후 `h{n}` 부여 | 명세 §4-1 미결정 — 07-23 개정(S2-4·D16): "문헌 순위(prior)는 조사 순서, 최종 순위는 fab 증거"로 재정의. 정렬 키 상세는 D16. 팀이 다른 규칙을 정하면 `_rank_hypotheses`만 교체(response.py는 순서 보존이라 무변경) |
| D2 | **첫 배치의 누적 스코프 = 데이터축 처음(EPOCH 2026-01-01)부터 전부**. 커서는 (직전 배치가 처리한 마지막 날짜, exclusive) → 데이터축 `max(ts)` (inclusive)로 전진 | 명세 §2.3 "직전 배치 이후 누적" — 직전 배치가 없으면 전체가 누적분. 구 `_FIRST_CURSOR_DATE=2026-03-04` 하드코딩은 폐기 |
| D3 | **`low_yield_eq` 선정 기준 = 7일 창 내 평균 수율 최저 장비 1개** (`backend/api/yield_summary.py`) | 명세 §2.1은 "장비별 yield 최저 1개 선정"만 규정, 창 기준은 미규정. 일별 최저(매일 다른 장비)로 바꾸려면 이 파일만 수정 |
| D4 | **같은 정규화 패턴으로 접히는 그룹이 여럿이면 unmapped끼리 로트 병합해 1건 저장** (`batch_runner._persist_results`) | `analysis_id`가 패턴+배치 단위 유니크(§3)라 비매핑 결함 여러 종(Donut·Loc…→전부 Unknown)이 충돌하는 것 방지. VLM이 실제 다패턴을 내기 시작하면 grouper 단계에서 정규화하는 방안 재검토 |
| D5 | **`chamber_id`는 전부 null** (commonality rows·suspect) | MCP `run_commonality_analysis`가 장비/챔버를 **별개 카운터**로 집계해 장비별 챔버를 특정할 수 없음. 장비-챔버 조인 집계가 MCP에 생기면 해소 |
| D6 | **normal_ratio caption의 지지/약화 판정 임계 = 정상비율 50%** (`assembler.py`) | 명세 §4-3(P3 반박 임계) 미결정 — caption 문구 생성에만 쓰는 표시용 잠정값. Critic 기각 임계가 확정되면 같은 값으로 정렬 |
| D7 | **telemetry `unit` = 빈 문자열** | fab.db/`fab_model.yaml`에 단위 메타가 없음. §2.7 계약상 non-null 문자열이면 되므로 ""로 충족. 시뮬레이터에 단위가 추가되면 채움 |
| D8 | **미조사 판정 = `investigated` 마커 기반 judge_unknown 보류**(S2-6, `critic.py`) — 반자동은 조사경로 부재로 항상 `SEMI_AUTO_PENDING`, 자동 tier 조사실패(suspect 부재·에이전트 폭주) 폴백은 `NOT_INVESTIGATED`. 기각(rejected)이 아니라 판단보류(judge_unknown) | 명세 §2.5 🔲 "Critic이 자동 기각"을 "보류"로 이행(환각억제: 안 봤으면 판정 안 함). 4규칙 위반(P2~P5)이 미조사보다 우선. §4-2 사람 판정/반자동 조사 경로 생기면 `SEMI_AUTO_PENDING` 제거. 구 `SEMI_AUTO_AUTO_REJECT`(자동 기각)는 폐기 |
| D9 | **`GET /lots/{id}/wafers`의 존재 판정 = 배치가 판독한 로트(wafer_reading 저장분)** — 미판독 lot_id는 404 | §2.6이 "판독 웨이퍼 목록"이므로 판독분이 원천. fab.db 전체 로트 조회로 넓히려면 정답 누출(라벨) 우회 경로 재검토 필요 |
| D10 | **가설 카드 수 무제한** — 후보 전수(수백 건 가능)를 verdict 포함 그대로 §2.5에 노출 | 계약에 상한 없음 + "no silent caps". 응답이 무거우면 계약에 페이지네이션을 추가하는 쪽으로(명세 개정 필요) |
| D11 | **telemetry `t0` = 항상 null** | 이상 시작 추정 로직(변화점 탐지 `detect_change_points`)이 파이프라인 미사용. §2.7 계약상 Nullable이라 충족. 변화점 연동 시 채움 |
| D12 | **logs의 그룹 컨텍스트 없음** — MCP 트레이스는 도구명+인자 요약만 (`batch_runner.LoggingMCP`) | 노드 내부를 건드리지 않는 위임 프록시 방식이라 그룹(패턴) 라벨을 모름. 메시지에 [패턴] 프리픽스가 필요해지면 hypothesis.py에 로그 훅 추가 필요 |

> **2026-07-23 추가 (D13~D16, 슬라이스3 S3 E2E 평가에서 유도).** SC-CENTER-01 ground truth로 ③~⑥
> 관통 검증 중 발견한 4개 결함의 처방. 전부 원리 유도 + fab.db 실측 근거 확보 후 적용(시나리오
> 과적합 아님). 상세 실측: `personalspace_rca/0723 work/hypo_critic_test_result.md`.

| # | 결정 | 근거 / 되돌릴 조건 |
|---|---|---|
| D13 | **maintenance 조회 창은 telemetry와 비대칭 — 결함 이후 +14일까지**(`_maintenance_range`, `MAINT_LOOKAHEAD_DAYS=14`) | 시간역전(P2) 반박 재료(결함 뒤 PM)를 수집하려면 필요. 원인 신호(telemetry)는 결함 이전이 맞으므로 그 창은 안 넓힘. SC-CENTER-01 실측: 함정 PM(defect+6d)이 공정구간 창 밖이라 P2 무발화였음. 14는 캘리브레이션값(함정 6d의 2배·PM주기 상한 커버), 시나리오 확장 시 재조정 |
| D14 | **step=None 후보에 mapping.process를 step 폴백**(`_with_step_fallback`) | 문헌직결(direct) 가설은 KG가 step=NULL로 내는데 그대로 commonality 돌리면 전체공정 최다통과 장비(함정 포함)로 쏠려 정답이 엉뚱한 장비에서 검증→P4 기각. mapping.process(빌드타임 공정 정규화)로 빈칸만 보충, path.step 있으면 불가침. 근본 교정은 kg_rca 6번(`kg_step보충_제안.md` 전달됨) — 반영되면 폴백 자연 무동작 |
| D15 | **그룹 검증 시간창 = 전체 로트 min(ts_in)~max(ts_out) 합집합**(`_group_time_range`) | 이전엔 대표(첫 로트) 구간만 썼는데 SC-CENTER-01 실측에서 첫 로트 창이 시나리오 telemetry 공백(coverage_gap)과 겹쳐 원인 시계열 0포인트→정답 P4 사망. 로트가 며칠 흩어져 지나가므로 합집합이 그룹 창. 비용: get_lot_history 그룹당 1콜→N콜(수용) |
| D16 | **재랭킹 2순위 키 = commonality_ratio 내림차순**(`_rank_hypotheses`, D1 정렬키에 반영됨) | 세기 동률에서 "원인 장비라면 결함 로트 전부가 지났어야 한다"는 인과 필요조건으로 가른다. SC-CENTER-01 실측: 정답 CLEAN-01(8/8) vs 오답 DEPO-02(5/8) — 이 키로 top-1 달성. 이미 수집 중이던 신호(commonality analysis, 기획안 "모든 가설 공통 호출")의 랭킹 연결 |
