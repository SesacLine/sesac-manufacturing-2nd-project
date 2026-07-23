# CLAUDE.md

이 파일은 이 저장소를 처음 여는 Claude가 별도 탐색 없이 바로 맥락을 잡을 수 있도록 만든
프로젝트 요약이다. 세부 사항은 각 절 끝의 "정본 문서"를 따라간다 — 이 파일은 최신 수치를
따라가지 못할 수 있으니, 정확한 숫자가 필요하면 반드시 정본을 다시 확인할 것.

## 한눈에

**지식그래프(KG) × Fab 운영데이터 기반 웨이퍼맵 결함 근본원인분석(RCA) 시스템.** 수율 엔지니어가
"오늘 판독 배치 확인" 버튼을 누르면, 저수율 로트를 골라 결함 패턴을 판독하고, 지식그래프
(문헌 기반 "일반적으로 이런 원인이 있을 수 있다")와 MCP 서버(fab.db 기반 "이번에 실제로
무슨 일이 있었나")를 교차 검증해 근거 있는 원인 후보 카드를 만들어준다. 자유 질의는 없고
**고정 질문 템플릿**(`"{패턴} 결함 패턴이 나타나는 근본 원인은 무엇인가요?"`) 하나로만 돈다.

> **용어 주의**: 기획안 v1.5부터 이 시스템을 "GraphRAG"라고 부르지 않는다. 동적 커뮤니티
> 요약을 하는 GraphRAG 기법 자체는 쓰지 않고, 문헌으로 정적 구축한 KG를 빌드타임에 결정적으로
> 순회해 둔 결과를 런타임에 조회만 하기 때문이다. 다만 **코드 식별자에는 옛 이름이 그대로 남아
> 있다**(`backend/nodes/graphrag.py`, `fetch_graphrag_candidates`, `RCAState.graphrag_candidates`) —
> 리네이밍은 아직 안 했으므로 코드를 읽을 때 혼동하지 말 것.

- 팀 프로젝트(SeSAC 2nd Project). **개인 작업 공간은 이 repo 안의 `personalspace_rca/`**(`.gitignore`
  등록됨, git 추적 밖). 날짜별 `MMDD work/` 폴더 아래에 그날 스터디·설계 노트를 둔다(예:
  `personalspace_rca/0718 work/0718_study.md`). Claude는 개인 작업/노트를 항상 여기에 만들 것 —
  repo 상위의 옛 `Semiconductor/personalspace/`(0714까지)는 폐기된 위치이므로 쓰지 말 것.
- **④/⑤ 갱신(2026-07-23)**: ④ Hypothesis·⑤ Critic이 스켈레톤을 크게 벗어났다. ④는 자동 tier
  LLM 그룹 조사관(배치 telemetry)·방향 대조·cause 클러스터·**fab 재랭킹**·스텝 상한까지, ⑤는
  4규칙 + `investigated` 소비(judge_unknown 분기)까지 구현됨(슬라이스2 S2-1~6). 이어 ground truth
  E2E 평가(슬라이스3)로 **SC-CENTER-01 근본원인 top-1 달성**(정답 193위 rejected → 0위 accepted,
  함정 P2 시간역전 44건 명시 기각). 처방 4종은 BACKEND_DECISIONS D13~D16. **④/⑤ 상세 정본은
  `personalspace_rca`의 hypo_critic_py.md·terms_of_reference.md·hypo_critic_test_result.md** —
  아래 파이프라인 절의 `32b3690` 스냅샷은 이 전환 이전이라 ③~⑥ 서술이 낡았으니 상세는 그쪽을 볼 것.
- **현재 상태(2026-07-20 기준)**
  - 파이프라인은 **커밋 `32b3690` 기준 ⓪~⑥**으로 Walking Skeleton 완성, end-to-end 실행
    검증됨(kg_rca v2.4 갱신 후 재검증: Center 297건 후보 → 163건 채택/134건 기각). 단, VLM
    (`32b3690` 기준 ①)과 응답생성(`32b3690` 기준 ⑥)은 실제 모델 미연동(하드코딩/템플릿) —
    아래 "단순화 목록" 참고.
    ⚠️ **이 ⓪~⑥ 구성은 기획안 v1.5 이전 상태다** — v1.5 목표는 CNN이 추가된 ⓪~⑦이며,
    아래 "파이프라인" 절의 목표 vs `32b3690` 대조를 볼 것.
  - **API 계약 8종 구현 완료**(07-20, `32b3690`). **React 프론트엔드는 수정 중**(같은 커밋에서
    최초 구현, 이후 계속 손보는 중).
  - **기획안이 v1.5로 개정됨**(07-20): 판독 파이프라인에 CNN 노드가 추가되고 VLM 역할이 바뀌었다.
    **`backend/` 코드는 아직 이 개정을 반영하지 않았다** — 아래 "파이프라인" 절의 목표 vs
    `32b3690` 대조를 먼저 읽을 것.
- 정본: `docs/semiconductor_proposal.md`(기획 전체, 배경·차별점·평가방법), `docs/API_명세서_v1.0.md`(프론트↔백엔드 API 계약)

## 네 개의 하위 프로젝트

`backend`/`kg_rca`/`secsgem-mcp`는 원래 각자 별도 `.git`을 가진 팀원별 저장소였으나 2026-07-13에
공동작업 목적으로 이 저장소 밑으로 물리 이동하고 자체 `.git`을 삭제했다 — 지금은 전부 이 repo
하나의 커밋 히스토리로 잡힌다. 파이썬 3종은 루트 `pyproject.toml` 하나로 의존성을 통합 관리한다
(`uv sync`). `frontend`는 2026-07-20에 추가됐고 npm으로 따로 관리한다.

| 폴더 | 역할 | 상태 |
|---|---|---|
| `frontend/` | React + Vite 대시보드. 3화면 + 근거 모달, dev 서버 `:5173` | 최초 구현 완료 |
| `backend/` | FastAPI + LangGraph 오케스트레이션. kg_rca와 secsgem-mcp를 연결하는 파이프라인 (`32b3690` 기준 ⓪~⑥ / 기획안 v1.5 목표 ⓪~⑦) | 스켈레톤 완성, v1.5 개편 미반영 |
| `kg_rca/` | 지식그래프(KG). 도메인 문헌 → Neo4j 적재 → LLM KG 추출 → 결정적 그래프 순회로 원인 후보(`hypotheses.json`) 생성 | 완성, 계속 갱신 중 |
| `secsgem-mcp/` | MCP 서버. SECS/GEM 시뮬레이터가 만든 가상 fab 운영 데이터(`fab.db`)를 9종 도구로 조회 | 완성 |

## 파이프라인 (`backend/`) — 목표 8단계 vs 커밋 `32b3690` 7단계

⚠️ **기획안 v1.5(2026-07-20 반영)에서 판독 파이프라인이 개편됐고, `backend/` 코드는 아직 반영
전이다.** 아래 "`32b3690` 기준"은 **backend를 마지막으로 건드린 커밋**(`[Feat] #11`, 07-20)의
코드 상태를 뜻한다 — 그 뒤로 backend가 커밋되면 이 절부터 낡는다. 목표 구조와 커밋 상태를
구분해서 읽을 것.

**기획안 v1.5 목표 구조 ⓪~⑦** (정본 `docs/semiconductor_proposal.md` §7.1)

```
⓪ 저수율 로트 선별      wafer.die_map 직접 집계 (결정적 함수) — 32b3690과 동일
① CNN 결함 패턴 판정    ← 신설. 실시간 비전 모델 추론(ResNet 계열 등)
                       3종 + Unknown + Normal
② Grouper              CNN 판정 결과 기반 유사 패턴 그룹화 (결정적 함수)
                       Normal은 정상이라 그룹 미생성
③ VLM description 생성  그룹별 "대표 패턴"의 공간/형상을 자연어 서술 — API + few-shot, 실시간
④ 지식그래프(KG) 조회   ③의 (패턴, description) 쌍을 검색 키로 빌드타임 순회 결과를 조회
⑤ Hypothesis           검증등급별 MCP 도구 조건부 호출 → Evidence table
⑥ Critic               시간정합/반대근거/faithfulness/KG메커니즘 4규칙 (규칙 기반, LLM 미사용)
⑦ 응답생성             Root Cause + Evidence + 권장 조치 카드 — 실시간 LLM
```

핵심 변화 두 가지:
- **CNN 노드가 신설**되어 분류를 맡고, **VLM은 "판독"에서 "서술(description)"로 역할이 바뀌었다.**
- **VLM이 Grouper 뒤로 이동**했다. 그룹 대표에만 VLM을 호출해 호출 수를 줄이는 구조라, 기존
  "VLM 판독 → 그 결과로 그룹화" 순서와 전제가 반대다.

**커밋 `32b3690` 기준 ⓪~⑥** (CNN 없음, VLM이 판독까지 담당하던 옛 구조)

```
⓪ select_low_yield_lots  nodes/lowyield.py   저수율 로트 선별 (wafer.die_map 집계 SQL, 임계값 0.8 하드코딩)
① read_wafer_maps        nodes/vlm.py        웨이퍼맵 판독 — 실제 VLM 미연동, pattern="Center" 하드코딩
② group_by_pattern       nodes/grouper.py    로트별 다수결 대표패턴 → 패턴별 그룹화 (최소 로트수 게이트 없음)
③ fetch_graphrag_candidates nodes/graphrag.py kg_rca 원인후보 조회 (KGClient.get_candidates)
④ build_hypotheses       nodes/hypothesis.py MCP 실호출로 증거 수집 (검증등급별 조건부 호출, 캐싱 포함)
⑤ review_hypotheses      nodes/critic.py     시간정합/반대증거/faithfulness/KG메커니즘 4규칙으로 채택·기각
⑥ generate_response      nodes/response.py   응답 카드 생성 — 실제 LLM 미연동, 결정적 템플릿 문자열
```

목표 ↔ `32b3690` 대응: 목표①CNN은 **미구현**, 목표②③이 `32b3690`에서는 ①VLM판독 → ②그룹화로
순서가 뒤집혀 있고, 목표④⑤⑥⑦ = `32b3690` ③④⑤⑥.

- `graph.py`: LangGraph `StateGraph` 조립. 그룹 팬아웃은 Send API가 아니라 **순차 loop**
  (`_run_per_group`). ③~⑥ 노드는 kg_client/mcp가 필요해 람다가 아니라 `async def`로 감싼다
  (람다는 `await`를 못 담아 실행 자체가 안 됨 — 실제로 겪은 버그).
- **실시간 모델/LLM 호출 노드**: 목표 구조 기준 ①CNN(**비전 모델**, LLM 아님) · ③VLM · ⑦응답생성
  (LLM), 그리고 **④ Hypothesis의 자동(Parameter) tier**(2026-07-22 S2-2로 `create_react_agent`
  그룹 조사관 도입 — 반자동·근거없음은 결정론). KG 조회는 빌드타임 결과 조회. **Critic은 규칙
  기반으로 LLM을 쓰지 않는다(확정).** ④가 LLM이 됐어도 숫자(evidence)는 도구 반환에서 코드가
  재구성하고 LLM은 서사(rationale)만 쓴다(옵션 A) — Critic은 evidence만 읽어 판정(faithfulness firewall).
- **재시도 없음**: 채택 후보가 0개면 재시도하지 않고 즉시 `insufficient_evidence`("판단 불가")를
  반환한다. 근거 없이 답을 지어내지 않는 것이 이 설계의 환각 억제 장치다(기획안 §5.2·§7.1).
- **판정 책임 경계(S2 확정)**: 최종 채택/기각은 **전부 ⑤ Critic**이 한다 — ④는 tier 무관하게
  증거 수집·검증·**랭킹(soft)**만 하고 기각 판정은 안 한다(hypo_critic_py.md §1). 자동 tier도
  ④에서 즉시 채택되지 않고 evidence(drift 등)를 채워 ⑤ 4규칙으로 넘긴다. 기획안 §7.1의 "자동은
  ④에서 즉시 채택/기각" 서술은 S2 설계에서 "④ soft / ⑤ hard"로 정리됐으니 그대로 인용하지 말 것.
- **✅ Hypothesis 노드 확정(2026-07-22, S2-2)**: 자동(Parameter) tier는 **LLM 에이전트**
  (`create_react_agent` 그룹 조사관)가 step 배치로 telemetry를 검증하고, 반자동·근거없음은
  **결정론 룰베이스**다(tier별 하이브리드). 단 숫자는 도구 반환에서 코드가 재구성하고 LLM은
  rationale만 쓴다(옵션 A). `32b3690` 스냅샷(위 절)은 이 전환 이전이라 전 tier 결정론이었다 —
  스냅샷 표를 현재 코드로 읽지 말 것. ④/⑤ 상세 정본은 `personalspace_rca`의 hypo_critic_py.md.
- `state.py`의 `RCAState`가 파이프라인 전체가 공유하는 상태 타입(TypedDict). 현 필드 흐름:
  `cursor_date`/`cursor_end` → `target_lot_ids → vlm_results → groups → graphrag_candidates →
  hypotheses → critic_result → final_response`.
  KG 검색 키는 목표 구조에서 **CNN 라벨 + VLM description 쌍**이 된다(기획안 §6.2/§7.1). `VLMResult`에
  `pattern`과 `description`이 이미 **별도 필드로 있어** 새 필드가 필요한 게 아니라, 각 값을 누가
  생산하느냐(CNN vs VLM)가 갈리는 것이다.
- `main.py`는 **앱 조립만** 한다(CORS·라우터 등록·`store.init_db()`). 엔드포인트는 `api/`,
  저장 계층은 `store.py`, 전역 싱글턴(KGClient·MCPClient)은 `deps.py`에 있다.
- `store.py`: `app_state.db`(SQLite) 테이블 4종 — `cursor_state`(배치 커서) · `batch` · `analysis` ·
  `wafer_reading`. 배치 커서의 시작점은 `config.py`의 `DATA_EPOCH = "2026-01-01"`에서 파생된다
  (`batch_runner.py`).

**결함 패턴 처리 범위 (기획안 §6.1 확정)**: 이 프로젝트가 다루는 결함 패턴은
**Center/Edge-Ring/Scratch 3종뿐**이다. CNN은 여기에 **`Unknown`·`Normal`을 더해 판정**한다 —
WM-811K의 나머지 결함 패턴은 전부 `Unknown`(= "새로운 결함 패턴")으로 처리하고 **`Normal`은 정상 웨이퍼이므로 그룹을 만들지 않는다.**
KG~응답생성 경로는 3종에만 연결된다.

**API 계약 8종 구현 완료**(2026-07-20 커밋 `32b3690`). 정본은 **`docs/API_명세서_v1.0.md` §2**
(§2.1~§2.7 — §3.1은 계약이 아니라 "엔드포인트별 에러 요약"이니 헷갈리지 말 것).
전부 `/api/v1` prefix, 라우터는 `backend/api/` 하위:

```
GET  /api/v1/yield-summary                                    수율 현황 요약 (화면1)
GET  /api/v1/analyses                                         분석 결과 대기열 (화면1)
POST /api/v1/batches                                          배치 실행 (202 비동기 접수)
GET  /api/v1/batches/{batch_id}                               배치 진행 상태 (화면2)
GET  /api/v1/analyses/{analysis_id}                           분석 결과 상세 (화면3)
GET  /api/v1/analyses/{analysis_id}/evidence/{hypothesis_id}  근거 상세 (모달)
GET  /api/v1/lots/{lot_id}/wafers                             로트 웨이퍼맵 판독
GET  /api/v1/lots/{lot_id}/wafers/{wafer_id}/die-map          웨이퍼맵 이미지
GET  /health                                                  (prefix 밖, main.py 직접)
```

⚠️ 구 엔드포인트 `POST /batch/run` · `GET /batch/results`는 **삭제됐다**(각각 `POST /api/v1/batches`,
`GET /api/v1/analyses`로 대체). 옛 문서나 코드 주석에서 보더라도 쓰지 말 것.

### MCP 연결 시 반드시 알아야 할 것

`MultiServerMCPClient.get_tools()`는 **호출마다 새 stdio 서브프로세스**를 만든다(라이브러리
docstring에 명시된 동작). Hypothesis 노드처럼 다회 호출하는 패턴에서 치명적으로 느려서
(Center 244건 처리 시 타임아웃 실측) `mcp_client/client.py`는 `client.session()`으로 연결을
한 번만 열고 `load_mcp_tools(session, ...)`로 재사용한다. `MCPClient`는 모듈 레벨 싱글턴 유지
(`backend/deps.py`의 `_mcp_client` / `mcp_client()`) — 이 패턴을 깨지 말 것.

## kg_rca (지식그래프)

```
data/raw/ 문헌 → 표 행 단위 청킹 → Neo4j 적재 → LLM KG 추출(+검증규칙 6종) → 결정적 순회 + LLM 문장합성
```

- 그래프 스키마(정본 `docs/KG_schema_v1.4.md`): 노드 8종
  (`DefectPattern`·`SpatialSignature`·`ProcessStep`·`FailureMode`·`Cause`·`Parameter`·
  `Maintenance`·`Recipe`), 관계 7종(`ARISES_IN`/`OCCURS_IN`/`CAUSED_BY`/`VERIFIED_BY`/
  `ATTRIBUTED_TO`/`HAS_SIGNATURE`/`FORMS_IN`).
  `DefectPattern`(3종: Center/Edge-Ring/Scratch)·`ProcessStep`(6종)·`Parameter`(21종 —
  07-13 `pad_usage_hours` 추가)만 고정 vocabulary, 나머지는 LLM이 문헌에서 자유 추출.
- 검증등급 3단: **`[자동]`**(Parameter, 정상범위 이탈 여부를 시스템이 계산) /
  **`[반자동]`**(Maintenance·Recipe, 사람이 텍스트 판단 필요) / **`[근거없음]`**(fab 데이터로
  확인 불가). Hypothesis 노드(`32b3690` ④ / 목표 ⑤)에서 "어느 MCP 도구를 부를지"를 이 등급이
  결정한다. 등급 부여 기준은 "fab.db에 데이터가 있느냐"가 **아니라** "결정적 조인 키 + 판정
  규칙으로 자동 채택/기각까지 갈 수 있느냐"다(기획안 §6.2).
- 출력물: `kg_rca/outputs/hypotheses.json` — backend가 읽는 유일한 산출물(Neo4j 없이도 이 파일만
  있으면 backend 동작 가능). 가설 수는 재생성마다 바뀌므로 코드에 하드코딩 금지(2026-07-13 갱신
  기준 총 642건 — Center 297 · Edge-Ring 249 · Scratch 96 / **07-22 재빌드(doc_A~H 편입) 후
  772건** — Center 375 · Edge-Ring 290 · Scratch 107, `kg_rca/STATUS.md` §1 참고).
- **⚠️ 기획안이 낡은 구간**: `docs/semiconductor_proposal.md` §6.2는 아직 "문헌 5편 → 청크 95개 →
  가설 **125건**(Center 62/Edge-Ring 53/Scratch 10)"으로 07-13 개편 이전 수치를 쓰고, 스키마도
  `SpatialSignature` 노드와 `HAS_SIGNATURE`/`FORMS_IN` 관계가 빠진 구버전 표기다. **가설 수·스키마의
  정본은 `kg_rca/STATUS.md` §1과 `docs/KG_schema_v1.4.md`** — 기획안 수치를 인용하지 말 것.
  (`kg_rca/STATUS.md` 안에도 "가설이 125건인 이유" 옛 문단이 남아 있어 정리 대상.)
- **출력 스키마(2026-07-13 개편, 정본 `kg_rca/KG_output_명세.md`)**: `route`/`score.confidence`
  필드가 빠지고 `scenario_hint`(MCP 검증 체인 라우팅: A2/A3/A5/A6/null)와
  `score.evidence_docs`/`evidence_chunks`(측정 기반 순위 성분)로 대체됐다. `backend/state.py`의
  `GraphRAGCandidate`·`backend/graph_client/kg_client.py`가 이 스키마를 따라가도록 2026-07-14에
  같이 갱신했다 — kg_rca를 다시 갱신할 때는 이 두 파일도 같이 봐야 한다.
- 실행 스크립트는 `0_reset.py`~`6_ask_graphrag.py` 순서(번호가 실행 순서).
- 알려진 미해결 문제(정본 `kg_rca/STATUS.md` §4): 검증신호 Maintenance 쏠림(P1), 가설 점수체계
  1차 재설계 완료·잔여 과제 있음(P2), Maintenance 노드 중복(P3), 추출 비결정성(P4), EDS 공정 문헌
  공백(P5, CLEAN은 07-13 해소됨), ProcessStep join 의미필터 없음(P6).
- **cross-component 갭 `pad_usage_hours` — 2026-07-15 해소됨**: kg_rca가 `[자동]` 승격한
  `pad_usage_hours`(`MCP_KG_정합성검토.md` X1E)가 시뮬레이터에 없던 문제는 커밋 `2a95e43`로
  해결됐다. 지금은 `secsgem-mcp/simulator/fab_model.yaml`의 CMP 블록에
  `pad_usage_hours: {normal: [0, 250], unit: h, counter_rate_per_day: 11}`이 있다.
  (`docs/skeleton_kickoff.md`에는 아직 미해결로 적힌 서술이 남아 있으니 그쪽을 믿지 말 것.)

## secsgem-mcp (MCP 서버, 9종 도구)

WM-811K 웨이퍼맵 + SECS/GEM 시뮬레이터 합성 fab 데이터(`fab.db`, SQLite, read-only)를
lot/wafer 키로 결합해 제공. 실시간 SECS/GEM 통신은 하지 않음 — 전부 빌드타임 생성 데이터.
(MixedWM38은 팀 결정으로 제외 — 시뮬레이터 빌드도 WM-811K만 받는다.)

| 도구 | 조회 대상 | 역할 |
|---|---|---|
| `get_wafer_map` | wafer | 웨이퍼 이미지(base64 PNG, 라벨 없음) — VLM 입력용 |
| `get_lot_history` | lot_history | 로트가 지난 장비 이력 |
| `run_commonality_analysis` | lot_history | 불량 로트 공통 장비 — **모든 가설 공통 호출** |
| `get_normal_lot_ratio` | wafer+lot_history | 반대 증거(정상 로트 비율) — **모든 가설 공통 호출** |
| `query_telemetry` | telemetry | 센서값 시계열, `[자동]` 등급 전용 |
| `get_maintenance_history` | maintenance | 정비 이력, `[반자동]` 등급(Maintenance) 전용 |
| `get_alarm_history` | alarm | 알람 — `lot_id`가 아닌 `equipment_id`로 조회해야 값이 나옴(fab.db 알람 131건 전부 `lot_id=NULL`) |
| `detect_change_points` | metric_series/event_log | 변화점 탐지 (현재 파이프라인 미사용) |
| `get_lot_timeline` | lot_history+alarm | 시간 정합 검사(Critic 단계) |

모든 응답은 `{data, meta}` 공통 스키마. `meta.coverage.missing`으로 없는 구간을 명시하고,
웨이퍼 라벨은 어떤 도구도 반환하지 않음(정답 누출 차단). fab.db 스키마 7개 테이블 요약은
`secsgem-mcp/README.md` §3.

## 설치 · 실행

```bash
pip install uv
uv venv && uv sync                # 루트 pyproject.toml 하나로 backend/kg_rca/secsgem-mcp 전부 설치
.venv\Scripts\activate             # Windows
cp .env_example .env               # 상대경로 이미 맞춰짐, OPENAI_API_KEY만 채우면 됨
uvicorn backend.main:app --reload  # 터미널 1 → :8000

cd frontend && npm install && npm run dev   # 터미널 2 → :5173
```

브라우저는 `http://localhost:5173`으로 연다(백엔드 단독 확인은 `http://localhost:8000/docs`).
CORS는 `:5173`만 허용된다(`backend/main.py`, 프록시 미사용).

`secsgem-mcp/datasets/fab.db`가 없으면 `secsgem-mcp/README.md` "데이터 준비" 절차 선행 필요
(WM-811K 원천 데이터 다운로드 후 `python -m simulator.generate`로 빌드 — MixedWM38 불필요).

테스트: `pytest -q -m "not data"` (fab.db 빌드 없이 CI에서 도는 것과 동일).

## 알려진 단순화 / TODO (코드에 `# 결정①/②/③` 또는 `TODO(팀 결정 필요)`로 표시됨)

| 위치 | 지금 선택 | 비고 |
|---|---|---|
| `hypothesis.py` 결정① MCP 호출 단위 | 가설 단위 대신 `(step, evidence_label, evidence)` 캐싱 | 캐싱 없으면 244건에서 타임아웃 실측. 응급처치 수준 |
| `hypothesis.py` 결정② `step=None` 후보 | **mapping.process로 step 폴백**(`_with_step_fallback`, 07-23 처방·BACKEND_DECISIONS D14) — 이전엔 `step=None`을 그대로 commonality에 전달해 함정 장비로 쏠렸음(SC-CENTER-01 실측) | 근본은 kg_rca 6번 교정(`kg_step보충_제안.md` 전달), 반영되면 폴백 무동작. (`route` 필드는 07-13 개편으로 출력에서 제거됨 — `step` 유무로 판단) |
| ~~`hypothesis.py` 결정③ direction 무시~~ **해소(07-22 S2-1)** | 방향 대조(`_drift_direction`/`_direction_match`) 승격 — drift 방향↔KG 예상 대조로 경쟁 가설 판별 | `direction=null` 후보만 n/a로 잔존 |
| `lowyield.py` 저수율 임계값 | `LOW_YIELD_THRESHOLD = 0.8` 고정값 | 동적 임계값 미검토 |
| `grouper.py` 최소 로트수 게이트 | `MIN_LOTS_PER_GROUP = 1`(게이트 없음) | 서브클러스터링 없음 |
| `vlm.py` | 실제 VLM 미연동, `pattern="Center"` 고정 | **파인튜닝 없음**이 기획안 확정 — VLM API(Qwen3-VL·Gemini 등) + few-shot 프롬프팅. Qwen3-VL-4B 파인튜닝은 선행연구(WaferSAGE)가 한 것이지 우리 계획이 아님 |
| CNN 분류 노드 | **미구현** | 기획안 v1.5 목표 구조 ①. ResNet 계열 경량 비전 모델, Center/Edge-Ring/Scratch 3종 + `Unknown` + `Normal` 판정 |
| `response.py` | 실제 LLM 미연동, 결정적 템플릿 문자열 | |
| `main.py` 배치 시작 커서 | `2026-03-04` 하드코딩 | fab.db 실데이터 범위 기준 시작일 정책 미정 |

| 검증 라운드 상한 | **배치당 에이전트 스텝 상한 도입**(`AGENT_RECURSION_LIMIT=8`, 07-23 S2-5) — 초과(폭주) 시 그 배치 미조사 폴백 | 기획안 §9 "상한" 이행. 단 가설별 추적 ID 로깅은 여전히 미반영. 후보 전량 순회 자체는 유지(함축은 랭킹이 담당) |

컴포넌트별 상세 개선 목록(VLM/Hypothesis/Critic/응답생성/E2E평가 5개 표)은
`docs/skeleton_kickoff.md` §8 참고 — 재설계 착수 전 체크리스트로 쓰면 됨.
⚠️ 단 `skeleton_kickoff.md` §8.1 첫 행의 *"fine-tuning이 목표, few-shot은 차선"* 은 **기획안 v1.5
이전 서술이라 무효**다(v1.5 §7·§9에서 "파인튜닝 없음"으로 확정). `pad_usage_hours` 미해결 서술도
같은 이유로 낡았다(07-15 해소).

## 평가 체계 (정본: `docs/semiconductor_proposal.md` §6.4·§10)

아직 **구현된 평가 코드는 없다**(E2E 평가는 `docs/skeleton_kickoff.md` §8 개선목록에 남아 있음).
기획안이 정의한 지표는 8종 — Latency / 판독 정확도(Precision·Recall) / 설명 정확도(BLEU·ROUGE-L) /
faithfulness / 경로 정합성 / **단일경로 vs 다중가설탐색 RCA 품질**(이 프로젝트의 핵심 비교 실험) /
사용자 만족도(5점 Likert) / KG-Fab 어휘 정합성. 정답 데이터는 합성 시나리오별 Ground Truth Root
Cause를 쓴다. `cross-fab OOD` 판독 견고성 평가는 우선순위 2(가능하면 구현)다.

데이터 역할 요약: **WM-811K**=결함을 본다(입력) · **KG**=원인 후보를 만든다(지식) ·
**fab.db**=후보를 검증한다(사실) · **Ground Truth**=성능을 평가한다(평가).

## 알려진 버그(이미 발견·수정·재검증 완료 — 재발 방지용 기록)

1. `mcp_client/client.py`의 `_as_dict`가 구조화 출력 없을 때 MCP 표준 콘텐츠 블록 리스트
   (`[{"type": "text", "text": "<json>"}]`)를 못 받았음 — dict/str만 처리하던 버그.
2. MCP 서버 기동 커맨드를 `"command": "python"`으로 두면 PATH 의존적으로 다른 파이썬이 잡혀
   `fastmcp`를 못 찾고 죽음 — `sys.executable`로 고정 필요.
3. Windows에서 `env=`를 통째로 갈아치우면 `SystemRoot` 등 필수 환경변수가 빠져 불안정 —
   부모 환경 이어받은 채로 `PYTHONPATH`/`FAB_DB`만 덧붙일 것.
4. `MultiServerMCPClient.get_tools()`가 호출마다 새 세션(서브프로세스)을 만드는 문제 — 위
   "MCP 연결" 절 참고. 가장 치명적이었던 버그(타임아웃 유발).
5. `secsgem-mcp/simulator/fab_model.py`가 Windows에서 `fab_model.yaml`을 인코딩 미지정으로
   읽어 한글 주석에서 `UnicodeDecodeError` — `encoding="utf-8"` 명시 필요. Windows에서 파일
   읽을 때는 항상 인코딩 명시할 것.

## Git 컨벤션 요약 (정본: `docs/git_convention_v0.2.md`)

- 브랜치: `develop` 없이 **`main` 하나만**. 이슈 기반 브랜치 → PR → `main`. `main` 직접 push 금지.
- 커밋: `[Type] #이슈번호 제목` — Type은 `Feat`/`Fix`/`Refactor`/`Docs`/`Chore`/`Test`.
- 브랜치명: `{type}/#이슈번호-작업내용` — 작업내용은 영어 소문자 + 하이픈으로만(한글 금지).
- PR: 리뷰어 1명 승인 후 **해당 리뷰어가 merge**, 병합 브랜치는 삭제하지 않고 유지.
- 금지: `--force` 푸시, `main` 직접 push, `.env`/API 키/`fab.db` 커밋.

## 막히면 볼 문서 (정본 인덱스)

| 궁금한 것 | 문서 |
|---|---|
| 기획 전체(배경·차별점·기술스택·평가방법·타임라인) | `docs/semiconductor_proposal.md` |
| 백엔드 현재 상태·구조·실행법 | `README.md` |
| 스켈레톤 구축 로그·팀 결정사항·컴포넌트별 개선목록 (가장 자주 갱신) | `docs/skeleton_kickoff.md` |
| 프론트↔백엔드 API 계약 8종(정본) | `docs/API_명세서_v1.0.md` |
| KG 스키마 전체 명세(정본) | `docs/KG_schema_v1.4.md` |
| `hypotheses.json` 출력 필드별 상세 명세(정본) | `kg_rca/KG_output_명세.md` |
| KG 진행상황·남은 문제 | `kg_rca/STATUS.md` |
| KG↔MCP 정합성 검토(용어 불일치, X1E pad_usage_hours 등) | `kg_rca/MCP_KG_정합성검토.md` |
| 데이터 모델 설계(v1.0/v2.0) | `kg_rca/데이터 모델 설계_v1 0.md`, `kg_rca/데이터 모델 설계_v2.0.md` |
| MCP 9종 도구 상세 계약 | `secsgem-mcp/README.md` |
| MCP 시나리오(A0~E4) | `docs/SECS_GEM MCP document.md` (개인 사본 `..personal/SECS GEM MCP 문서_v0.1.md`) |
| Git 컨벤션 | `docs/git_convention_v0.2.md` |
