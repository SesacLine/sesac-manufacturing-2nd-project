# SesacLine SemiRCA

**GraphRAG × Fab 운영데이터 기반 웨이퍼맵 결함 근본원인분석(RCA) 시스템** — SeSAC 2nd Project.

반도체 팹에서 수율이 떨어진 로트가 나오면, 엔지니어는 "이 결함 패턴이 왜 생겼는지"를 장비 이력·
센서값·정비 기록을 뒤져가며 찾아야 한다. 이 시스템은 그 과정을 자동화한다. 수율 엔지니어가
대시보드에서 **"오늘 판독 배치 확인"** 버튼 하나를 누르면:

1. 저수율 로트를 골라 웨이퍼맵 결함 패턴을 판독하고 패턴별로 묶은 뒤,
2. **지식그래프**(문헌 기반 — "이런 결함은 일반적으로 이런 원인이 있을 수 있다")와
   **MCP 서버**(fab.db 기반 — "이번에 실제로 무슨 일이 있었나")를 교차 검증해,
3. 근거가 붙은 원인 후보 카드를 만들어준다.

핵심은 **"확정"이 아니라 "근거 있는 가설"까지가 스코프**라는 것이다. 채택된 가설마다 공통 장비
집계·센서 시계열·정비 이력을 근거로 함께 보여주고, 반대 증거(정상 로트가 그 장비를 많이 통과했다면)
와 시간 정합(원인이 결함보다 늦게 일어났다면)으로 기각된 후보도 사유와 함께 남긴다.

## 아키텍처

```
                     [React 대시보드 (:5173)]
                              │ HTTP (API 8종)
                              ▼
                     [FastAPI + LangGraph (:8000)]
                              │
      ┌───────────────────────┼────────────────────────┐
      │ 파일 읽기              │ MCP (stdio 서브프로세스)  │ 직접 SQL
      ▼                       ▼                        ▼
  kg_rca/                secsgem-mcp/              fab.db
  hypotheses.json        (도구 9종)                (배치 내부용)
  "일반적 원인"           "실제로 무슨 일이"
```

세 개의 하위 프로젝트가 하나의 파이프라인으로 연결된다. 원래 팀원별 개별 저장소였으나 2026-07-13에
공동작업을 위해 이 저장소 아래로 물리 이동했다(자체 `.git` 없음 — 전부 이 repo 하나의 히스토리).
루트 `pyproject.toml` 하나로 세 곳의 파이썬 의존성을 통합 관리한다.

| 폴더 | 역할 | 상태 |
|---|---|---|
| `backend/` | FastAPI + LangGraph 오케스트레이션. 파이프라인 ⓪~⑥ 실행 + API 8종 제공 | API 8종 구현 완료 |
| `frontend/` | React + TypeScript 대시보드 3화면 + 근거 모달 | 구현 완료 |
| `kg_rca/` | GraphRAG. 도메인 문헌 → Neo4j 적재 → LLM KG 추출 → 결정적 순회로 원인 후보 생성 | 완성, 계속 갱신 중(v2.4) |
| `secsgem-mcp/` | MCP 서버. SECS/GEM 시뮬레이터가 만든 가상 fab 데이터(`fab.db`)를 9종 도구로 조회 | 완성 |

### 데이터가 흐르는 방식

**빌드타임** — `kg_rca`가 문헌에서 원인 후보를 미리 계산해 `hypotheses.json`으로 저장하고
(현재 642건: Center 297 · Edge-Ring 249 · Scratch 96), `secsgem-mcp`의 시뮬레이터가 웨이퍼맵
데이터셋 + 가상 팹 모델로 `fab.db`를 생성한다. 런타임에 Neo4j는 필요 없다.

**런타임** — 배치 실행 시 파이프라인이 두 산출물을 교차 검증한다.

```
⓪ 저수율 로트 선별   fab.db 직접 SQL — 직전 배치 이후 누적 구간
① 웨이퍼맵 판독      (VLM 미연동 — pattern="Center" 고정)
② 패턴별 그룹화      로트별 다수결 대표패턴
③ 원인 후보 조회     kg_rca hypotheses.json  ← "일반적으로 이런 원인"
④ 증거 수집         MCP 9종 도구 실호출      ← "이번에 실제로 무슨 일이"
⑤ 검증             시간정합·반대증거·faithfulness·KG메커니즘 4규칙
⑥ 응답 생성         대표 원인 정렬 → 카드 조립
```

**fab.db 접근 경로가 둘로 갈리는 이유**: 에이전트가 "확인"하는 경로(④⑤)는 MCP를 거친다 — MCP
도구는 어떤 웨이퍼가 무슨 결함인지(정답 라벨)를 절대 반환하지 않아, 분석이 정답을 커닝하는 것을
구조적으로 막는다. 반면 ⓪ 저수율 선별이나 수율 차트 집계는 시스템 내부 준비 작업이라 그 제약이
필요 없고 SQL 한 번이 훨씬 빠르다.

## 현재 상태 (2026-07-20)

- **API 계약 8종 + 프론트 3화면 구현 완료.** 백엔드 테스트 11건 통과, 프론트 TypeScript strict
  빌드 통과, 실서버 curl 스모크 통과.
- **실데이터 end-to-end는 미검증** — `secsgem-mcp/datasets/fab.db`가 없다. 파일이 생기면 코드
  수정 없이 동작한다(`.env`에 경로가 이미 잡혀 있음).
- 파이프라인 자체는 2026-07-14에 실데이터로 검증됨(Center 그룹 297건 후보 → 163건 채택 / 134건
  기각). 단 HTTP를 거치지 않은 직접 호출이라, 현재 구조(비동기 배치)로는 재검증이 필요하다.
- **VLM(①)과 응답생성(⑦)은 실제 모델 미연동** — 하드코딩/템플릿. 그래서 지금은 Center 그룹
  하나만 생성된다.

## 설치 · 실행

```bash
# 설치
pip install uv
uv venv && uv sync            # 루트 pyproject.toml 하나로 파이썬 의존성 전부
.venv\Scripts\activate         # Windows. macOS/Linux: source .venv/bin/activate
cp .env_example .env           # 상대경로는 이미 맞춰져 있음. OPENAI_API_KEY만 채우면 됨
cd frontend && npm install && cd ..
```

터미널 두 개로 띄운다.

```bash
uvicorn backend.main:app --reload     # 터미널 1 → :8000
cd frontend && npm run dev            # 터미널 2 → :5173
```

브라우저는 **`http://localhost:5173`**으로 연다(백엔드 단독 확인은 `http://localhost:8000/docs`).

`secsgem-mcp/datasets/fab.db`가 없으면 `secsgem-mcp/README.md`의 "데이터 준비" 절차를 먼저 돌린다
(원천 데이터는 **WM-811K 하나** — MixedWM38은 팀 결정으로 제외). fab.db 없이 띄우면 수율 차트는
에러 안내, 대기열은 빈 목록, 배치는 접수 후 실패로 표시된다 — 전부 의도된 방어 동작이다.

테스트:

```bash
pytest -q -m "not data" backend    # 11건 — fab.db 없이 도는 계약 스모크
cd frontend && npm run build       # 타입체크 + 빌드
```

## API 8종

Base URL `http://localhost:8000/api/v1` (+ `GET /health`). 계약 정본은 `docs/API_명세서_v1.0.md`.

| 엔드포인트 | 역할 | 화면 |
|---|---|---|
| `GET /yield-summary` | 최근 7일 수율 추이(2시리즈) | 1 대시보드 |
| `GET /analyses` | 분석 결과 대기열 | 1 대시보드 |
| `POST /batches` | 배치 실행 — 202 즉시 반환, 백그라운드 실행 | 1 대시보드 |
| `GET /batches/{id}` | 배치 진행 상태 (폴링 대상) | 2 진행 |
| `GET /analyses/{id}` | 분석 결과 상세 (가설 카드) | 3 결과 |
| `GET /lots/{id}/wafers` | 로트 판독 웨이퍼 목록 | 3 결과 |
| `GET /lots/{id}/wafers/{wid}/die-map` | 웨이퍼맵 PNG (유일한 비-JSON 응답) | 3 결과 |
| `GET /analyses/{id}/evidence/{hid}` | 근거 3섹션 | 근거 모달 |

**배치가 비동기인 이유**: 파이프라인이 MCP를 수백 번 호출해 수 분씩 걸린다. 동기로 처리하면 화면이
멈추므로 접수만 하고 즉시 `batch_id`를 반환하고, 프론트가 1.5초 간격으로 폴링해 진행 단계와 도구
호출 로그를 갱신한다. 실행 실패도 HTTP 500이 아니라 `200 + status:"failed"`로 준다(폴링 루프가
200을 기대하기 때문).

## 문서 인덱스

| 궁금한 것 | 문서 |
|---|---|
| 백엔드 구조·모듈·설계 포인트·알려진 버그 | `backend/README.md` |
| API 계약 (정본) | `docs/API_명세서_v1.0.md` |
| 개발 규칙·읽기 지도·수정 금지 영역 | `docs/AGENT_GUIDE.md` |
| 계약 밖 내부 정책 결정 12건 | `docs/BACKEND_DECISIONS.md` |
| 남은 갭 목록 | `docs/BACKEND_GAP.md` |
| 기획 전체(배경·차별점·평가방법·타임라인) | `docs/semiconductor_proposal.md` |
| KG 스키마 (정본) | `docs/KG_schema_v1.2.md` |
| `hypotheses.json` 출력 필드 명세 | `kg_rca/KG_output_명세.md` |
| KG 진행상황·남은 문제 | `kg_rca/STATUS.md` |
| MCP 9종 도구 상세 계약·fab.db 스키마 | `secsgem-mcp/README.md` |
| Git 컨벤션 | `docs/git_convention_v0.2.md` |

## 로드맵

1. **fab.db 빌드 → 실데이터 E2E 검증** (유일한 블로커). WM-811K 확보 후 `docs/AGENT_GUIDE.md`
   §3의 슬라이스별 curl + 화면 확인.
2. **VLM(①) 실연동** — 지금 패턴이 고정이라 Edge-Ring/Scratch/`Unknown`(미매핑) 경로가 실데이터로
   검증되지 않는다. Qwen3-VL 연동이 목표.
3. **잠정 결정 팀 리뷰** — `docs/BACKEND_DECISIONS.md` 12건과 명세 §4 미결정 3건. 계약이 바뀌면
   명세서 개정이 선행돼야 한다.

## Git 컨벤션 요약

브랜치는 `main` 하나만 쓴다(이슈 기반 브랜치 → PR → `main`, 직접 push 금지). 커밋 메시지는
`[Type] #이슈번호 제목` 형식(`Feat`/`Fix`/`Refactor`/`Docs`/`Chore`/`Test`). PR은 리뷰어 1명 승인
후 본인이 merge하고 병합 브랜치는 삭제한다. `--force` 푸시, `.env`·API 키·`fab.db` 커밋은 금지.
자세한 내용은 `docs/git_convention_v0.2.md`.
