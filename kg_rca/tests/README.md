# kg_rca 테스트 안내

KG 파이프라인(`6_ask_graphrag.py` → `outputs/hypotheses.json`)의 품질을 지키는 테스트 모음이다.

핵심 원칙 한 줄: **LLM의 출력값을 테스트하지 말고, 산출물이 지켜야 할 불변식과 계약을 테스트하라.**
가설 건수(772 등)나 문장 내용처럼 재생성마다 바뀌는 값은 절대 assert하지 않는다 — 대신 "타입이
맞나 / 정답을 후보에서 잃지 않았나 / 규칙을 지키나"를 본다.

전부 `fab.db`·Neo4j·LLM 없이 커밋된 산출물 파일만 읽으므로 **CI(`-m "not data"`)에서 그대로 돈다.**

---

## 한눈에 — 테스트 계층

| 계층 | 테스트 파일 | 무엇을 지키나 | 상태 |
|---|---|---|---|
| **L0 산출물 계약** | `test_hypotheses_contract.py` | 스키마·enum·어휘·라우팅·인용·랭킹 규칙 | ✅ 18건 |
| **L1 어휘 커버리지** | `test_recall_regression.py` | 시뮬레이터가 낼 수 있는 원인 전체를 후보로 아는가 | ✅ 11건(1 xfail) |
| **L2 시나리오 recall** | `test_scenario_recall.py` | 실제 11개 시나리오 정답을 후보에 올리는가 | ✅ 10건(1 xfail) |
| L3 순위 품질 | (미구현) | 정답이 상위 top-k에 오는가 (recall@k, MRR) | ⬜ 관측·fab 필요 → `-m data` |
| L4 검증 품질 | (미구현) | fab 재랭킹이 실제 원인을 위로 올리는가 | ⬜ `-m data` |
| L5 최종 응답 | (미구현) | LLM 답변의 정확성·근거성·인용 충실성 | ⬜ |

L0~L2는 "정답이 후보에 **있는가**"(존재)까지 본다. L3부터는 "정답이 **위에** 있는가"(순위)와
"실제로 **맞혔는가**"(검증)인데, 이건 관측(③)·fab.db(⑤)·LLM(⑦)이 필요해 `-m data`나 별도 평가로 뺀다.

---

## 폴더 구조

```
kg_rca/tests/
├── README.md                       ← 이 문서
├── conftest.py                     공용 fixture (matched_causes_by_pattern)
├── test_hypotheses_contract.py     L0 — 산출물 계약
├── test_recall_regression.py       L1 — 어휘 커버리지
├── test_scenario_recall.py         L2 — 시나리오 recall
├── golden/
│   └── recall_cases.yaml           정답 원인 9쌍 + 임계값 (committed 스냅샷)
└── ground_truth/
    └── SC-*.json (11개)             시뮬레이터가 낸 시나리오 정답지 (committed 스냅샷)
```

## 실행

```bash
pytest kg_rca/tests -q                 # 전체
pytest kg_rca/tests -q -m "not data"   # CI와 동일 (지금은 결과 같음 — data 마커 테스트 아직 없음)
pytest kg_rca/tests/test_scenario_recall.py -v   # 한 파일만
```

---

## L0 — 산출물 계약 (`test_hypotheses_contract.py`, 18건)

`hypotheses.json`을 세션 fixture로 한 번 로드해, 산출물이 지켜야 할 불변식을 검사한다.
백엔드의 API contract test / 데이터 파이프라인의 data-quality test와 같은 발상이다.

| 묶음 | 검사 | 왜 |
|---|---|---|
| **스키마·enum** | `tier`∈{자동,반자동,근거없음}, `scenario_hint`∈{A2,A3,A5,A6,None}, `fab_table`∈{telemetry,maintenance,lot_history,None}, `evidence_label`, `occurrence_prior` | 오타가 조용한 분기 오류로 새는 걸 막는다 |
| **어휘 폐쇄성** | `pattern` 3종 · `path.step` ProcessStep 6종 · Parameter 후보의 `evidence`가 시드 21종 안 | CLAUDE.md가 "고정 vocabulary"라 선언한 걸 코드로 강제. 시드 밖 param은 fab 조인 실패(X1E 유형 사고) |
| **라우팅 진리표** | `evidence_label`=Parameter⇒자동·A3·telemetry / Recipe⇒반자동·A5·lot_history / Maintenance⇒반자동·A2\|A6·maintenance / None⇒근거없음 | `KG_output_명세.md`의 표를 그대로 assert. 파생 필드가 어긋나면 ⑤가 잘못 라우팅 |
| **인용 무결성** ★ | `chunk_ids`가 chunks.jsonl에 실존 + **지어낸 인용 탐지**(3단계 grounding) + verbatim 비율 하한 | LLM이 없는 인용을 지어냈는지 자동 탐지. Critic D3의 전제를 빌드타임에 보장 |
| **랭킹 계약** | 배열이 (occurrence_prior, evidence_docs, evidence_chunks) 내림차순 + cause 이름 tiebreak · `rank`는 1..n 연번 | "실행마다 순서가 바뀌지 않게"(명세)를 검증 |
| **신선도(경량)** | `meta.generated_at`이 있는가 | 낡은 산출물을 조용히 쓰는 사고의 최소 방어 |

**인용 무결성이 제일 강력하다.** 인용문을 3단계로 판정한다 — ①원문 그대로(verbatim) → ②`...`로
이은 생략 → ③머리말+항목 재구성(모든 토큰이 원문에 있음). 셋 다 실패하면(=원문에 없는 단어가
섞이면) **조작으로 fail**. 07-23 산출물 기준 762 verbatim / 33 생략 / 24 재구성 / **조작 0건**이고,
verbatim 비율(93%)이 85% 밑으로 떨어지면 별도로 경보한다(의역이 늘었다는 신호).

> 미구현: `param_in_fab_vocab`이 `fab_model.yaml`에 실재하는지 보는 cross-component 검사는 fab 빌드가
> 필요해 뺐다(`-m data` 후보). mtime 기반 신선도 비교도 아직 없다.

---

## L1 — 어휘 커버리지 (`test_recall_regression.py`, 11건 · 1 xfail)

**"시뮬레이터가 낼 수 있는 모든 정답 원인을 KG가 후보로 떠올리는가."**

`golden/recall_cases.yaml`의 9쌍(패턴 3종 × 원인 3종)을 골든셋으로, 각 원인이 그 패턴의 KG 후보
`matched_cause`에 **한 번이라도** 존재하는지 본다. 순위는 안 보고 **존재(coverage)만** 확인한다.

- **목적은 절대 성능이 아니라 "떨어지면 알림"**이다. KG를 재빌드했더니 정답 원인이 후보에서
  사라지면(예: 8/9 → 7/9) 빨간불. "재빌드가 KG를 개선한 게 아니라 망가뜨렸다"는 신호.
- 대조 키는 `matched_cause`다(`cause` 아님). KG cause 문자열과 시뮬레이터 어휘는 표기가 달라
  직접 비교하면 0%가 나오고, `mapping.matched_cause`가 둘을 잇는 번역 키다.

---

## L2 — 시나리오 recall (`test_scenario_recall.py`, 10건 · 1 xfail)

**"이번에 실제로 준비된 11개 시나리오의 정답을 KG가 후보에 올리는가."**

L1이 "낼 수 **있는**" 원인 전체(어휘)를 보는 데 비해, L2는 `ground_truth/*.json`이 **실제로 주입한**
정답(`true_root_causes`)만 본다. 더 실전에 가까운 숫자다.

> **L1 vs L2** — Edge-Ring의 가능한 원인이 A·B·C라면:
> L1은 A·B·C를 KG가 모두 후보로 아는지 검사하고, L2는 이번 시나리오의 정답이 B라면 B만 검사한다.

`test_scenario_causes_covered_by_golden`은 **golden ⊇ 시나리오 정답** 정합도 함께 지킨다 —
시뮬레이터에 원인을 추가하고 ground_truth를 재빌드했는데 golden을 안 고치면 여기서 걸린다.

---

## 데이터 자산

| 파일/폴더 | 무엇 | 출처 |
|---|---|---|
| `golden/recall_cases.yaml` | 정답 원인 9쌍 + `coverage_min` 임계값 + `known_miss` 표시 | secsgem-mcp `mapping_table.yaml`에서 도출한 스냅샷 |
| `ground_truth/SC-*.json` | 11개 시나리오 정답지(정답·함정·증거 경로) | 시뮬레이터 `generate.py` 산출(seed 20260101) |
| `conftest.py` | `matched_causes_by_pattern` — KGClient로 패턴별 matched_cause 집합 | L1·L2 공유 |

**둘 다 committed 스냅샷이다.** 컴포넌트 경계를 넘지 않으려고 테스트는 secsgem-mcp를 **런타임에
읽지 않는다** — golden과 ground_truth가 kg_rca 내부의 로컬 진실이고, 둘의 정합은 L2가 지킨다.
시뮬레이터를 다른 seed로 재빌드하면 스냅샷이 표류할 수 있으니, 그때는 두 자산을 다시 뽑아야 한다.

### `known_miss` 장치 (strict xfail)

`cmp_edge_overpolish`(Edge-Ring)는 지금 KG가 후보로 못 올린다 — KG 지식 부재가 아니라 **매핑 매칭
실패**다(`localized_over_polish` 등 동일 원인이 후보엔 있으나 `matched_cause`로 번역 안 됨). 이걸
golden에 `known_miss: true`로 표시하고 **strict xfail**로 둔다. 나중에 매핑이 고쳐져 이게 recall되기
시작하면 xfail이 XPASS로 뒤집혀 **오히려 실패한다** → "golden의 known_miss 표시를 걷어내라"는 알림.
조용히 좋아진 것도 놓치지 않으려는 장치다. (실제 SC-EDGE-RING-03의 정답이 이 원인이라, 이 시나리오는
현재 end-to-end로 못 맞힌다.)

---

## 앞으로 (L3~L5)

- **L3 순위 품질(recall@k)** — 정답이 top-k 안에 오는가. 단, raw `hypotheses.json`은 문헌 빈도순이라
  정답이 rank 35~367에 있어 파일 순서로는 recall@20=0이 나온다. 실제 순위는 ③ 관측 morphology
  재랭킹 + ⑤ fab 재랭킹이 만드므로 **관측/fab이 필요한 `-m data` 테스트**여야 한다.
- **L4 검증 품질** — SC-CENTER-01 파이프라인 골든: top-1 달성 + 함정 P2(시간 역전) 기각까지.
  ⑤/⑥ + fab.db 필요 → `-m data`.
- **L5 최종 응답** — ⑦ LLM 답변의 정확성·groundedness·인용 충실성 평가.
