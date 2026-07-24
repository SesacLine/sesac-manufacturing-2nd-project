# 노드 설계 공유 — ① CNN 결함 패턴 판정

## 0. 요약

- **노드**: ① read_wafer_maps (cnn_classify)
- **파일**: `backend/nodes/cnn.py` (엔진: `wafer_reading/classifier/`)
- **담당**: 허수정
- **한 줄 역할**: 저수율 로트의 웨이퍼 한 장 한 장에 결함 패턴 라벨(5클래스)을 붙인다.
  이 노드가 없으면 ② grouper가 패턴별 그룹을 만들 수 없고, 그 뒤 전부(관측→KG→가설)가 시작을 못 한다.
- **상태**: 구현 완료 — ResNet-18 실연동. 단, 체크포인트가 없는 환경에서는 "Center" 고정값 폴백으로 동작
- **작성일 / 대상 커밋**: 2026-07-24 / `fdb03e4` (PR #67·#68·#70·#72 머지 후 main — `cnn.py`·
  `wafer_reading/`는 #60 이후 무변경이라 계약 서술은 그대로, 테스트 현황·팀 결정만 갱신)

---

## 1. 입출력 계약 (필수)

### 1-1. 입력

| state 키 | 타입 | 채우는 주체 | 없으면/None이면 |
|---|---|---|---|
| `target_lot_ids` | `list[str]` | ⓪ lowyield | 빈 리스트면 `cnn_results=[]`로 즉시 반환 (정상 동작) |

| 환경 | 무엇 | 없으면 |
|---|---|---|
| `FAB_DB` | fab.db 경로 — 웨이퍼별 `die_map`(numpy .npy blob)을 읽는다 | KeyError로 배치 실패 (필수 전제) |
| `CNN_CKPT` | 체크포인트 경로 (기본 `wafer_reading/classifier/checkpoints/resnet18_5cls.pt`) | **폴백 모드** — 아래 참고 |

- **입력에 대해 내가 가정하는 것**: `target_lot_ids`의 로트는 전부 fab.db `wafer` 테이블에 있다
  (⓪이 같은 DB에서 뽑았으므로). `die_map`은 0/1/2 값 격자다(0=die 없음, 1=정상, 2=불량).
- **가정이 깨지면**: 로트가 DB에 없으면 그 로트 웨이퍼가 결과에서 조용히 빠진다(예외 없음).
  die_map이 NULL인 웨이퍼(배경 무라벨)는 판독하지 않고 폴백 결과로 처리한다.

### 1-2. 출력

| state 키 | 타입 | 비고 |
|---|---|---|
| `cnn_results` | `list[CNNResult]` | 웨이퍼 1장당 1건. 생산자는 CNN |

- **하위 노드가 믿어도 되는 불변식**:
  1. `pattern`은 반드시 5클래스(`Center`/`Edge-Ring`/`Scratch`/`Unknown`/`Normal`) 중 하나다.
     폴백 모드에서도 이 집합을 벗어나지 않는다(항상 `"Center"`).
  2. `confidence`는 실판독이면 softmax 확률(0~1), **폴백이면 0.5 고정** — 폴백 여부의
     유일한 표시다(구 `ambiguity` 필드는 PR #60에서 제거).
  3. 대상 로트의 (die_map 있는) 웨이퍼는 전부 결과에 1건씩 들어간다 — 누락 없음.
- **제거된 필드(PR #60)**: `spatial`·`description`·`severity`·`ambiguity` — 소비자 전수 추적
  결과 미사용(grouper=pattern, batch_runner=lot/wafer/pattern 3-튜플)이라 삭제. 형상 서술은
  ③ vlm_describe의 observation이 정본이다.

### 1-3. 새로 도입/변경한 필드

- `VLMResult` → **`CNNResult`** 개명 + 잔재 필드 4종(spatial/description/severity/ambiguity)
  제거, state 키 `vlm_results` → **`cnn_results`** 개명(이슈 #59, PR #60, 07-24 머지).
  남은 필드: `lot_id`/`wafer_id`/`pattern`/`confidence`.

---

## 2. 실패·경계 케이스 계약 (필수)

| 상황 | 이 노드의 동작 | 하위 노드가 보게 되는 것 |
|---|---|---|
| `target_lot_ids` 빈 리스트 | 즉시 빈 결과 반환 | `cnn_results=[]` → grouper가 그룹 0개 |
| 체크포인트 파일 없음 | 전 웨이퍼 폴백 판정 (한 번만 확인하고 기억 — 웨이퍼마다 재시도 안 함) | 전부 `pattern="Center", confidence=0.5` → 그룹이 Center 하나만 생김 (구 스켈레톤과 동일한 모습) |
| 체크포인트 손상 / torch 미설치 | 위와 동일한 폴백 | 〃 |
| die_map이 NULL인 웨이퍼 | 그 웨이퍼만 폴백 판정 | 해당 웨이퍼만 confidence=0.5 |
| fab.db 자체가 없음 | **예외 발생 → 배치 실패** | — (FAB_DB는 파이프라인 전체의 전제라 폴백하지 않음) |

- **예외를 던지는 경우**: FAB_DB 미설정/부재뿐. 모델 쪽 문제는 전부 폴백으로 흡수한다.
- **타임아웃·재시도 정책**: 없음 — 로컬 추론이라 네트워크 실패 개념이 없다.

---

## 3. 내부 플로우

```
target_lot_ids 비었나? ─예→ 빈 결과 반환
        └아니오→ fab.db에서 (lot_id, wafer_id, die_map) 조회
→ 분류기 로드 시도 (프로세스당 1회, 실패는 기억)
→ (분류기 있음 & die_map 있음)? ─예→ 모아서 배치 추론 → {pattern, confidence}
                               └아니오→ 폴백 결과 ("Center", 0.5)
→ cnn_results로 병합 반환
```

- 웨이퍼를 한 장씩 추론하지 않고 **한 번에 배치 추론**한다(`classify_batch`)

---

## 4. 설계에서 중요하게 고려한 것 (필수)

### 4-1. 체크포인트가 없어도 파이프라인이 죽지 않게 한 이유

- **문제**: 모델 파일(44.8MB)은 git에 못 올린다(바이너리 커밋 금지). 즉 CI와 갓 clone한 팀원
  환경에는 체크포인트가 없는 게 기본 상태다.
- **선택**: 파일이 없으면 구 스켈레톤과 똑같은 "Center" 고정값으로 폴백. 파이프라인 배선 자체는
  모델 없이도 항상 검증 가능하게 유지했다.
- **대안과 기각 이유**: "체크포인트 없으면 예외" — CI가 영구적으로 빨간불이 되고, 판독 모듈과
  무관한 작업자까지 막는다. 기각.
- **되돌릴 조건**: 체크포인트 배포가 자동화되면(예: 릴리즈 자산) 폴백을 경고 로그로 바꿔도 된다.

### 4-2. 학습-평가 누출 차단 (fab.db Test-only와 한 몸)

- **문제**: 분류기는 WM-811K로 학습하는데, fab.db(평가 대상)도 WM-811K에서 만들어진다.
  같은 웨이퍼가 양쪽에 있으면 판독 정확도가 부풀려진다 — 실측으로 구 fab.db에 학습 후보
  5,594장이 겹쳐 있었다.
- **선택**: 학습은 `trainTestLabel=Training` 안에서만 9:1로 나누고, fab.db는 Test split
  전용으로 재생성했다(누출 0 검증 완료). 그 결과 학습 코드의 "fab.db 웨이퍼 제외" 규칙은
  자동으로 무효(교집합 ∅)가 됐지만 안전망으로 남겨뒀다.
- **대안과 기각 이유**: "fab.db 웨이퍼만 학습에서 제외" — 동작은 하지만 fab.db를 재생성할
  때마다 재학습이 필요해지고, Test 셋 벤치마크의 의미도 흐려진다. 임시 브리지로만 썼다.
- **되돌릴 조건**: 없음 (이쪽이 교과서적 구성).

### 4-3. 모델 코드를 노드 파일에 넣지 않은 이유

- **문제**: 학습 스크립트·전처리·추론기는 서버 없이도 쓰인다(팀원 테스트, 재학습, 데모).
- **선택**: 노드는 "state 읽기 → 엔진 호출 → state 쓰기 + 폴백 정책"만 담고, 엔진은
  `wafer_reading/classifier/`에 분리했다. hypothesis 노드↔MCPClient와 같은 관례다.
- **대안과 기각 이유**: 노드 파일에 직접 구현 — dev 도구가 서버 코드를 import하는 역방향
  의존이 생긴다. 기각.
- **되돌릴 조건**: 없음.

---

## 5. 외부 의존 (LLM · MCP · 파일 · DB)

| 무엇 | 어디 | 결정적인가 | 없으면 |
|---|---|---|---|
| fab.db `wafer.die_map` | `FAB_DB` 경로 | 결정적 | 배치 실패 (유일한 하드 의존) |
| ResNet-18 체크포인트 | `CNN_CKPT` (기본 checkpoints/) | **추론은 결정적** (같은 입력→같은 출력). 학습(재생성)은 비결정적 — 재학습본은 수치가 조금 다를 수 있다 | 폴백 모드 |
| torch/torchvision | uv sync로 설치 (cu128 인덱스 고정) | — | 폴백 모드 |

- 호출 횟수/지연: 배치당 추론 1회(전 웨이퍼 일괄)

---

## 6. 튜닝 상수 · 매직넘버

| 이름 | 값 | 위치 | 근거 |
|---|---|---|---|
| `_FALLBACK_PATTERN` | `"Center"` | `cnn.py` | 구 스켈레톤 관례 유지 — 임의값 |
| `INPUT_SIZE` | 64 | `classifier/data.py` | 공통 격자 크기. nearest 고정(0/1/2 값 오염 방지) |
| 학습 에폭/배치 | 12 / 256 | `classifier/train.py` | GPU 31초 기준 실측 설정. CPU면 `--epochs 4` 축소 가능 |
| 클래스 가중 | 역빈도 | `classifier/train.py` | Training 실측 Normal 36,730 vs Scratch 500 (73:1) |

---

## 7. 테스트 현황

- **모델 평가**: 검증셋(Training 9:1) 전체 97.3%. Test split 스모크(클래스당 50장):
  Center 78% / Edge-Ring 76% / **Scratch 62%** / none 94% / Donut 94% / Loc 74%.
  검증셋과 Test의 격차는 WM-811K 자체의 분포차 — Test 쪽이 운영 기대치다.
- **파이프라인 검증**: 실배치 완료 — 실판독으로 4그룹(Center/Edge-Ring/Unknown/Normal) 생성 확인.
  07-24 merge 통합 main(#55·#58·#60) 재검증 — 실배치 완료, 3그룹(Center/Edge-Ring/Unknown) 분화,
  Center 그룹 top-1이 GT 메커니즘(CLEAN flow_rate 저하)과 부합.
- **자동화 E2E(07-24, PR #67)**: `backend/tests/test_e2e_wafer_reading_path.py` — GT 시나리오
  11종으로 ①→③→④ 진입 경계를 파라미터라이즈 검증(`@pytest.mark.data`, fab.db 필요 — CI의
  `-m "not data"`에서는 제외). 정답 라벨 흉내(is_normal) 트랙과 별개로 `test_real_cnn_wiring`이
  실 CNN 판정 → ③ 배선을 게이트한다 — 공유 체크포인트 전제라 결정적이며, 모델 정확도는 단언하지
  않고 배선만 단언(실측: SC-CENTER-01 실판정 필터 시 `random@center` — FP 혼입·미검출 영향).
- **아직 검증 못 한 케이스**: ① confidence 값의 신뢰도(캘리브레이션 안 함 — 0.9가 "90% 맞다"는
  뜻이 아직 아님) ② 폴백 모드에 대한 자동화 테스트 없음(수동 확인만) ③ 손상 die_map blob.

---

## 8. 알려진 한계 · 팀 논의 필요

| # | 항목 | 내 제안 | 결정 필요 여부 |
|---|---|---|---|
| 1 | Scratch 정밀도 0.45 (과잉 예측) — 가짜 Scratch 그룹이 생길 수 있음 | 에폭 증가 + 가중치 완화 실험, 또는 confidence 문턱 도입 | 개선 우선순위만 |
| 2 | ~~로트 과반이 Normal이면 grouper가 Normal 그룹을 만들어 unmapped로 노출됨~~ → **grouper 구현 완료(이슈 #69 → PR #72, 07-24)**: Normal 다수결 로트는 그룹 미생성 + `normal_lots`로 분리 운반(동률 우선순위 Edge-Ring > Center > Scratch > Unknown, 07-22 판독 설계서 §3) | "판독상 정상 N로트" 전용 카드 노출 배선(status 신설 vs reason 교체)은 프론트 협의 후 후속 | 카드 노출만 남음 |
| 3 | 체크포인트 배포 채널 (44.8MB, git 밖) | ~~채널 미정~~ → **팀 전원 동일 체크포인트 사용 합의(07-24)** — #67 E2E(`test_real_cnn_wiring`) 결정성의 전제. 공유 방식은 팀 드라이브 + 가이드 §3 | 배포 채널 운영 확정만 남음 |

---

## 부록. 코드 진입점 맵

| 하고 싶은 일 | 볼 곳 |
|---|---|
| 노드 동작(폴백 정책 포함)을 바꾸려면 | `backend/nodes/cnn.py:read_wafer_maps` |
| 판정 클래스를 바꾸려면 | `wafer_reading/classifier/__init__.py:CLASSES` (체크포인트와 순서 일치 필수) |
| 재학습하려면 | `python -m wafer_reading.classifier.train --pkl ... --fab-db ... --out ...` |
| 추론만 따로 쓰려면 | `wafer_reading/classifier/infer.py:WaferClassifier` |
| split/제외 규칙을 바꾸려면 | `wafer_reading/classifier/data.py:build_dataset_arrays` |
