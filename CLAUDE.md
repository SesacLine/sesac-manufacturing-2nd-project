# CLAUDE.md — SesacLine_SemiRCA

이 파일은 이 저장소를 처음 여는 Claude가 별도 탐색 없이 바로 맥락을 잡을 수 있도록 만든
프로젝트 요약이다. 세부 사항은 각 절 끝의 "정본 문서"를 따라간다 — 이 파일은 최신 수치를
따라가지 못할 수 있으니, 정확한 숫자가 필요하면 반드시 정본을 다시 확인할 것.

## 한눈에

**GraphRAG × Fab 운영데이터 기반 웨이퍼맵 결함 근본원인분석(RCA) 시스템.** 수율 엔지니어가
"오늘 판독 배치 확인" 버튼을 누르면, 저수율 로트를 골라 결함 패턴을 판독하고, 지식그래프
(문헌 기반 "일반적으로 이런 원인이 있을 수 있다")와 MCP 서버(fab.db 기반 "이번에 실제로
무슨 일이 있었나")를 교차 검증해 근거 있는 원인 후보 카드를 만들어준다.

- 팀 프로젝트(SeSAC 2nd Project), 개인 작업 공간은 `personalspace/`(이 repo 상위 폴더, git 추적 밖)
- **현재 상태(2026-07-13, kg_rca v2.4 갱신은 2026-07-14 반영)**: 파이프라인 ⓪~⑥ **Walking Skeleton
  완성**, end-to-end 실행 검증됨(kg_rca v2.4 갱신 후 재검증: Center 297건 후보 → 163건 채택/134건
  기각). 단, VLM(①)과 응답생성(⑥)은 실제 LLM 미연동 상태(하드코딩/템플릿) — 아래 "단순화 목록" 참고.
- 정본: `docs/semiconductor_proposal.md`(기획 전체, 배경·차별점·평가방법), `README.md`(백엔드 현황),
  `docs/skeleton_kickoff.md`(구축 로그·팀 결정사항, 가장 자주 갱신됨)

## 세 개의 하위 프로젝트

원래 각자 별도 `.git`을 가진 팀원별 저장소였으나 2026-07-13에 공동작업 목적으로 이 저장소
밑으로 물리 이동하고 자체 `.git`을 삭제했다 — 지금은 전부 이 repo 하나의 커밋 히스토리로
잡힌다. 루트 `pyproject.toml` 하나로 세 곳의 의존성을 통합 관리한다(`uv sync`).

| 폴더 | 역할 | 상태 |
|---|---|---|
| `backend/` | FastAPI + LangGraph 오케스트레이션. kg_rca와 secsgem-mcp를 연결하는 파이프라인 ⓪~⑥ | 스켈레톤 완성 |
| `kg_rca/` | GraphRAG. 도메인 문헌 → Neo4j 적재 → LLM KG 추출 → 결정적 그래프 순회로 원인 후보(`hypotheses.json`) 생성 | 완성, 계속 갱신 중(v2.4) |
| `secsgem-mcp/` | MCP 서버. SECS/GEM 시뮬레이터가 만든 가상 fab 운영 데이터(`fab.db`)를 9종 도구로 조회 | 완성 |

## 파이프라인 ⓪~⑥ (`backend/`)

```
⓪ select_low_yield_lots  lowyield.py   저수율 로트 선별 (fab.db 직접 SQL, 임계값 0.8 하드코딩)
① read_wafer_maps        vlm.py       웨이퍼맵 판독 — 실제 VLM 미연동, pattern="Center" 하드코딩
② group_by_pattern       grouper.py    로트별 다수결 대표패턴 → 패턴별 그룹화 (최소 로트수 게이트 없음)
③ fetch_graphrag_candidates graphrag.py  kg_rca 원인후보 조회 (KGClient.get_candidates)
④ build_hypotheses       hypothesis.py MCP 실호출로 증거 수집 (검증등급별 조건부 호출, 캐싱 포함)
⑤ review_hypotheses      critic.py     시간정합/반대증거/faithfulness/KG메커니즘 4규칙으로 채택·기각
⑥ generate_response      response.py   응답 카드 생성 — 실제 LLM 미연동, 결정적 템플릿 문자열
```

- `graph.py`: LangGraph `StateGraph` 조립. 그룹 팬아웃은 Send API가 아니라 **순차 loop**
  (`_run_per_group`). ③~⑥ 노드는 kg_client/mcp가 필요해 람다가 아니라 `async def`로 감싼다
  (람다는 `await`를 못 담아 실행 자체가 안 됨 — 실제로 겪은 버그).
- LLM을 실시간 호출하는 노드는 **①VLM과 ⑥응답생성 둘뿐**(2026-07-09 결정). ③~⑤는 원래부터
  결정적 룰베이스 함수이지 LLM이 아니다.
- `state.py`의 `RCAState`가 파이프라인 전체가 공유하는 상태 타입(TypedDict). 필드 흐름:
  `target_lot_ids → vlm_results → groups → graphrag_candidates → hypotheses → critic_result → final_response`.
- `main.py`: FastAPI 앱. `app_state.db`(SQLite)에 `cursor_state`(배치 커서 날짜) +
  `batch_group_result`(그룹별 최종 응답 JSON) 저장. 최초 커서 `2026-03-04` 하드코딩.

**현재 구현된 API 3종**: `POST /batch/run`(배치 1회 실행) · `GET /batch/results`(누적 결과 조회) ·
`GET /health`. 프론트↔백엔드 API 계약(8종, 명세 §3.1 표 기준)의 **정본은 `docs/API_명세서_v1.0.md`** — 계약은 확정이고
백엔드가 순차 구현 중이다(미구현 구간은 명세 본문 `🔲` 마커로 표시).

### MCP 연결 시 반드시 알아야 할 것

`MultiServerMCPClient.get_tools()`는 **호출마다 새 stdio 서브프로세스**를 만든다(라이브러리
docstring에 명시된 동작). Hypothesis 노드처럼 다회 호출하는 패턴에서 치명적으로 느려서
(Center 244건 처리 시 타임아웃 실측) `mcp_client/client.py`는 `client.session()`으로 연결을
한 번만 열고 `load_mcp_tools(session, ...)`로 재사용한다. `MCPClient`는 모듈 레벨 싱글턴 유지
(`backend/main.py` 참고) — 이 패턴을 깨지 말 것.

## kg_rca (GraphRAG)

```
data/raw/ 문헌 → 표 행 단위 청킹 → Neo4j 적재 → LLM KG 추출(+검증규칙 6종) → 결정적 순회 + LLM 문장합성
```

- 그래프 스키마(v2.3~v2.4, 정본 `docs/KG_schema_v1.2.md`): 노드 8종
  (`DefectPattern`·`SpatialSignature`·`ProcessStep`·`FailureMode`·`Cause`·`Parameter`·
  `Maintenance`·`Recipe`), 관계 7종(`ARISES_IN`/`OCCURS_IN`/`CAUSED_BY`/`VERIFIED_BY`/
  `ATTRIBUTED_TO`/`HAS_SIGNATURE`/`FORMS_IN`).
  `DefectPattern`(3종: Center/Edge-Ring/Scratch)·`ProcessStep`(6종)·`Parameter`(21종 —
  07-13 `pad_usage_hours` 추가)만 고정 vocabulary, 나머지는 LLM이 문헌에서 자유 추출.
- 검증등급 3단: **`[자동]`**(Parameter, 정상범위 이탈 여부를 시스템이 계산) /
  **`[반자동]`**(Maintenance·Recipe, 사람이 텍스트 판단 필요) / **`[근거없음]`**(fab 데이터로
  확인 불가). 파이프라인 ④에서 "어느 MCP 도구를 부를지"를 이 등급이 결정한다.
- 출력물: `kg_rca/outputs/hypotheses.json` — backend가 읽는 유일한 산출물(Neo4j 없이도 이 파일만
  있으면 backend 동작 가능). 가설 수는 재생성마다 바뀌므로 코드에 하드코딩 금지(2026-07-13 갱신
  기준 총 642건 — Center 297 · Edge-Ring 249 · Scratch 96, `kg_rca/STATUS.md` §1 참고).
- **출력 스키마(2026-07-13 개편, 정본 `kg_rca/KG_output_명세.md`)**: `route`/`score.confidence`
  필드가 빠지고 `scenario_hint`(MCP 검증 체인 라우팅: A2/A3/A5/A6/null)와
  `score.evidence_docs`/`evidence_chunks`(측정 기반 순위 성분)로 대체됐다. `backend/state.py`의
  `GraphRAGCandidate`·`backend/graph_client/kg_client.py`가 이 스키마를 따라가도록 2026-07-14에
  같이 갱신했다 — kg_rca를 다시 갱신할 때는 이 두 파일도 같이 봐야 한다.
- 실행 스크립트는 `0_reset.py`~`6_ask_graphrag.py` 순서(번호가 실행 순서).
- 알려진 미해결 문제(정본 `kg_rca/STATUS.md` §4): 검증신호 Maintenance 쏠림(P1), 가설 점수체계
  1차 재설계 완료·잔여 과제 있음(P2), Maintenance 노드 중복(P3), 추출 비결정성(P4), EDS 공정 문헌
  공백(P5, CLEAN은 07-13 해소됨), ProcessStep join 의미필터 없음(P6).
- **주의(cross-component 갭)**: kg_rca는 `pad_usage_hours`가 "fab에 실재"한다고 보고 `[자동]`
  승격까지 했지만(`MCP_KG_정합성검토.md` X1E), 이 저장소의 `secsgem-mcp/simulator/fab_model.yaml`
  CMP 파라미터에는 아직 `pad_usage_hours`가 없다(`down_force`/`slurry_flow`뿐) — 실제
  `query_telemetry` 호출 시 이 신호에 대해서는 정상범위를 못 찾을 것. secsgem-mcp 쪽 시뮬레이터
  갱신(및 `fab.db` 재생성)이 필요한 상태로 보인다.

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
uvicorn backend.main:app --reload
```

`secsgem-mcp/datasets/fab.db`가 없으면 `secsgem-mcp/README.md` "데이터 준비" 절차 선행 필요
(WM-811K 원천 데이터 다운로드 후 `python -m simulator.generate`로 빌드 — MixedWM38 불필요).

테스트: `pytest -q -m "not data"` (fab.db 빌드 없이 CI에서 도는 것과 동일).

## 알려진 단순화 / TODO (코드에 `# 결정①/②/③` 또는 `TODO(팀 결정 필요)`로 표시됨)

| 위치 | 지금 선택 | 비고 |
|---|---|---|
| `hypothesis.py` 결정① MCP 호출 단위 | 가설 단위 대신 `(step, evidence_label, evidence)` 캐싱 | 캐싱 없으면 244건에서 타임아웃 실측. 응급처치 수준 |
| `hypothesis.py` 결정② route="direct" 의심 장비 | `step=None`을 그대로 `run_commonality_analysis`에 전달 | 신호가 흐려짐 |
| `hypothesis.py` 결정③ `direction: null`인 `[자동]` 후보 | 방향 무시, 정상범위 이탈이면 `drift_detected=True` | 4건뿐이라 영향 작음 |
| `lowyield.py` 저수율 임계값 | `LOW_YIELD_THRESHOLD = 0.8` 고정값 | 동적 임계값 미검토 |
| `grouper.py` 최소 로트수 게이트 | `MIN_LOTS_PER_GROUP = 1`(게이트 없음) | 서브클러스터링 없음 |
| `vlm.py` | 실제 VLM 미연동, `pattern="Center"` 고정 | Qwen3-VL-4B 연동 예정(fine-tuning 목표) |
| `response.py` | 실제 LLM 미연동, 결정적 템플릿 문자열 | |
| `main.py` 배치 시작 커서 | `2026-03-04` 하드코딩 | fab.db 실데이터 범위 기준 시작일 정책 미정 |

컴포넌트별 상세 개선 목록(VLM/Hypothesis/Critic/응답생성/E2E평가 5개 표)은
`docs/skeleton_kickoff.md` §8 참고 — 재설계 착수 전 체크리스트로 쓰면 됨.

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
- 브랜치명: `{type}/#이슈번호-작업내용`.
- PR: 리뷰어 1명 승인 후 **본인이 merge**, 병합 브랜치는 삭제.
- 금지: `--force` 푸시, `main` 직접 push, `.env`/API 키/`fab.db` 커밋.

## 막히면 볼 문서 (정본 인덱스)

| 궁금한 것 | 문서 |
|---|---|
| 기획 전체(배경·차별점·기술스택·평가방법·타임라인) | `docs/semiconductor_proposal.md` |
| 백엔드 현재 상태·구조·실행법 | `README.md` |
| 스켈레톤 구축 로그·팀 결정사항·컴포넌트별 개선목록 (가장 자주 갱신) | `docs/skeleton_kickoff.md` |
| 프론트↔백엔드 API 계약 8종(정본) | `docs/API_명세서_v1.0.md` |
| KG 스키마 전체 명세(정본) | `docs/KG_schema_v1.2.md` (`kg_rca/schema_v2.md`는 07-14에 삭제됨, 내용은 이 파일로 이전) |
| `hypotheses.json` 출력 필드별 상세 명세(정본) | `kg_rca/KG_output_명세.md` |
| KG 진행상황·남은 문제 | `kg_rca/STATUS.md` |
| KG↔MCP 정합성 검토(용어 불일치, X1E pad_usage_hours 등) | `kg_rca/MCP_KG_정합성검토.md` |
| 데이터 모델 설계(v1.0/v2.0) | `kg_rca/데이터 모델 설계_v1 0.md`, `kg_rca/데이터 모델 설계_v2.0.md` |
| MCP 9종 도구 상세 계약 | `secsgem-mcp/README.md` |
| MCP 시나리오(A0~E4) | `kg_rca/SECS GEM MCP 문서_v0 1.md` |
| Git 컨벤션 | `docs/git_convention_v0.2.md` |
