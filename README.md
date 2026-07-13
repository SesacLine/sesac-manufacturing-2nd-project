# SesacLine SemiRCA — 백엔드 스켈레톤

FastAPI + LangGraph로 ⓪~⑥ RCA 파이프라인을 오케스트레이션하는 백엔드.
`kg_rca`(GraphRAG)와 `secsgem-mcp`(MCP 9종 도구)를 잇는 자리다.
둘 다 0713부터 이 repo 밑의 평범한 하위 폴더로 들어와 있다(공동작업 편하게 하려고 옮기면서
각자 갖고 있던 `.git`은 지웠다 — 이 repo를 git init하면 안의 파일까지 그대로 하나의 히스토리로 잡힌다).

지금은 **스켈레톤 단계**다 — 함수 시그니처와 데이터 흐름만 잡혀 있고, 실제 로직은
`raise NotImplementedError`로 비어 있다. 배경·용어·작업 순서는
`personalspace/0713 work/skeleton_kickoff.md`를 먼저 읽는다.

## 구조

```
backend/
  state.py          # RCAState — 파이프라인 전체가 공유하는 상태 타입
  main.py           # FastAPI 진입점 (배치 트리거 1개)
  graph.py          # LangGraph StateGraph 조립 (⓪~⑥ 노드 연결)
  nodes/
    lowyield.py      # ⓪ 저수율 로트 선별 (결정적 함수)
    vlm.py           # ① VLM 웨이퍼맵 판독 (LLM 호출)
    grouper.py       # ② 패턴별 그룹화 (결정적 함수)
    graphrag.py      # ③ kg_rca 원인후보 조회 (결정적 조회, LLM 없음)
    hypothesis.py    # ④ Hypothesis 노드 (결정적 함수, LLM 없음)
    critic.py        # ⑤ Critic 노드 (결정적 함수, LLM 없음)
    response.py      # ⑥ 응답생성 (LLM 호출)
  mcp_client/        # secsgem-mcp 9종 도구 클라이언트
  graph_client/      # kg_rca 결과 조회 클라이언트
kg_rca/               # GraphRAG (0713부터 하위 폴더, 평범한 폴더 — 자체 .git 없음)
secsgem-mcp/          # MCP 서버 9종 도구 + fab.db (0713부터 하위 폴더, 평범한 폴더 — 자체 .git 없음)
```

파이프라인에서 LLM을 실시간 호출하는 노드는 ①VLM과 ⑥응답생성 둘뿐이다. ③~⑤는 전부
결정적 함수다(2026-07-09 노드화 결정 — 상세는 `semiconductor_proposal.md` §2/§7 참고).

## 의존 관계

- `kg_rca/`가 미리 계산해 둔 `outputs/hypotheses.json`을 읽는다(③).
- `secsgem-mcp/`의 MCP 서버를 stdio로 붙여 9종 도구를 호출한다(④⑤).
- 둘 다 0713부터 이 repo 밑의 하위 폴더로 물리적으로 들어와 있다(`kg_rca/`, `secsgem-mcp/`).
  각자 갖고 있던 `.git`은 0713에 지웠다(팀 결정 — 히스토리 병합보다 단일 repo로 공동작업하는
  쪽을 택함) — 그래서 이 repo에서 `git init` 후 `git add -A`를 하면 두 폴더 안 파일까지
  전부 하나의 커밋 히스토리로 들어간다. (`kg_rca`/`secsgem-mcp` 각자의 이전 커밋 기록은
  더 이상 로컬에 없으니, 필요하면 옮기기 전 원본 repo에서 따로 백업해 둘 것.)

## 설치

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv/Scripts/activate
pip install -r requirements.txt
cp .env_example .env   # 이미 채워진 상대경로(./kg_rca, ./secsgem-mcp) 그대로 쓰면 됨
```

## 실행 (스켈레톤 상태 — 아직 대부분 NotImplementedError)

```bash
uvicorn backend.main:app --reload
```

## 알려진 미해결 사항

- `mapping_table.yaml`(fab.db 시나리오 근거)과 kg_rca cause 어휘가 대부분 안 겹친다 —
  `personalspace/0711 work/kg_mapping_vocabulary.md` 참고. Center 패턴부터 검증 권장.
- 그룹 팬아웃(순차 loop vs LangGraph Send API), 저수율 임계값 등은 아직 팀 결정 전이라
  가장 단순한 기본값을 가정하고 TODO로 표시해 뒀다.
