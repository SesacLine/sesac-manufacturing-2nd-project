# Git Convention (SesacLine_SemiRCA)

이전 프로젝트(v0.1, Java/IntelliJ 기준)를 이 프로젝트(Python/FastAPI 모노레포, 소규모 팀)에 맞춰 간소화한 버전이다.

## 브랜치 전략

- `develop` 없이 **`main` 하나만 유지**한다. 모든 작업은 이슈 기반 브랜치에서 시작해서 `main`으로 PR한다.
- `main`은 직접 push 금지 — 항상 PR을 통해서만 병합.

## PR 올리기 전 필수 확인

1. 작업 시작 전 본인 브랜치에 `main`을 pull 받는다(conflict 예방).
2. push 전에 로컬에서 최소한 아래를 확인한다.
   - `pytest` 통과 (`secsgem-mcp/tests`, 관련 있으면 `-m "not data"`)
   - 관련 있으면 `uvicorn backend.main:app --reload`로 기동 확인
   - GitHub Actions CI(`.github/workflows/ci.yml`) 통과 여부 확인
3. merge 시 conflict는 본인이 해결한다. 리뷰 승인 후 **리뷰어가 merge**하고, 병합된 브랜치는 **삭제하지 않고 그대로 둔다**(작업 이력 추적용).

## 금지 사항

- 강제 푸시(`--force`) 금지, `main` 직접 push 금지 — 꼬이면 팀원과 상의 후 재클론.
- `.env`, API 키, `fab.db` 등 비밀값/데이터는 절대 커밋 금지. `.gitignore`가 처리하지만 `git add` 후 `git status`로 한 번 더 확인한다.

---

## Commit Type

- `Feat` : 새로운 기능
- `Fix` : 버그 수정
- `Refactor` : 코드 리팩토링
- `Docs` : 문서 작업
- `Chore` : 설정, 패키지 구조, 변수명 등 자잘한 변경
- `Test` : 테스트 추가/수정

```
[Type] #이슈번호 제목

ex)
[Feat] #12 hypothesis 노드 tier 분기 구현
[Fix] #15 telemetry 정상범위 비교 방향 버그 수정
[Docs] #20 skeleton_kickoff 환경구축 파트 갱신
```

---

## Issue

```
[Type] 작업내용

ex)
[Feat] KG client 필드 매핑 구현
```

### 템플릿

```markdown
## 작업 내용
무엇을 할지 한 줄 요약

## TODO
1. [ ] task1
2. [ ] task2

## 참고
관련 문서/논의 링크 (있으면)

- Assignees: 본인 (assign yourself)
- Labels: 작업 유형
```

---

## Branch 명명

```
{type}/#이슈번호-작업내용   (작업내용은 영어 소문자 + 하이픈으로만, 한글 금지)

ex)
feat/#12-hypothesis-tier-branching
fix/#15-telemetry-range-compare
docs/#20-skeleton-kickoff-env-setup
```

---

## PR

- 제목: `[Type] 이슈 제목`
- **리뷰어 1명 승인** 후 해당 **리뷰어가 merge**
- merge 후에도 작업 브랜치는 삭제하지 않고 유지
- 컨플릭트나 리뷰 중 질문 사항은 팀 채널에 남긴다

### 템플릿

```markdown
## 개요
- closed #이슈번호
- 무엇을, 왜 변경했는지 한두 줄로

## 확인 방법
- [ ] pytest 통과
- [ ] (해당 시) uvicorn 기동 확인
- [ ] CI 통과

📣 To Reviewer
- 특히 봐줬으면 하는 부분이 있다면 작성
```
