# 백엔드 잠정 결정 기록 (AGENT_GUIDE §1-a "잠정+기록" 등급)

> 계약(`docs/API_명세서_v1.0.md`)이 규정하지 않는 **내부 구현 정책**을 여기 남긴다.
> 계약과 어긋나 보이면 계약이 이긴다. 각 항목은 팀 검토 후 확정하거나 뒤집을 수 있다.
> 작성: 2026-07-20 API 8종 + 프론트 구현 세션.

| # | 결정 | 근거 / 되돌릴 조건 |
|---|---|---|
| D1 | **대표 원인(`hypotheses[0]`) = accepted 중 ④ fab 재랭킹 최상위** — ④ `hypothesis.py`의 `_rank_hypotheses`가 클러스터(unit+direction) 단위로 증거 세기 내림차순(동률: normal_ratio 오름차순 → kg rank) 정렬해 내보내고, ⑤ Critic·⑥ response는 순서를 보존만 한다(`accepted[0]` = ④의 1위). kg_rca 순위(`rank` = candidates 배열 순서)는 조사 순서·동률 타이브레이커로만 쓴다. 비채택 후보는 accepted 뒤에 같은 순서로 잇고, 정렬 확정 후 `h{n}` 부여 | 명세 §4-1 미결정 — 07-23 개정(S2-4): "문헌 순위(prior)는 조사 순서, 최종 순위는 fab 증거"로 재정의. 팀이 다른 규칙을 정하면 `_rank_hypotheses`만 교체(response.py는 순서 보존이라 무변경) |
| D2 | **첫 배치의 누적 스코프 = 데이터축 처음(EPOCH 2026-01-01)부터 전부**. 커서는 (직전 배치가 처리한 마지막 날짜, exclusive) → 데이터축 `max(ts)` (inclusive)로 전진 | 명세 §2.3 "직전 배치 이후 누적" — 직전 배치가 없으면 전체가 누적분. 구 `_FIRST_CURSOR_DATE=2026-03-04` 하드코딩은 폐기 |
| D3 | **`low_yield_eq` 선정 기준 = 7일 창 내 평균 수율 최저 장비 1개** (`backend/api/yield_summary.py`) | 명세 §2.1은 "장비별 yield 최저 1개 선정"만 규정, 창 기준은 미규정. 일별 최저(매일 다른 장비)로 바꾸려면 이 파일만 수정 |
| D4 | **같은 정규화 패턴으로 접히는 그룹이 여럿이면 unmapped끼리 로트 병합해 1건 저장** (`batch_runner._persist_results`) | `analysis_id`가 패턴+배치 단위 유니크(§3)라 비매핑 결함 여러 종(Donut·Loc…→전부 Unknown)이 충돌하는 것 방지. VLM이 실제 다패턴을 내기 시작하면 grouper 단계에서 정규화하는 방안 재검토 |
| D5 | **`chamber_id`는 전부 null** (commonality rows·suspect) | MCP `run_commonality_analysis`가 장비/챔버를 **별개 카운터**로 집계해 장비별 챔버를 특정할 수 없음. 장비-챔버 조인 집계가 MCP에 생기면 해소 |
| D6 | **normal_ratio caption의 지지/약화 판정 임계 = 정상비율 50%** (`assembler.py`) | 명세 §4-3(P3 반박 임계) 미결정 — caption 문구 생성에만 쓰는 표시용 잠정값. Critic 기각 임계가 확정되면 같은 값으로 정렬 |
| D7 | **telemetry `unit` = 빈 문자열** | fab.db/`fab_model.yaml`에 단위 메타가 없음. §2.7 계약상 non-null 문자열이면 되므로 ""로 충족. 시뮬레이터에 단위가 추가되면 채움 |
| D8 | **semi_auto 잠정 자동 기각 = Critic 4규칙 통과 후 `SEMI_AUTO_AUTO_REJECT` 토큰으로 기각** (`critic.py`) | 명세 §2.5 🔲 "Critic이 자동으로 기각" 이행. 4규칙 위반이 있으면 그 사유(P2~P5)가 우선. §4-2 사람 판정 엔드포인트가 생기면 이 분기 제거 |
| D9 | **`GET /lots/{id}/wafers`의 존재 판정 = 배치가 판독한 로트(wafer_reading 저장분)** — 미판독 lot_id는 404 | §2.6이 "판독 웨이퍼 목록"이므로 판독분이 원천. fab.db 전체 로트 조회로 넓히려면 정답 누출(라벨) 우회 경로 재검토 필요 |
| D10 | **가설 카드 수 무제한** — 후보 전수(수백 건 가능)를 verdict 포함 그대로 §2.5에 노출 | 계약에 상한 없음 + "no silent caps". 응답이 무거우면 계약에 페이지네이션을 추가하는 쪽으로(명세 개정 필요) |
| D11 | **telemetry `t0` = 항상 null** | 이상 시작 추정 로직(변화점 탐지 `detect_change_points`)이 파이프라인 미사용. §2.7 계약상 Nullable이라 충족. 변화점 연동 시 채움 |
| D12 | **logs의 그룹 컨텍스트 없음** — MCP 트레이스는 도구명+인자 요약만 (`batch_runner.LoggingMCP`) | 노드 내부를 건드리지 않는 위임 프록시 방식이라 그룹(패턴) 라벨을 모름. 메시지에 [패턴] 프리픽스가 필요해지면 hypothesis.py에 로그 훅 추가 필요 |
