# 코호트 카드 노출 제안 — "분석 참조 로트" 표기 (0728)

## 배경

- ⑤ Hypothesis의 **commonality 코호트**(#110, merge됨): 하루 단위 그룹(#97)은 그룹당
  1~2로트라 commonality 판별력이 없음(1로트면 통과 장비 전부가 "공통") → commonality
  **입력만** "그룹 로트 + 같은 패턴으로 판독됐던 최근 7일 로트(최대 8, EDS 최신순)"로 확장.
- 카드·yield_impact·시간정합(P2)은 종전대로 그룹 로트만 사용. 코호트는 내부 계산 전용이라
  **현재 화면에는 전혀 안 보인다** — evidence에 `cohort_size`/`cohort_days` 숫자만 스탬프됨.
- 정본: `docs/node_langraph_spec/node_spec_05_hypothesis.md` 부록 C.

## 제안 — 코호트를 "분석 참조 로트"로 카드에 노출

**소속로트에 합치지 않는다.** 소속로트 = 처분 대상(Hold 권고·yield_impact 계산 기준)이라,
과거 로트를 섞으면 ① 로트가 여러 카드에 중복 소속 ② 수율영향 이중 계산 ③ "재처분?" 혼란.
대신 **별도 필드**로 구분 표기:

```
소속 로트 (2/5): lot45629                      ← 처분 대상 (현행 유지)
분석 참조 (D-7 동일 패턴): lot44812, lot40400   ← 코호트 (신규 노출)
의심 장비: CLEAN-01 (참조 포함 3로트 공통)
```

효과: "오늘 로트 1개여도 최근 7일 동일 패턴 이력과 교차해 공통 장비를 찾았다"는 추론
과정이 화면에 드러남 — commonality 근거의 설득력 + 설계(카드=운영 단위/추론=사건 단위
분리) 시각화.

## 작업 항목

### 백엔드 (소폭 — additive)

1. `hypothesis.py`의 코호트 스탬프 확장: 현재 `cohort_size`(int)·`cohort_days`(int)에
   **`cohort_lot_ids`(list[str], 그룹 로트 제외한 이력 로트만)** 추가.
   - 위치: `build_hypotheses` 끝 evidence 스탬프 루프 (defect_ts 스탬프 옆).
   - `_commonality_cohort` 반환은 "그룹 로트 + 이력 로트" 순서 보장이므로
     `comm_lot_ids[len(lot_ids):]`가 곧 이력 로트.
2. evidence → analysis payload 경로는 기존 그대로 통과(assembler가 evidence를 통째 보존).
   API 계약은 additive 필드라 v2.0 위반 없음.

### 프론트

1. 분석 상세(화면3) 카드에 "분석 참조 로트" 행 추가 — `hypotheses[].evidence.cohort_lot_ids`
   (대표로 top 가설 것 사용; 그룹 공통 값이라 어느 가설에서 읽어도 동일).
   비어 있으면(코호트 미형성 — 캐치업 배치·이력 없음) 행 자체를 숨김.
2. (선택) 근거 모달 commonality 섹션에 "최근 {cohort_days}일 동일 패턴 {cohort_size-소속수}로트
   포함" 캡션 — commonality 로트 수가 소속로트 수보다 큰 이유 설명.

## 확인 사항 (동작 전제)

- 코호트는 **캐치업 배치에서는 미형성**(판독 이력 저장이 배치 종료 시점이라 배치 내 날짜끼리는
  서로 못 봄) — 캐치업 이후 하루 단위 배치부터 형성됨. 화면 테스트는 캐치업 완료 후
  하루 전진 배치에서 할 것.
- 노출 대상은 로트 id뿐 — 정답성 정보(라벨·시나리오) 아님. 정답 누출 없음.
