# 노드 설계 공유 — ③ 관측 생산 (vlm_describe)

## 0. 요약

- **노드**: ③ observe_groups (vlm_describe)
- **파일**: `backend/nodes/vlm_describe.py` (엔진: `wafer_reading/{stacking,quantitative,vlm}/`)
- **담당**: **분담 주의** — 기본 경로(결정적 관측: stacking+quantitative 연결)는 KG/geometry 담당
  팀원(류은서) 구현이고, 이 문서의 주 대상인 **VLM_LIVE 분기와 VLM 어댑터(wafer_reading/vlm) 전체**가 팀원(허수정)의 구현이다.
- **한 줄 역할**: 패턴 그룹 하나를 "관측(Observation)" 한 건으로 요약한다 — 어디에(공간)·어떤
  모양으로(형상) 불량이 있는지를 구조화 값과 자연어로. 이 노드가 없으면 ④ KG 조회가 검색 키
  (signature enum + 자연어)를 받을 수 없다.
- **상태**: 구현 완료 — 결정적 경로 상시 동작, VLM 자연어는 `VLM_LIVE=1`일 때만(opt-in)
- **작성일 / 대상 커밋**: 2026-07-24 / `fdb03e4` (PR #67·#70·#72 머지 후 main — `vlm_describe.py`·
  `wafer_reading/`는 #55·#58·#60 이후 무변경이라 계약 서술은 그대로, #61 배선 완료·테스트 현황만 갱신)

---

## 1. 입출력 계약 (필수)

### 1-1. 입력

| state 키 | 타입 | 채우는 주체 | 없으면/None이면 |
|---|---|---|---|
| `groups` | `list[Group]` | ② grouper | 빈 리스트면 그대로 빈 결과 (정상) |
| `cnn_results` | `list[CNNResult]` | ① cnn | **두 경로 모두** 멤버 필터(_member_keys)에 사용(PR #58) — 없으면 기본 경로는 로트 전체로 폴백(단독 호출 하위호환) |

| 환경 | 무엇 | 없으면 |
|---|---|---|
| `FAB_DB` | die_map 로드 | 스켈레톤 관측으로 폴백 (배치는 계속) |
| `VLM_LIVE` | `1`이면 VLM 자연어 켬 (기본 꺼짐) | 꺼짐 = 결정적 관측만 |
| `VLM_TRACK` | `open`(Qwen 로컬) / `pty`(OpenAI) | 기본 `open` |
| `OPENAI_API_KEY` | pty 트랙용 (.env) | pty 선택 시 호출 실패 → 결정적 관측으로 강등 |

- **입력에 대해 내가 가정하는 것**: `group["pattern"]`은 5클래스 중 하나다. Normal 그룹은
  **PR #72(이슈 #69, 07-24)부터 grouper가 만들지 않는다**(`normal_lots`로 분리 운반) — 혹시
  들어와도 최소 관측으로 방어 처리된다(§2 표의 해당 행은 방어 계약으로 유지).
- **가정이 깨지면**: 모르는 패턴은 "자연어 없는 최소 관측"으로 처리된다(예외 없음).

### 1-2. 출력

| state 키 | 타입 | 비고 |
|---|---|---|
| `groups[].observation` | `Observation` | 그룹당 정확히 1건 — 웨이퍼별 판독을 합치는 집계가 아니라, 그룹 이미지를 한 번 보고 만든 관측 |
| `observation.total_description` | `str` | **VLM_LIVE 실생성 시에만 존재.** 사용자 노출용 요약(영어, API §2.5 description의 원천 — **⑦ 배선 완료, PR #70**) — ⑦이 `RESPONSE_LLM=1`이면 한국어로 번역해 운반, 기본은 영어 원문 운반 |
| `observation.vlm_track` / `image_mode` | `str` | **VLM_LIVE에서만 존재.** 어느 트랙·어떤 이미지(stacked/single)였는지 — 평가·재현용. `vlm_track` 존재 = "VLM 실생성" 판별 키 |

> ⚠️ 구버전 주의: 07-23 구현은 이 3종을 **group 레벨**에 붙였으나, PR #55(07-24)로 전부
> **observation 내부**로 통일됐다(스켈레톤/라이브 경로 배치 위치 일치 + 서브그래프 유실 해소).

- **하위 노드가 믿어도 되는 불변식**:
  1. 모든 그룹에 `observation`이 반드시 붙는다 — 어떤 실패에서도 None이 아니다(폴백이 채움).
  2. 구조화 값(`signature`/`angular_coverage`/`density`/`continuity`/`defect_die_ratio`)은
     **항상 결정적 계산의 산출**이다. VLM이 켜져 있어도 이 값들은 VLM이 못 건드린다.
  3. `location_text`/`morphology_text`가 비어 있지 않으면 → 실제 VLM이 그 그룹 이미지를 보고
     쓴 문장이다(스켈레톤 폴백 제외). Unknown 그룹의 자연어는 실VLM일 때만 존재한다 —
     스켈레톤은 미지 패턴의 서술을 지어내지 않는다(지어내면 KG를 가짜 근거로 오도).
  4. `observation.total_description`이 없는 것(키 부재)은 "VLM이 안 돌았다"는 뜻... 단
     **스켈레톤 폴백은 예외적으로 이 키를 채운다**(전형값 템플릿) — "VLM 실생성" 판별은
     `vlm_track` 존재로 하라(⑦ 응답 노드의 §2.5 description 배선도 이 기준으로 구현됨 — PR #70,
     `response.py:_group_description`).

### 1-3. 새로 도입/변경한 필드

- `observation.total_description` / `vlm_track` / `image_mode` — VLM 산출·메타.
  **PR #55(07-24)로 state.py `Observation`에 정식 선언 완료**(NotRequired). 초기 구현은
  group 레벨 dict 확장 키였으나, 경로별 배치 위치 불일치·서브그래프 진입 시 유실 문제로
  observation 내부로 통일했다(state_py 계약 검증 A-1·A-2).
- API 노출: `total_description` → §2.5 `description` 배선 **구현 완료(이슈 #61 → PR #70, 07-24)**.
  제안한 정책이 그대로 채택됐다 — ⑦이 `vlm_track` 존재로 실생성분만 운반하고 스켈레톤 폴백은
  null(→ 프론트 summary_line fallback), `RESPONSE_LLM=1`이면 한국어 번역(`deps.response_translator`,
  temp=0)·기본(off)은 영어 원문 운반. `FinalResponse`에 `description` 키가 신설됐다(`state.py`).
  배선 상세 정본은 `docs/node_spec_07_response.md`.

---

## 2. 실패·경계 케이스 계약 (필수)

| 상황 | 이 노드의 동작 | 하위 노드가 보게 되는 것 |
|---|---|---|
| fab.db 없음 / die_map 전부 NULL | 패턴별 스켈레톤 관측(전형값 템플릿) | 3종이면 그럴듯한 고정 관측, 그 외엔 자연어 없는 최소 관측 |
| quantitative 계산 실패(예외) | 스켈레톤으로 폴백 | 〃 |
| **VLM 호출 실패** (타임아웃·파싱 실패가 재시도 2회 후에도 지속) | **결정적 관측만으로 강등** — 예외를 위로 던지지 않음 | 구조화 값은 정상, 자연어 빈 값, total_description 키 없음 |
| 그룹에 멤버 규칙 통과 웨이퍼가 0장 | 기본 경로(로트 전체)로 계산 | 결정적 관측 |
| Normal/미지 패턴 그룹 (Normal은 PR #72부터 정상 경로에선 미도달 — 방어 계약으로 유지) | 최소 관측 | ④에서 candidates=[] → unmapped 흐름 |

- **예외를 던지는 경우**: 없음. 이 노드의 실패는 전부 "관측의 품질 저하"로 변환되고 배치는 계속된다.
  근거: 자연어가 없어도 signature enum 진입으로 KG 조회가 성립하므로, VLM 실패가 배치를 죽일
  이유가 없다.
- **타임아웃·재시도 정책**: VLM 호출당 타임아웃 120초, 파싱/호출 오류 통합 재시도 2회(총 3시도).
  소진 시 위의 강등. 수치는 잠정값(실측 후 조정 대상).

---

## 3. 내부 플로우

```
VLM_LIVE 꺼짐? ─예→ [기본 경로] 멤버 규칙 필터(cnn_results 있으면 — PR #58) die_map
                      → 스택맵 → quantitative → 구조화 관측 (자연어 빈 값)
             └아니오→ [라이브 경로]
                ① cnn_results에서 "개별 판독 = 그룹 패턴" 웨이퍼만 필터 (멤버 규칙)
                ② 그 die_map들로 구조화 관측 생성 (기본 경로와 같은 계산)
                ③ VLM 어댑터 호출:
                     Scratch? ─예→ 결함 die 최다 웨이퍼 1장 렌더 (단일 이미지)
                             └아니오→ 그룹 스태킹 히트맵 1장 렌더
                     → few-shot 3턴 + 쿼리 메시지 조립 → 트랙(open/pty) 호출
                     → JSON 파싱·필드 검사 (실패 시 재시도 ≤2)
                ④ 성공: 관측에 location/morphology_text 오버레이 + total_description·
                   vlm_track·image_mode를 observation에 부착 (PR #55 — group 레벨 아님)
                   실패: 구조화 관측만으로 강등
```

---

## 4. 설계에서 중요하게 고려한 것 (필수)

### 4-1. VLM은 자연어만, 구조화 값은 전부 결정적 계산인 이유

- **문제**: angular_coverage는 KG 재랭킹에서 감점 -10짜리 판별자(강)다. VLM이 이 값을 내면
  텍스트 환각 하나가 정답 원인 후보를 순위 밖으로 밀어낸다. defect_die_ratio 같은 수치는
  VLM이 셀 수도 없다.
- **선택**: VLM 출력 계약을 텍스트 4필드(pattern_candidate 에코 + location/morphology/
  total_description)로 못 박고, 구조화 값은 die-matrix에서 결정적으로 계산한다. VLM은 그
  필드들을 보지도 출력하지도 않으므로 환각의 통로 자체가 없다.
- **대안과 기각 이유**: 초기엔 density/continuity를 VLM이 내는 안(6필드)이었으나, 팀원의
  quantitative가 이 둘까지 결정적으로 산출하게 되면서 VLM 몫을 더 줄였다(07-23 확정).
- **되돌릴 조건**: 결정적 계산이 특정 형상에서 계속 오판하고 VLM 관측이 더 정확하다는 실측이
  쌓이면, 해당 필드만 "VLM 보조 신호" 재승격 검토 (§8-1 참고).

### 4-2. flag(opt-in) 분기로 만든 이유

- **문제**: VLM을 상시 켜면 배치마다 모델/API 의존이 생기고, CI·무GPU·무키 환경이 전부 깨진다.
  게다가 당시 같은 파일을 팀원이 수정 중이었다.
- **선택**: `VLM_LIVE` 환경변수 분기(백엔드의 `KG_LIVE` 관례를 그대로 따름). 기본 경로는 팀원
  코드를 한 줄도 건드리지 않고, 라이브 경로는 파일 뒤에 별도 함수로 덧붙였다.
- **대안과 기각 이유**: 스켈레톤을 삭제하고 VLM로 교체 — 환경 의존이 강제되고 머지 충돌 면적이
  커진다. 기각.
- **되돌릴 조건**: VLM이 운영 필수가 되는 시점에 기본값을 뒤집는다(flag는 유지).

### 4-3. Scratch만 단일 이미지로 보내는 이유

- **문제**: 스크래치는 웨이퍼마다 위치·방향이 달라, 여러 장을 겹치면 선형 신호가 서로 상쇄된다
  (실측: 5장 스태킹 이미지에서 선이 거의 안 보임).
- **선택**: Scratch 그룹은 그룹에서 결함 die가 가장 많은 웨이퍼 1장을 렌더한다(신호가 가장
  뚜렷한 대표). few-shot의 Scratch 예시도 단일 이미지로 맞춰 형식을 정합시켰다.
- **대안과 기각 이유**: (a) 스태킹 유지 + "여러 희미한 선" 서술로 프롬프트 조정 — 서술 품질이
  원리적으로 낮아짐 (b) 전 패턴 단일 이미지 — Center/Edge-Ring은 스태킹이 신호를 강화한다는
  실측과 상충. 둘 다 기각.
- **되돌릴 조건**: 대표 1장이 그룹을 대변 못 하는 사례(로트 간 이질적 스크래치)가 실측되면
  "상위 K장 몽타주" 검토.

### 4-4. VLM 실패를 "강등"으로 처리하는 이유 (배치 불사 원칙)

- **문제**: 외부 모델 호출은 언제든 실패할 수 있다. 그때 배치 전체가 죽으면 수율 엔지니어의
  하루 업무(버튼 한 번)가 통째로 실패한다.
- **선택**: 재시도 소진 시 구조화 관측만으로 진행. signature enum 진입이 성립하므로 KG 조회는
  여전히 동작하고, 잃는 것은 자연어 품질뿐이다.
- **대안과 기각 이유**: 그룹 스킵 — 관측 없이도 얻을 수 있는 결정적 정보까지 버린다. 기각.
- **되돌릴 조건**: "자연어 없는 카드는 내보내지 말라"는 제품 결정이 나오면 스킵으로 변경.

---

## 5. 외부 의존 (LLM · MCP · 파일 · DB)

| 무엇 | 어디 | 결정적인가 | 없으면 |
|---|---|---|---|
| fab.db `die_map` | `FAB_DB` | 결정적 | 스켈레톤 폴백 |
| stacking + quantitative | `wafer_reading/` | 결정적 | (코드 의존 — 없을 수 없음) |
| **VLM 호출** | open: Qwen3-VL-4B 로컬 / pty: OpenAI API | **잠재적 비결정** — greedy/temp 0으로 고정했지만 API 서버측 변동·모델 업데이트 가능성 있음. `vlm_track` 기록이 재현성 보조 | 강등 (결정적 관측만) |
| few-shot 예시 이미지 3장 | `wafer_reading/vlm/assets/` (커밋됨) | 결정적 (시드 고정 생성물, 정답 JSON과 쌍 고정) | 어댑터 예외 → 강등 |

- 호출 횟수/지연: **그룹당 VLM 1콜** (배치당 최대 4~5콜). pty 콜당 수 초. open은 최초 모델
  다운로드 ~8GB(1회), 이후 로드 ~2초 + 추론 수 초.

---

## 6. 튜닝 상수 · 매직넘버

| 이름 | 값 | 위치 | 근거 |
|---|---|---|---|
| `DEFAULT_TIMEOUT_S` / `MAX_RETRIES` | 120 / 2 | `vlm/adapter.py` | 잠정 — 실측 조정 대상 |
| `MAX_NEW_TOKENS` | 512 | `vlm/backends/qwen_local.py` | 텍스트 4필드에 충분 + 폭주 방지 |
| Scratch 대표 선정 | 결함 die 최다 | `vlm/adapter.py:_render_image` | 임의(신호 최강 가정) — 팀 결정 대기 |
| few-shot 예시 수 | 3턴(패턴당 1) | `vlm/prompts.py` | 팀 확정 "각 1장에서 시작" — 품질 미달 시 증량 |
| 스태킹 `min_coverage` | 0.5 | `stacking.py` | 원판 경계 비율 부풀림 억제 (실측 후 도입) |

---

## 7. 테스트 현황

- **단위 테스트**: `wafer_reading/tests/test_vlm_adapter.py` 6건 — 텍스트 4필드 반환, Scratch
  단일 분기, 파싱 재시도/소진, 코드펜스 허용, 필드 누락 거부. 전부 fake backend 주입이라
  데이터·GPU·키 없이 돈다. + 팀원의 `backend/tests/test_vlm_describe.py`(기본 경로).
- **실호출 검증**: 양 트랙 데모 성공(pty: Edge-Ring 스택·Scratch 단일 / open: Center 스택 —
  4B가 schema 강제 없이 유효 JSON). 실배치 완주(VLM_LIVE=1 pty, 4그룹).
  **07-24 머지 통합 main(#55·#58·#60) 재검증**: pty 실호출 1회(§3 — total_description 등 전부
  observation 내부 확인) + 전체 배치 완주(§4 — 3그룹, Center top-1 GT 메커니즘 부합)
- **자동화 E2E(07-24, PR #67)**: `backend/tests/test_e2e_wafer_reading_path.py` — GT 시나리오
  11종으로 ①→③→④ 진입 경계 기준선 고정(`@pytest.mark.data`). §8-1의 오염 실측(Center 대형
  스택 `ring@edge`, Scratch 스택 희석)이 **기준선표에 오답값 그대로 박혀 있어**, 그 한계가
  고쳐지면 이 테스트가 빨간불로 알린다(수치를 "정답"으로 읽지 말 것). VLM 실호출 검증은
  과금 때문에 `VLM_E2E=1` opt-in(대표 시나리오 1건).
- **아직 검증 못 한 케이스**: ① open 트랙 대량 호출 시 JSON 준수율(1회 성공만 확인)
  ② 재시도·강등 경로의 실전 발생(테스트로만 검증) ③ **Unknown 그룹의 의미 진입**(KG_LIVE=1
  + Neo4j 필요 — 아직 안 돌림. 자연어→cosine≥0.4 매칭이 실제로 되는지가 관건) ④ VLM 서술
  품질의 정량 평가(루브릭/LLM-judge — 평가 프레임워크 미구축).

---

## 8. 알려진 한계 · 팀 논의 필요

| # | 항목 | 내 제안 | 결정 필요 여부 |
|---|---|---|---|
| 1 | quantitative가 다수 웨이퍼 스택에서 오분류(실측 2건: Center 48장·Scratch 45장 그룹 → signature=ring@edge). 원인: DEFECT_HEAT_THRESHOLD=0.5가 대형 스택에 과엄격 — 결함 위치가 장마다 어긋나 공통 셀이 드묾. **#67 E2E 기준선표가 이 오염값을 그대로 고정** — 수리되면 테스트가 알린다 | 임계 하향 또는 웨이퍼별 계산 후 집계, Scratch는 단일 맵 입력 | **geometry 담당과 논의 필요** |
| 2 | ~~멤버 규칙이 기본 경로 미적용~~ → **해소(PR #58, 07-24)**: `_member_keys` 공용 헬퍼로 두 경로 통일. 실측 근거: SC-CENTER-01 전체 192장 `random@edge`(오답) vs 멤버 29장 `cluster@center`(정답) | — | 완료 |
| 3 | ~~total_description 영한 번역이 ⑦ 응답생성 요구사항에 추가돼야 함~~ → **해소(PR #70, 07-24)**: ⑦이 `RESPONSE_LLM=1` opt-in 번역(`deps.response_translator`, temp=0, 실패 시 영어 원문 폴백)으로 구현 | — | 완료 |
| 4 | 재시도/타임아웃 수치가 잠정 | 실배치 로그로 실패율 실측 후 확정 | 실측 후 |

---

## 부록. 코드 진입점 맵

| 하고 싶은 일 | 볼 곳 |
|---|---|
| flag 분기·폴백 정책을 바꾸려면 | `backend/nodes/vlm_describe.py:observe_groups`, `_observe_group_live` |
| 프롬프트·few-shot 예시를 바꾸려면 | `wafer_reading/vlm/prompts.py` (예시 이미지와 쌍 고정 주의) |
| 이미지 분기(Scratch 단일 등)를 바꾸려면 | `wafer_reading/vlm/adapter.py:_render_image` |
| 트랙을 추가하려면 | `wafer_reading/vlm/backends/` (계약: `generate(messages)->str`) + `adapter.py:__init__` |
| 예시 이미지를 재생성하려면 | `python -m wafer_reading.vlm.gen_assets` (재생성 시 예시 JSON 재검토 필수) |
| 파이프라인 없이 단독 테스트하려면 | `python -m wafer_reading.vlm.demo --track pty --pattern Edge-Ring --n 9` |
