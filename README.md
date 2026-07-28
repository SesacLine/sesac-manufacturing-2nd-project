# SesacLine SemiRCA

**지식그래프(KG) × Fab 운영데이터 기반 웨이퍼맵 결함 근본원인분석(RCA) 시스템** — SeSAC 2nd Project.

반도체 팹에서 수율이 떨어진 로트가 나오면, 엔지니어는 "이 결함 패턴이 왜 생겼는지"를 장비 이력·
센서값·정비 기록을 뒤져가며 찾아야 한다. 이 시스템은 그 과정을 자동화한다. 수율 엔지니어가
대시보드에서 **"오늘 판독 배치 확인"** 버튼 하나를 누르면:

1. 저수율 로트를 골라 웨이퍼맵 결함 패턴을 판독(CNN)하고 패턴별로 묶은 뒤,
2. **지식그래프**(문헌 기반 — "이런 결함은 일반적으로 이런 원인이 있을 수 있다")와
   **MCP 서버**(fab.db 기반 — "이번에 실제로 무슨 일이 있었나")를 교차 검증해,
3. 근거가 붙은 원인 후보 카드를 만들어준다.

핵심은 **"확정"이 아니라 "근거 있는 가설"까지가 스코프**라는 것이다. 채택된 가설마다 공통 장비
집계·센서 시계열·정비 이력을 근거로 함께 보여주고, 반대 증거(정상 로트가 그 장비를 많이 통과했다면)
와 시간 정합(원인이 결함보다 늦게 일어났다면)으로 기각된 후보도 사유와 함께 남긴다. 응답에도
확신 수준(`confidence`)은 `medium|low`뿐 — "high(확정)"는 설계상 존재하지 않는다.

> **용어 주의**: 기획안 v1.5부터 이 시스템을 "GraphRAG"라고 부르지 않는다(동적 커뮤니티 요약 기법을
> 쓰지 않고, 정적 KG를 빌드타임에 순회해 둔 결과를 런타임에 조회만 하기 때문). 다만 코드 식별자에는
> 옛 이름이 남아 있다(`backend/nodes/graphrag.py` 등) — 읽을 때 혼동하지 말 것.

## 아키텍처

```
                     [React 대시보드 (:5173)]
                              │ HTTP (API 10종, /api/v1)
                              ▼
                     [FastAPI + LangGraph (:8000)]
                       │            │
              ┌────────┤            └─ wafer_reading/ (CNN ResNet-18 · 스택맵 · 정량 관측)
      ┌───────┴────────┼────────────────────────┐
      │ 파일 읽기       │ MCP (stdio 서브프로세스) │ 직접 SQL
      ▼                ▼                        ▼
  kg_rca/          secsgem-mcp/              fab.db
  hypotheses.json  (도구 9종)                (배치 내부용)
  "일반적 원인"     "실제로 무슨 일이"
```

다섯 개의 하위 프로젝트가 하나의 파이프라인으로 연결된다. `backend`/`kg_rca`/`secsgem-mcp`는 원래
팀원별 개별 저장소였으나 2026-07-13에 공동작업을 위해 이 저장소 아래로 물리 이동했다(자체 `.git`
없음 — 전부 이 repo 하나의 히스토리). 루트 `pyproject.toml` 하나로 파이썬 의존성을 통합 관리한다.

| 폴더 | 역할 | 상태 |
|---|---|---|
| `backend/` | FastAPI + LangGraph 오케스트레이션. 파이프라인 ⓪~⑦ 실행 + API 10종 제공 | v1.5 구조 + API v2.0 구현 완료 |
| `frontend/` | React + TypeScript 대시보드 3화면 + 근거 모달 + 차트 | API v2.0 정합 구현(07-26) |
| `wafer_reading/` | 웨이퍼맵 판독 — CNN 분류(ResNet-18 5클래스)·그룹 스택맵·die-matrix→KG 어휘 관측 | 구현됨(체크포인트는 커밋 금지) |
| `kg_rca/` | 지식그래프. 도메인 문헌 → Neo4j 적재 → LLM KG 추출 → 결정적 순회로 원인 후보 생성 | 완성, 계속 갱신 중 |
| `secsgem-mcp/` | MCP 서버. SECS/GEM 시뮬레이터가 만든 가상 fab 데이터(`fab.db`)를 9종 도구로 조회 | 완성 |

### 데이터가 흐르는 방식

**빌드타임** — `kg_rca`가 문헌에서 원인 후보를 미리 계산해 `hypotheses.json`으로 저장하고
(07-22 재빌드 기준 772건: Center 375 · Edge-Ring 290 · Scratch 107 — 재생성마다 변동, 정본은
`kg_rca/STATUS.md` §1), `secsgem-mcp`의 시뮬레이터가 WM-811K 웨이퍼맵 + 가상 팹 모델로 `fab.db`를
생성한다. 런타임에 Neo4j는 필요 없다.

**런타임** — 배치 그래프(전 그룹 공통) + 그룹 서브그래프(패턴 그룹당 1회)의 2층 구조가
두 산출물을 교차 검증한다.

```
[배치 그래프]
⓪ 저수율 로트 선별     fab.db 직접 SQL — 직전 배치 이후 누적 구간
① 웨이퍼맵 판독(CNN)   ResNet-18 5클래스(Center/Edge-Ring/Scratch/Unknown/Normal) — 체크포인트 없으면 "Center" 폴백
② 패턴별 그룹화        로트별 다수결 대표패턴 (Normal은 그룹 미생성 — 별도 수집)
③ 그룹 관측(VLM)      스택맵 die-matrix → KG 어휘(signature 등) 실연동 · VLM 자연어는 미연동

[그룹 서브그래프 — 그룹마다 실행]
④ KG 원인 후보 조회    hypotheses.json           ← "일반적으로 이런 원인"   (후보 0건 → 즉시 응답)
⑤ 증거 수집·검증·재랭킹  자동 tier LLM 조사관 + MCP 도구  ← "이번에 실제로 무슨 일이"
⑥ 검증(Critic)        시간정합·반대증거·faithfulness·KG메커니즘 4규칙 (LLM 없음, 결정론)  (채택 0건 → 즉시 응답)
⑦ 응답 생성           카드 조립 (현재 템플릿 — LLM 연동 예정)
```

후보 0건(unmapped)·채택 0건(insufficient)이면 응답 노드로 가는 경로 자체가 그래프에 없다(조건부
엣지) — LLM이 재료 없이 문장을 쓰는 경로를 위상적으로 차단한다. 한 그룹이 예외로 죽어도 그 그룹만
스킵하고 배치는 완료된다(그룹 고장 격리).

**fab.db 접근 경로가 둘로 갈리는 이유**: 에이전트가 "확인"하는 경로(⑤⑥)는 MCP를 거친다 — MCP
도구는 어떤 웨이퍼가 무슨 결함인지(정답 라벨)를 절대 반환하지 않아, 분석이 정답을 커닝하는 것을
구조적으로 막는다. 반면 ⓪ 저수율 선별이나 수율 차트 집계는 시스템 내부 준비 작업이라 그 제약이
필요 없고 SQL 한 번이 훨씬 빠르다.

## 현재 상태 (2026-07-26)

- **파이프라인 ⓪~⑦ v1.5 구조 구현 완료**(07-23) — 그룹 서브그래프 + 조건부 엣지 2종, CNN
  실연동(#39), ⑤ Hypothesis(자동 tier LLM 조사관·방향 대조·클러스터·fab 재랭킹·스텝 상한)·
  ⑥ Critic(4규칙 + 미조사 보류) 고도화. **ground truth E2E 평가로 SC-CENTER-01 근본원인 top-1
  달성**(정답 193위 rejected → top-1 accepted, 함정 시간역전 44건 기각). 나머지 10개 시나리오는 미완.
- **API 계약 v2.0 10종 구현 완료**(07-25) — 차트 2종(`/yield-daily`·`/stats/causes`) 추가,
  `confidence`(R1)·`yield_impact`·`actions`(권장 조치 구조화)·`novel`(미지 패턴 OSR) 확장.
  서버 "오늘"은 `EVENT_DATE`(기본 2026-04-01, env 오버라이드) — 데이터가 1~3월분이라 벽시계를 쓰지 않는다.
- **프론트 v2.0 정합 1차 구현**(07-26) — 대기열 수율영향·확신 컬럼(수율영향순 정렬), 원인군(R2)
  카드·채택 유력/보조 플래그·OCAP 권장 조치, 일별 수율+이벤트·장비 도넛·패턴 Pareto 차트.
- **실데이터 end-to-end는 미검증** — `secsgem-mcp/datasets/fab.db`가 없다. 파일이 생기면 코드
  수정 없이 동작한다(`.env`에 경로가 이미 잡혀 있음).
- **미연동 잔여**: ③ VLM 자연어(관측의 die-matrix 성분만 실연동 — 파인튜닝 없이 VLM API +
  few-shot 예정), ⑦ 응답 LLM(현재 템플릿), ① CNN 학습 체크포인트(없으면 "Center" 폴백 —
  폴백 중엔 그룹이 1개만 생긴다).

## 설치 · 실행

6가지 준비물 중 실제로 **필수인 건 4개뿐**이다 — Neo4j·CNN 학습은 "완성된 걸 그냥 돌려보는" 데는
필요 없다. 이 구분이 안 되어 있으면 전부 필수처럼 보여서 헤매기 쉽다.

| 준비물 | 필수 여부 | 이유 |
|---|---|---|
| 파이썬 환경(`uv sync`) | **필수** | 없으면 백엔드·스크립트 자체가 안 돌아감 |
| `.env` 설정 | **필수** | 최소 `OPENAI_API_KEY` 하나만 있으면 됨 |
| `fab.db` 생성(WM-811K + 시뮬레이터) | **필수** | 없으면 배치·MCP 도구가 읽을 데이터가 없음 |
| Neo4j + KG 재빌드(`kg_rca` 0~7번) | 선택 | `hypotheses.json`이 이미 커밋돼 있어 기본값은 이 파일만 읽음(Neo4j 미접속) — KG를 새로 만들 때만 |
| CNN 체크포인트 학습 | 선택 | 없으면 전부 "Center"로 판정하는 폴백 — 서비스는 그래도 돌아감 |
| `frontend`의 `npm install` | **필수** | |

> Neo4j는 서비스를 **실행**하는 데 필수가 아니다. 문헌·KG 스키마를 고쳐 `hypotheses.json`을
> 다시 만들 때만 필요하다 — `backend/deps.py`의 `KG_LIVE` 게이트가 기본 미설정이면 이 파일만
> 조회하고 Neo4j는 아예 안 건드린다.

### A. 최소 실행 — 서비스만 띄우기

```bash
# 1. 파이썬 환경
pip install uv
uv venv && uv sync            # 루트 pyproject.toml 하나로 파이썬 의존성 전부
.venv\Scripts\activate         # Windows. macOS/Linux: source .venv/bin/activate

# 2. 환경변수 — OPENAI_API_KEY만 채우면 됨(상대경로는 이미 맞춰져 있음)
cp .env_example .env
```

```powershell
# 3. fab.db 생성 (WM-811K 다운로드 → 시뮬레이터 빌드, Windows PowerShell)
curl.exe -L -o ..\MIR-WM811K.zip http://mirlab.org/dataSet/public/MIR-WM811K.zip
Expand-Archive -Path ..\MIR-WM811K.zip -DestinationPath ..\ -Force
New-Item -ItemType Directory -Force secsgem-mcp\datasets\raw
Copy-Item ..\MIR-WM811K\Python\WM811K.pkl secsgem-mcp\datasets\raw\
cd secsgem-mcp
..\.venv\Scripts\python -m simulator.generate --wm811k datasets\raw\WM811K.pkl --out datasets --seed 20260101
cd ..
```

> ⚠️ `secsgem-mcp/README.md`의 `wget -P ..` 예시는 PowerShell에서 안 먹힌다(`wget`이
> `Invoke-WebRequest` 별칭이라 `-P` 플래그가 안 맞음) — 위처럼 `curl.exe`(`.exe`를 꼭 붙여야
> 별칭과 안 겹침) + `Expand-Archive`로 대체할 것. 원천 데이터는 **WM-811K 하나**(MixedWM38은
> 팀 결정으로 제외), 압축 파일이 2GB라 브라우저로 직접 받아도 된다.

```bash
# 4. 프론트 의존성
cd frontend && npm install && cd ..
```

터미널 두 개로 띄운다.

```bash
uvicorn backend.main:app --reload     # 터미널 1 → :8000
cd frontend && npm run dev            # 터미널 2 → :5173
```

브라우저는 **`http://localhost:5173`**으로 연다(백엔드 단독 확인은 `http://localhost:8000/docs`)
→ **"오늘 판독 배치 확인"** 클릭. fab.db 없이 띄우면 수율 차트는 빈 상태, 대기열은 빈 목록,
배치는 접수 후 실패로 표시된다 — 전부 의도된 방어 동작이다.

### B. KG를 새로 만들 때만 (선택 — Neo4j 필요)

`kg_rca` 문헌을 고치거나 스키마를 바꿔 `hypotheses.json`을 재생성할 때만 필요하다. 서비스
실행만 확인하려면 건너뛴다. 상세 절차는 `kg_rca/README.md` "준비"·"실행" 절이 정본이다 —
요약하면:

Neo4j는 **0728부터 AuraDB(관리형 클라우드)** 다 — 로컬 설치·Docker 기동 절차는 없어졌다.
[console.neo4j.io](https://console.neo4j.io)에서 받은 값을 `.env`에 넣는다(스킴이 `bolt://`가
아니라 **`neo4j+s://`**):

```ini
NEO4J_URI=neo4j+s://xxxxxxxx.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<콘솔 발급값>
NEO4J_DATABASE=neo4j
```

⚠️ env 파일은 **저장소 루트의 `.env` 하나뿐**이다(0728 통합). `kg_rca/.env`를 만들지 말 것 —
`find_dotenv()`는 cwd가 아니라 **호출한 `.py` 파일의 디렉터리**부터 위로 걷기 때문에, 그 파일이
있으면 kg_rca 스크립트가 실행 위치와 무관하게 그쪽을 집어 루트 `.env`가 통째로 무시된다.

접속 확인(`python kg_rca/1_test_connection.py`) 후, `kg_rca/` 안에서 `1_test_connection.py`부터
`6_ask_graphrag.py`(여기서 `hypotheses.json` 재생성)까지 번호 순서로 실행한다.
`7_build_signature_index.py`는 의미 진입용 선택 단계.

> 리빌드 중에는 `.env`의 `KG_LIVE`를 0으로 내려둘 것 — `0_reset.py`가 DB를 비우고 시작하므로
> 반쯤 적재된 그래프가 그대로 라이브 조회에 노출된다.

### C. CNN 학습할 때만 (선택)

체크포인트 없이도 서비스는 돌지만 전부 "Center"로 판정된다. Edge-Ring/Scratch를 실제로
갈리게 하려면(A의 `fab.db`·`WM811K.pkl`이 먼저 있어야 함):

```bash
python -m wafer_reading.classifier.train --pkl secsgem-mcp/datasets/raw/WM811K.pkl --fab-db secsgem-mcp/datasets/fab.db --out wafer_reading/classifier/checkpoints/resnet18_5cls.pt
```

### 목적별 가이드

| 목적 | 필요한 경로 |
|---|---|
| 서비스가 도는지만 확인 | A |
| 기존 KG로 백엔드·프론트 확인 | A |
| 문헌·KG 스키마 수정 후 가설 재생성 | A + B |
| 웨이퍼 패턴 분류 정확도까지 확인 | A + C |
| KG·CNN 둘 다 새로 구축 | A + B + C |

### 테스트

```bash
pytest -q -m "not data" backend/tests kg_rca/tests   # fab.db 없이 도는 스코프
cd secsgem-mcp && pytest -q -m "not data"            # 상대경로(cwd) 의존이라 자기 폴더에서 실행
cd frontend && npm run build                          # 타입체크 + 빌드
```

⚠️ 루트에서 `pytest` 한 방에 전부 돌리면 secsgem-mcp 테스트가 cwd 문제로 실패한다 — CI도 위처럼
스코프를 나눠 돈다(`.github/workflows`). `backend/tests`는 `e2e/`·`server/`·`unit/` 3분류로
나뉘어 있다(상세는 `backend/README.md`) — 그중 `e2e/`는 실LLM·실배치 비용이 들어 opt-in
환경변수(`HYPO_CRITIC_EVAL=1`, `BATCH_E2E=1`, `VLM_E2E=1`)를 줘야만 돈다.

## API 10종

Base URL `http://localhost:8000/api/v1` (+ `GET /health`). 계약 정본은 `docs/API_명세서_v2.0.md`
(v1.0은 이력 보존용 — 정본 아님).

| 엔드포인트 | 역할 | 화면 |
|---|---|---|
| `GET /yield-summary` | 최근 7일 수율 추이(2시리즈) | 1 대시보드 |
| `GET /analyses` | 분석 결과 대기열 (+confidence·yield_impact) | 1 대시보드 |
| `POST /batches` | 배치 실행 — 202 즉시 반환, 백그라운드 실행 | 1 대시보드 |
| `GET /batches/{id}` | 배치 진행 상태 (폴링 대상) | 2 진행 |
| `GET /analyses/{id}` | 분석 결과 상세 (가설 카드·권장 조치) | 3 결과 |
| `GET /lots/{id}/wafers` | 로트 판독 웨이퍼 목록 | 3 결과 |
| `GET /lots/{id}/wafers/{wid}/die-map` | 웨이퍼맵 PNG (유일한 비-JSON 응답) | 3 결과 |
| `GET /analyses/{id}/evidence/{hid}` | 근거 3섹션 | 근거 모달 |
| `GET /yield-daily` | 일별 수율 전 구간 + 이벤트 오버레이 (v2.0 §2.8) | 1 대시보드 |
| `GET /stats/causes` | 장비·원인·패턴 집계 (v2.0 §2.9) | 1 대시보드 |

**배치가 비동기인 이유**: 파이프라인이 MCP를 수백 번 호출해 수 분씩 걸린다. 동기로 처리하면 화면이
멈추므로 접수만 하고 즉시 `batch_id`를 반환하고, 프론트가 1.5초 간격으로 폴링해 진행 단계와 도구
호출 로그를 갱신한다. 실행 실패도 HTTP 500이 아니라 `200 + status:"failed"`로 준다(폴링 루프가
200을 기대하기 때문).

## 문서 인덱스

| 궁금한 것 | 문서 |
|---|---|
| 백엔드 구조·모듈·설계 포인트·알려진 버그 | `backend/README.md` |
| API 계약 (정본) | `docs/API_명세서_v2.0.md` |
| 노드별 설계 공유(골격·CNN·VLM관측·KG조회·Hypothesis·Critic·Response) | `docs/node_langraph_spec/` |
| 개발 규칙·읽기 지도·수정 금지 영역 | `docs/AGENT_GUIDE.md` |
| 계약 밖 내부 정책 결정 | `docs/BACKEND_DECISIONS.md` |
| 남은 갭 목록 | `docs/BACKEND_GAP.md` |
| 기획 전체(배경·차별점·평가방법·타임라인) | `docs/semiconductor_proposal.md` |
| KG 스키마 | `docs/KG_schema_v1.3.md` (repo 내 최신본) |
| `hypotheses.json` 출력 필드 명세 | `kg_rca/KG_output_명세.md` |
| KG 진행상황·남은 문제 | `kg_rca/STATUS.md` |
| MCP 9종 도구 상세 계약·fab.db 스키마 | `secsgem-mcp/README.md` |
| Git 컨벤션 | `docs/git_convention_v0.2.md` |

## 로드맵

1. **fab.db 빌드 → 실데이터 E2E 검증** (유일한 블로커). WM-811K 확보 후 배치 실행 + 화면 확인,
   ground truth 나머지 10개 시나리오 평가와 단일경로 baseline 비교까지.
2. **③ VLM 자연어·⑦ 응답 LLM 연동** — 파인튜닝 없음(기획안 v1.5 확정), VLM API + few-shot.
   CNN 학습 체크포인트 생성도 이 축(현재 폴백 모드).
3. **"판독상 정상 N로트" 전용 카드 배선** — grouper의 `normal_lots` 수집(#69)은 구현됐고,
   저장→API→프론트 노출은 판독 담당 진행 예정(status `normal_reading` 신설, 명세 개정 동반).
4. **잠정 결정 팀 리뷰** — `docs/BACKEND_DECISIONS.md`. 계약이 바뀌면 명세서 개정이 선행돼야 한다.

## Git 컨벤션 요약

브랜치는 `main` 하나만 쓴다(이슈 기반 브랜치 → PR → `main`, 직접 push 금지). 커밋 메시지는
`[Type] #이슈번호 제목` 형식(`Feat`/`Fix`/`Refactor`/`Docs`/`Chore`/`Test`). PR은 리뷰어 1명 승인
후 **해당 리뷰어가 merge**하고, 병합 브랜치는 삭제하지 않고 유지한다. `--force` 푸시, `.env`·API
키·`fab.db` 커밋은 금지. 자세한 내용은 `docs/git_convention_v0.2.md`.
