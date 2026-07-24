# ⑦ generate_response / ⑦' respond_without_llm — 노드 설계 공유 문서

> 템플릿(`docs/# 노드 설계 공유 문서 템플릿 v1.md`) §0~§8 형식을 따른 판.
> 같은 파일 안의 두 함수(⑦ 정상 경로 / ⑦' LLM 없는 경로)를 한 문서에서 다룬다.

---

## 0. 요약

- **노드**: ⑦ generate_response(정상) + ⑦' respond_without_llm(후보 0건·채택 0건) — 그룹 서브그래프의 **마지막** 노드
- **파일**: `backend/nodes/response.py` (약 140줄)
- **담당**: (류은서)
- **한 줄 역할**: 앞 노드들이 만든 판정 결과를 **화면에 뿌릴 최종 카드 한 장**으로 조립한다. 이게 없으면 프론트가 받을 응답 자체가 없다.
- **이 노드가 하지 않는 일**: 채택/기각을 **판정하지 않는다**(그건 ⑥ Critic). 공장 데이터를 **보지 않는다**(그건 ⑤). 원인 후보를 **만들지 않는다**(그건 ④). 여기서는 이미 나온 결과를 **정리·번역·정렬**만 한다.
- **상태**: **거의 구현**.
  - ✅ 3가지 결과(reviewed / insufficient / unmapped) 분기, 가설 정렬·번호 부여, verdict 표시, `description` 배선 + **영어→한국어 번역(opt-in)**까지 동작.
  - ✅ `summary`는 **결정론적 템플릿**(내부용, LLM 안 씀 — 확정). 이 노드에서 LLM을 쓰는 유일한 곳은 description 번역.
  - 🔲 남은 건 **VLM을 실제로 돌리는 것**(§8) — 지금 평상시엔 VLM이 안 돌아 `description=None`(→ 프론트 summary_line). VLM을 켜고(`VLM_LIVE=1`) 번역을 켜면(`RESPONSE_LLM=1`) 한국어 서술이 뜬다.
- **작성일 / 대상 커밋**: 2026-07-24 / `97ca5f4` + 본 작업분(description 배선 + 번역 주입)

---

## 1. 입출력 계약

이 노드는 **그룹 하나짜리 상태**(`GroupState`, `backend/state.py`)를 받는다.

### 1-1. 입력

| state 키 | 타입 | 채우는 주체 | 없으면 / None이면 |
|---|---|---|---|
| `group_id` | `str` | 배치 그래프 | **필수** |
| `pattern` | `str` | ② grouper (← ① CNN) | **필수** |
| `lot_ids` | `list[str]` | 배치 그래프 | **필수** |
| `critic_result` | `CriticResult \| None` | ⑥ critic | None이면 채택·기각 전부 빈 것으로 취급 |
| `candidates` | `list[...]` | ④ graphrag | ⑦'에서 **unmapped ↔ insufficient를 가르는 스위치**로만 씀 |
| `observation` | `Observation \| None` | ③ vlm_describe | 없으면 서술(description) = None |

**`critic_result`에서 실제로 꺼내 쓰는 것**: `accepted`(채택 가설 목록), `rejected`(기각·보류 가설 목록). 각 가설 원소에서 `cause`·`tier`·`equipment`·`stage`·`sentence`·`reject_token`·`reject_reason`을 읽는다.

**`observation`에서 꺼내 쓰는 것**: `vlm_track`(VLM 실생성 여부 판별용)과 `total_description`(VLM이 쓴 **영어** 서술). `vlm_track`이 없으면 total_description이 있어도 **안 쓴다**(§4-2).

**전제조건**
- `generate_response`(⑦)는 **채택 가설이 1건 이상 있을 때만** 호출된다. 후보 0건·채택 0건 분기는 그래프의 조건부 엣지(`route_on_candidates`·`route_on_verdicts`)가 걸러 ⑦'로 보내므로 이 함수까지 오지 않는다.
- `pattern`은 KG 3종(Center/Edge-Ring/Scratch) 또는 그 밖(Unknown 등). `Normal`은 애초에 그룹이 안 생겨 여기 없다.

**가정이 깨지면**: 예외를 던지지 않는다. `critic_result`가 None이거나 목록이 비어도 조용히 "빈 목록" 카드를 만든다.

### 1-2. 출력

한 키 `final_response`(딕셔너리) 하나를 낸다. 이 값이 그대로 저장돼 API가 꺼내 쓴다.

| 필드 | 뜻 | 비고 |
|---|---|---|
| `group_id` / `pattern` / `lot_ids` / `lot_count` | 그룹 식별·범위 | 3가지 결과 모두 존재 |
| `status` | `reviewed`(채택 있음) / `insufficient`(후보는 있었으나 채택 0) / `unmapped`(애초에 후보 0) | 프론트가 결과 종류를 가르는 키 |
| `reason` | 결과 없음 안내 문구 | `reviewed`면 None, 나머지는 문구 있음 |
| `hypotheses` | 가설 카드 목록(정렬·번호·verdict 포함) | `unmapped`면 `[]` |
| `summary` | 내부용 한 줄 요약(고정 템플릿) | ⚠️ **현재 API로 안 나감**(§8) |
| `description` | 사용자 노출용 그룹 서술 | **VLM 실생성분만** 운반. 없으면 None → 프론트가 `summary_line`으로 대체 |

**하위(=API 조립 `assembler.py`)가 믿어도 되는 불변식**

1. `hypotheses`는 **항상 리스트**다(없으면 `[]`, None 아님).
2. 목록 **맨 앞(index 0)이 대표 가설**이다 — 채택된 것들을 앞에, 비채택을 뒤에 잇는다.
3. 각 가설에는 `hypothesis_id`가 `h0`, `h1`, … 순으로 붙는다. **정렬을 끝낸 뒤** 번호를 매기므로 `h0`이 곧 대표다(근거 모달이 `h0`부터 열려야 함, API §2.7).
4. 각 가설에는 `verdict`가 `accepted` / `rejected` / `judge_unknown` 중 하나로 붙는다.
5. `description`은 **VLM이 실제로 생성한 값**이거나 None이다. 스켈레톤/폴백으로 지어낸 문구는 **절대 나가지 않는다**(§4-2).

### 1-3. 새로 도입 / 변경한 필드

- `final_response`에 **`description` 키 추가**(본 작업분). 사용자 노출용 한국어 서술. 왜 필요했나 → API §2.5가 정의한 필드인데 그동안 `assembler.py`에서 `None`으로 하드코딩돼 있어, 실제 값이 API까지 흐르지 않았다.

---

## 2. 실패·경계 케이스 계약

| 이런 상황이면 | 이 노드는 | 하위가 보게 되는 것 |
|---|---|---|
| 후보가 애초에 0건 (Unknown 등) | ⑦'가 `unmapped` 카드 | "판독까지만 지원" 안내, `hypotheses=[]` (UC-3) |
| 후보는 있었으나 채택 0건 | ⑦'가 `insufficient` 카드 | "판단 불가(근거부족)" 안내 + 기각 가설 목록 (UC-2) |
| `critic_result`가 None | 빈 목록으로 취급, 예외 없음 | 빈 카드 |
| `observation` 없음 / **`vlm_track` 없음(스켈레톤·폴백)** | `description=None` | 프론트가 `summary_line`으로 대체 |
| (예정) 응답 LLM 호출 실패 | 현재 LLM 미연동이라 **해당 없음** | — |

- **예외를 던지는가?**: 아니오. 이 노드는 파이프라인의 끝이라, 여기서 죽으면 결과가 통째로 사라진다. **무슨 일이 있어도 카드 한 장은 만들어 내보낸다**는 원칙.
- **재시도·타임아웃**: 없음. 순수 조립 함수(외부 호출 없음).

---

## 3. 내부 플로우

```
critic_result를 받음
   │
   ├─(그래프 라우팅: 채택 ≥1)──→ ⑦ generate_response
   │        가설 정렬(대표=맨 앞) → h0,h1… 번호 → 한국어 서술 → "reviewed" 카드
   │
   └─(그래프 라우팅: 후보 0 / 채택 0)──→ ⑦' respond_without_llm
            candidates 비었나?
              ├─예 → "unmapped" 카드 (hypotheses=[])
              └─아니오 → 가설 정렬·번호(⑦과 동일 헬퍼) → "insufficient" 카드
```

- **가설 정렬 규칙**(두 경로 공통 헬퍼 `_ordered_hypotheses`): 채택된 것 먼저(원래 순서 유지) → 비채택(원래 순서 유지) → 각 원소에 verdict 부여 → **정렬 확정 후** `h{n}` 번호 부여.
- **verdict 판정**: 채택이면 `accepted`. 기각 중 기각 사유 토큰이 "보류 계열"(미조사·근거없음: `SEMI_AUTO_PENDING`·`NO_KG_MECHANISM`·`NOT_INVESTIGATED`)이면 `judge_unknown`, 그 외는 `rejected`. **자연어를 보고 판단하지 않고 토큰으로만** 가른다.
- **서술 운반+번역**(`_group_description(state, translate)`): observation에 `vlm_track`이 있으면(VLM 실생성) → `total_description`을 가져와, 번역기(`translate`)가 주입돼 있으면 한국어로 옮겨 싣고 없으면 원문(영어) 그대로. `vlm_track`이 없으면 → None. 번역 콜이 실패하면 원문(영어)으로 폴백.

---

## 4. 설계에서 중요하게 고려한 것

### 4-1. `summary`는 결정론적 템플릿으로 **확정**(LLM 안 씀)

- **문제**: 그룹 레벨 "원인 요약문"을 LLM으로 만들까 검토했으나, `summary`는 **어떤 소비처도 없다** — assembler가 안 읽고, API §2.5에 필드가 없고, 프론트가 참조 안 한다(grep 확인). 소비처 없는 값에 LLM(비용·비결정성·firewall 뒤 미검증)을 붙이는 건 손해.
- **선택**: `summary`는 `"Center 패턴 — 가설 2건 채택: …"` 같은 **결정적 템플릿**으로 남긴다(내부/디버그용). LLM 합성은 **안 한다**(팀 결정). 사용자 노출 자연어는 `description`(형상)·`hypotheses[].narrative`(가설별)가 담당.
- **되돌릴 조건**: `summary`를 실제 API 필드로 노출하기로 하면(명세 §2.5 + 프론트 수정) 그때 재검토.

### 4-2. 서술을 VLM 영어 전담 + 이 단계 운반으로 나누고, 지어낸 폴백은 노출 금지 ★(본 작업분)

- **문제 1(번역 위치)**: 사용자에게 보일 서술(`description`)은 최종적으로 한국어여야 한다. 그런데 VLM에게 "이 값만 한국어로 써라"라고 시키면 자주 어색하게/틀리게 처리하고 프롬프트도 복잡해진다.
- **선택 1**: **VLM(노드③)은 영어 서술만** 생산하게 두고(프롬프트 단순·출력 자연스러움), 한국어 번역은 **이 응답 단계**에서 한다. 번역기(`translate: str→str`)는 조립 시점 **partial 주입**(`deps.response_translator`, `RESPONSE_LLM=1`일 때만 실체) — `build_hypotheses`의 `mcp` 주입과 같은 관례. 이건 "생성"이 아니라 "옮기기"라 firewall과 충돌하지 않는다(evidence 밖 사실이 새로 안 생김).
- **문제 2(가짜 서술 방지)**: ③은 VLM이 없거나 실패하면 "그 패턴의 전형적 문구"를 **스켈레톤으로 지어내** total_description을 채운다. 이걸 그대로 사용자에게 보이면, VLM이 실제로 그 웨이퍼를 본 것도 아닌데 관측처럼 읽혀 오해를 준다(환각 억제 원칙 위배).
- **선택 2**: **VLM이 실제로 생성한 경우에만** 서술을 운반한다. 실생성 판별은 관측 메타 **`vlm_track` 존재**로 한다(이 키는 VLM_LIVE 경로가 성공했을 때만 붙는다). 없으면 무조건 `None` → 프론트가 결정적 `summary_line`으로 대체(명세 §2.5 동작 그대로).
- **폴백**: 번역기 미주입(기본/CI)이면 원문(영어) 운반 — 결정적, LLM 비용 0. 번역 콜이 실패해도 원문(영어) 보존 — 실제 관측 내용을 잃지 않게(곱게 무너짐).
- **남은 것**: 이제 코드는 다 됐고, 실제로 한국어 서술이 뜨려면 **VLM을 켜야** 한다(`VLM_LIVE=1` + `RESPONSE_LLM=1`, fab.db 필요). 평상시엔 vlm_track이 없어 `None` → summary_line.

### 4-3. ⑦와 ⑦'이 **같은 정렬 헬퍼**를 공유하는 것

- **문제**: 정상 경로와 "판단 불가" 경로가 각자 가설 목록을 만들면, 번호 매김 규칙이 어긋나 근거 모달이 엉뚱한 가설을 연다.
- **선택**: 두 경로가 `_ordered_hypotheses` 하나를 공유한다. 그래서 어느 경로로 나오든 `h0`부터 시작하고 대표가 맨 앞이라는 약속이 동일하게 지켜진다(테스트로 못 박음).

### 4-4. 마지막 노드는 예외를 던지지 않는다

- **문제**: 여기서 예외가 나면 그룹 결과가 통째로 사라진다.
- **선택**: `critic_result`가 None이든 목록이 비었든 조용히 빈 카드를 만든다. "없으면 없다고 적힌 카드"가 "결과 없음"보다 낫다.

---

## 5. 외부 의존

| 무엇 | 어디 | 결정적인가 | 없으면 |
|---|---|---|---|
| **LLM(description 번역)** | `deps.response_translator` (ChatOpenAI, temp=0) | **비결정적** — `RESPONSE_LLM=1`일 때만 주입 | 원문(영어) 그대로 운반 (폴백) |
| **MCP / DB / 파일** | — | **해당 없음** — 아무것도 조회 안 함 | — |

- 이 노드가 LLM을 쓰는 곳은 **description 번역 한 곳뿐**. 그마저 `RESPONSE_LLM` off(기본)면 안 부르므로, **기본 경로는 완전 결정적**이라 골든 테스트가 쉽다. 번역기는 테스트에서 가짜 콜러블로 주입해 검증한다.
- 호출 횟수: 그룹당 최대 1콜(description 있을 때만). 그룹은 배치당 3~5개 수준이라 비용·지연 부담 작음.

---

## 6. 튜닝 상수 · 매직넘버

| 이름 | 값 | 위치 | 근거 |
|---|---|---|---|
| `_JUDGE_UNKNOWN_TOKENS` | critic 토큰 3종 집합 | `response.py` | ⑥ Critic이 정한 "보류 계열" 사유. 자연어 매칭 금지, 토큰으로만 판정 |
| `RESPONSE_LLM` (env 플래그) | `0`/`1` | `deps.response_translator` | description 번역 켜는 opt-in(KG_LIVE·VLM_LIVE와 같은 관례). 기본 off = 원문 운반 |
| `_TRANSLATE_PROMPT` | 충실 번역 프롬프트 | `deps.py` | 사실 가감·해석 금지(firewall) |

숫자 하드코딩은 없다(문자열 템플릿·문구뿐). description은 상수 문구를 두지 않는다 — VLM 실생성분만 운반한다(§4-2).

---

## 7. 테스트 현황

| 무엇을 보장하나 | 파일 | 비고 |
|---|---|---|
| unmapped·insufficient 카드가 예상 payload와 정확히 일치 | `test_skeleton_response.py` | 골든 비교 |
| 근거 모달 드릴다운이 `h0`부터 열림 | 〃 | AC-18 |
| ⑦·⑦'이 정렬 헬퍼를 공유 / ⑦엔 unmapped·insufficient 분기가 없음 | 〃 | AC-15·16 |
| **reviewed 카드 전체 골든**(summary 문자열·accepted verdict/verdict_reason=None·reason=None 포함) | 〃 | `..reviewed_matches_golden` |
| **정렬 불변식** — accepted+rejected+judge_unknown 혼합에서 채택이 앞·대표=h0·verdict 4종·h{n} 순번 | 〃 | `..accepted_first_then_rejected..` |
| `_ordered_hypotheses(None)` → `[]` (critic 없음 방어) | 〃 | `..none_critic_returns_empty` |
| `vlm_track` 있으면 total_description 운반 / 스켈레톤 폴백은 문구가 있어도 None / observation 없으면 None / vlm_track만 있고 텍스트 없으면 None | 〃 | 본 작업분 |
| 번역기 주입 시 한국어로 변환(⑦·⑦' 양쪽) / 번역 실패 시 원문(영어) 폴백 | 〃 | 가짜 콜러블 주입 |
| ⑦·⑦' 시그니처가 `[state, translate]` | `test_skeleton_flatten.py` | partial 주입 관례 |

- 전체 백엔드 `pytest -q -m "not data"` green 확인(157건).

**아직 검증 못 한 케이스**
- **실제 VLM+번역 end-to-end**(VLM_LIVE=1 + RESPONSE_LLM=1 + fab.db) — 지금은 가짜 콜러블로만.

---

## 8. 알려진 한계 · 팀 논의 필요

| # | 항목 | 제안 | 결정 필요 |
|---|---|---|---|
| 1 | **VLM 미가동**이 진짜 병목 — 평상시 description=None. 코드는 다 됐고 VLM_LIVE·RESPONSE_LLM을 켜야 한국어 서술이 뜬다 | VLM 실가동 + fab.db로 end-to-end 검증 | O(다음 스텝) |
| 2 | `hypotheses[].narrative`는 **빌드타임 문헌 문장**(generic) — 런타임 근거 반영 `rationale`은 만들어놓고 카드에 안 뜸 | rationale을 가설별로 만들어 카드에 실을지 | 중 |
| 3 | `summary`(결정론 템플릿)는 **API payload엔 안 실림** — 내부/디버그용으로 유지 확정(LLM 합성 안 함) | 노출하려면 명세 §2.5+프론트 수정 | 낮음 |
| 4 | 번역 콜이 그룹당 동기 blocking — 그룹 수가 적어 문제 작지만, 많아지면 async화 검토 | 필요 시 async 전환 | 낮음 |

---

## 부록 A. 코드 진입점 맵

| 하고 싶은 일 | 볼 곳 |
|---|---|
| 정상 카드 조립 | `response.py::generate_response` |
| "판단 불가"·"미매핑" 카드 | `response.py::respond_without_llm` |
| 가설 정렬·번호·verdict 규칙 | `response.py::_ordered_hypotheses` |
| 서술(description) 운반·번역 지점 | `response.py::_group_description` |
| 카드 → API 응답 변환 | `backend/assembler.py::build_analysis_payload` |
| 어느 경로로 갈지 정하는 곳 | `backend/graph.py::route_on_candidates` · `route_on_verdicts` |
| 응답 필드 계약(정본) | `docs/API_명세서_v1.0.md` §2.5 |

## 부록 B. 용어

| 말 | 뜻 |
|---|---|
| **⑦ / ⑦'** | ⑦=정상(채택 있음) 응답, ⑦'=LLM 안 부르는 응답(후보 0·채택 0) |
| **verdict** | 가설 1건의 최종 표시 상태: accepted / rejected / judge_unknown |
| **judge_unknown** | 기각이 아니라 "지금 데이터로는 판단 보류"(미조사·근거없음) |
| **description** | 사용자에게 보일 그룹 결함 서술. API §2.5 필드. VLM 실생성분만 실림 |
| **summary_line** | 프론트가 코드값으로 조립하는 결정적 한 줄(비계약). `description`이 None일 때의 대체 |
| **vlm_track** | 관측 메타(open/pty). **존재 자체가 "VLM이 실제로 서술을 생성했다"는 신호** |
