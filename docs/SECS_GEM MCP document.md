> **0714 안내 — 이 문서는 목표 설계도다, 지금 코드가 이렇게 동작한다는 뜻이 아니다.**
> 여기 그려진 A0~E5 세분화 검증 체인(원인 유형별로 동적으로 도구를 골라 부르는 방식)은 앞으로
> 만들어야 할 목표 설계다. 실제 구현된 `backend/nodes/hypothesis.py`·`critic.py`(Walking Skeleton)는
> 훨씬 단순하다 — `tier`(자동/반자동/근거없음) 하나로만 MCP 호출을 분기하고, `detect_change_points`
> (T8)는 아직 전혀 안 쓰며, Recipe 검증(A5)은 조회 자체를 안 하고 "사람 판정 필요"로만 남긴다.
> 실제 구현 현황은 `docs/skeleton_kickoff.md`(§4·§8)·`personalspace/0714 work/skeleton_study.md` 참고.
>
> 또한 §3.1 표와 §5.1.3/§5.2.3 예시가 언급하는 `motor_torque`(모터 토크)·`slurry_particle`(슬러리
> 대입자)는 2026-07-13 kg_rca 팀 결정(`kg_rca/MCP_KG_정합성검토.md` X1E)으로 "계측 불가 변수"로
> 제거하기로 확정됐다 — 이 두 값이 실제로 조회 가능하다는 전제로 짜인 예시 부분은 그 결정과 안
> 맞으니 참고할 때 감안할 것.

# 1. Tool 명세

- Tool별 코드: `secsgem-mcp/server/tools/*.py` 참고

| 공통
사용
여부 | # | 툴 | 역할 | 파라미터 | 반환 |
| --- | --- | --- | --- | --- | --- |
| O | T1 | `get_wafer_map` | 웨이퍼맵 이미지 및 메타 데이터 반환 (라벨 미포함) | `lot_id`, `wafer_id` | 웨이퍼맵 이미지 + 메타 데이터 |
| O | T2 | `get_lot_history` | lot의 공정 step별 장비 / chamber / recipe / 입출 시각 | `lot_id` | step별 (장비, chamber, recipe, 입출 시각) 목록 |
| O | T3 | `run_commonality_analysis` | 불량 lot 집합의 공통 장비 / chamber / recipe 집계 | `lot_ids[]`, (옵션) `step` | 공통 통과 장비/chamber/recipe 집계표 + 각 항목의 통과 lot 비율 |
| X | T4 | `get_normal_lot_ratio` | 특정 장비 통과 lot의 정상/불량 비율 | `equipment_id` 또는 `chamber_id`, `time_range` | 해당 장비 통과 lot 중 정상/불량 수와 비율 |
| X | T5 | `query_telemetry` | 장비 파라미터 시계열 + 정상 범위 | `equipment_id`, `time_range`, (옵션) `params[]` | 시계열 (ts, param, value) + 정상 범위 |
| X | T6 | `get_alarm_history` | S5F1 알람 목록 | `equipment_id` 또는 `lot_id`, `time_range` | S5F1 알람 목록 (ts, alarm_id, text) |
| X | T7 | `get_maintenance_history` | PM/BM 이력 | `equipment_id`, `time_range` | PM/BM 이력 (ts, type, 교체 부품) |
| X | T8 | `detect_change_points` | 수율/파라미터 변화점 + 인접 이벤트 정렬 | `metric`(수율/파라미터), `scope`, `time_range` | 변화점 시각 목록 + 인접 이벤트(PM/recipe 변경/알람) 정렬 |
| X | T9 | `get_lot_timeline` | lot 처리 전후 이벤트 통합 타임라인 | `lot_id` | 해당 lot 처리 전후의 관련 장비 이벤트 통합 타임라인 |

# 2. 시나리오 표준 파이프라인

```json
[진입] '분석' 트리거 (웨이퍼맵 이미지 + 시스템 프롬프트)
  ├─ A0: T1 get_wafer_map → VLM 판독 → 결함 클래스 추론(3개 중 하나)
  ├─ KG/GraphRAG 검색 (MCP 외부) → 후보 원인 공정 목록
  ├─ [Hypothesis Loop] 후보 원인마다:
  │    ├─ A1: T2+T3 commonality → 의심 장비 축소
  │    ├─ A2~6: T5/T6/T7/T8 시점 및 신호 확인  ← 원인 유형별 분기
  │    ├─ T4 negative evidence → 약한 가설 기각
  │    └─ T9 시간 선후 확인 → 선후 불일치 이벤트 기각
  ├─ evidence table 조립 (지지/반대/미확인/다음 액션)
  └─ [Critic] 시간 정합 / negative evidence 수행 여부 / Faithfulness 재검증 → 채택 or 반려 or "판단 불가"
```

# 3. 시나리오 (유형 A~E)

<aside>
📌

`→` 는 호출 순서, `∥` 는 병렬 호출을 의미함

</aside>

## 3.1 유형 A (A1~6) `표준 검증 흐름`

A0. 웨이퍼맵 확보와 판독 입력 (진입점)

- 트리거: 사용자가 원인 분석을 요청
- 시퀀스: T1 `get_wafer_map(lot_id, wafer_id)` → 이미지를 VLM에 전달 → 결함 클래스 및 형상 서술 응답
- 분기:
    - VLM 판독이 Center/Edge-Ring/Scratch → 해당 클래스의 후보 원인으로 가설 루프 진입
    - VLM 판독이 3클래스 외 패턴(예: Donut 유사) → 유사 경로: "본 평가 구성의 범위 밖 패턴"으로 보고하고 인스턴스 조사는 제한적으로 수행
    - 무패턴(’none’ 정상) 판정 → "결함 패턴 없음"을 보고하고 종료
- 주의
    - T1은 라벨을 반환하지 않으므로 판독 결과는 전적으로 VLM의 출력에 의존
    - 판독 불확실성에 대한 내용은 evidence table의 "미확인"란에 남김

A1. Commonality로 의심 장비 축소 (가설 루프의 첫 단계)

- 트리거: 같은 결함 패턴의 불량 lot 집합 수집
- 시퀀스:
    1. 각 불량 lot에 T2 `get_lot_history(lot_id)` ∥ (lot 수만큼 병렬)
    2. T3 `run_commonality_analysis(lot_ids[], step?)`
        - KG가 지목한 후보 공정(예: Edge-Ring→ETCH)을 `step` 옵션으로 좁혀 1차 호출
        - 호출 결과값이 없으면 step 미지정으로 전체 재호출
- Hypothesis Agent 판단 기준: 특정 장비/chamber의 통과 lot 비율이 배경 분포 대비 뚜렷이 높은가
    - 서버는 임계값을 정하지 않고 비율과 모수만 반환
- 분기:
    1. 몰림 후보 발견 → 해당 장비를 대상으로 유형 A2~A6 중 원인에 맞는 시나리오 진행 + 유형 B1이 필수적으로 병행되어야 함
    2. 몰림 없음 (모든 장비에 고르게 분산) → 장비 기인 가설 약화 → A5(recipe/자재 축) 또는 C1 경로 검토

A2. 정비(PM/BM) 직후 불량 급증 검증

- 트리거: A1에서 의심 장비 확보, 또는 KG 후보 원인이 "정비 후 이상"(예: CMP 패드 교체 후 스크래치)으로 나옴
- 시퀀스:
    1. T7 `get_maintenance_history(equipment_id, time_range)` : 불량 발생 구간 이전을 포함하도록 time range 설정
    2. T8 `detect_change_points(metric=수율, scope=해당 장비, time_range)` : 변화점과 정비 이벤트의 인접성 확인
    3. 정비 이벤트와 변화점이 근접하면 T9 `get_lot_timeline(대표 불량 lot)` 으로 개별 lot 수준의 선후 재확인
- 지지 판정: (정비 시각) < (수율 변화점) < (불량 lot들의 해당 step 처리 시각) 순서가 성립
- 분기: 정비 이벤트가 불량 발생 이후에만 존재 → 함정이므로 B2로 전환해 기각 처리

A3. 텔레메트리 드리프트 검증 (*Fab에서 FDC가 보는 종류의 신호를 에이전트가 확인하는 시나리오)

<aside>
📌

- 텔레메트리: 장비가 가동 중에 계속 내보내는 센서 측정값의 시계열
- 드리프트: 파라미터가 설정값 근처에 머물다가 어느 시점부터 서서히 한 방향으로 흘러가는 현상 **(’서서히’가 핵심임. 이상치로 인한 스파크와 다르기 때문에, “알람 기준치 ≠ 이상치”)**
- FDC(Fault Detection and Classification): Fab에서 텔레메트리를 실시간 감시해서 장비 이상을 잡아내는 시스템
</aside>

- 트리거
    - 의심 장비 및 시간 창이 좁혀짐
    - KG 후보 원인이 파라미터값이 이상한 계열 (예: Edge-Ring→에지 플라즈마 밀도, Center→샤워헤드 유량)
- 시퀀스:
    1. T5 `query_telemetry(equipment_id, time_range, params=[KG가 지목한 파라미터])` : 파라미터를 지정해 호출(전체 덤프 금지)
    2. 정상 범위 이탈/드리프트 구간 발견 시, T8 `detect_change_points(metric=해당 파라미터, ...)` 로 드리프트 시작점을 특정
    3. 드리프트 시작점과 불량 lot 처리 시각의 선후를 T9로 확인
- 지지 판정
    - 드리프트 시작 ≤ 불량 lot 처리 시각
    - 드리프트 구간에 처리된 lot에서 불량이 집중
- 분기:
    - 파라미터가 전 구간 정상 범위 내 → 이 파라미터 경로는 "지지 증거 없음"으로 기록(정상 범위 내 변동은 교란 신호일 수 있음…B3) → 다른 후보 파라미터 또는 다른 원인으로 이동

A4. 알람 동시성 검증

- 트리거
    1. 의심 장비 및 시간 창 확정
    2. A3에서 드리프트를 찾지 못해 알람 이벤트를 대신 확인
- 시퀀스: T6 `get_alarm_history(equipment_id, time_range)` → 알람 발생 시각과 불량 lot 처리 시각의 겹침 확인 → 겹치면 T9로 lot 단위 재확인
- 보조 사용: `lot_id` 파라미터 변형으로 "이 lot 처리 중 울린 알람"을 직접 조회 ~~(lot 관점 진입 시 T2 직후에 쓰기 좋음)~~
- 주의:
    - 배경에 무관 알람이 상시 주입되어 있어 교란 신호를 주므로,
    - 알람 존재만으로 지지 판정하면 안 되고 (a) 알람 대상 장비가 commonality 결과와 일치하는지, (b) KG 메커니즘과 연결되는지를 함께 확인 → 불일치 시 B3

A5. Recipe/조건 변경 시점 검증

- 트리거: A1 결과가 장비 몰림이 아니라 recipe 몰림(같은 recipe_id 공유)을 보일 때
- 시퀀스:
    1. T3 결과에서 공통 recipe 확인 → T2 이력들에서 해당 recipe의 최초 사용 시각 특정.
    2. T8 `detect_change_points(metric=수율, scope=해당 step, time_range)` : 변화점이 recipe 전환 시각과 인접한지 확인
    3. T4 `get_normal_lot_ratio` 를 recipe 관점의 보조 확인으로 사용: 같은 장비에서 다른 recipe로 처리된 lot이 정상인지 대조(장비 기인 가설과의 변별)
- 지지 판정: recipe 전환 이후 처리 lot에 불량 집중 + 같은 장비의 타 recipe lot은 정상

A6. 소모품 수명 / 교체 이력 검증 (Scratch 특화)

- 트리거:
    - VLM 판독이 Scratch
    - Scratch의 후보 원인 3종(CMP 패드 마모, 슬러리 대입자, 세정 브러시)이 모두 소모품 및 연속 사용 마모 계열이므로, 교체 이력과 사용량 파라미터가 결정적 단서임
- 시퀀스:
    1. A1을 `step=CMP`, `step=세정`으로 각각 실행해 몰림 장비를 좁힘 (T3 보조)
    2. T7 `get_maintenance_history(해당 장비, time_range)` : 교체 부품 필드에서 패드/컨디셔너/브러시 교체 시점 확인
    3. T5 `query_telemetry(params=[패드 사용 시간, 슬러리 유량, 브러시 압력 등])` : 마모 누적 또는 입자 이상 신호 확인
    4. 교체 시점 및 드리프트와 불량 lot 처리 시각의 선후 판정 (A2와 동일, T9 보조)
- 변별 포인트
    - 같은 CMP 장비라도 원인별 신호가 다름
        - 패드 마모는 사용 시간 누적 + 교체 직전 불량 집중
        - 슬러리 대입자는 교체 주기와 무관한 유량/입자 이상
- 특이점
    - Scratch는 모수가 작아(1,193장) commonality 신호가 약할 수 있음
    - lot 수가 하한(예: 5 lot) 미만이면 통계적 판단을 유보하고 evidence table의 "미확인"에 모수 부족을 명시 → C2와 연결
- 클래스 × 원인 후보 ⇒ 시나리오 체인 매핑
    - 각 원인을 검증하는 표준 툴 체인
    - A1(commonality)과 B1(negative evidence), B2(시간 정합)는 원인과 무관하게 모든 체인에 포함됨
    
    | 클래스 | 후보 원인 (배정 확률) | 검증 체인 | 결정적 단서가 놓이는 곳(신호원) |
    | --- | --- | --- | --- |
    | **Center** | **증착 챔버 중심부 불균일 — 샤워헤드 막힘 (55%)** | **A1(step=증착) → A3(유량/압력) → A4** | **증착 장비 텔레메트리 드리프트** |
    | Center | CMP 중심 과연마 (25%) | A1(step=CMP) → A3(연마 압력/패드) → A2 | CMP 파라미터 or 정비 직후 시점 |
    | ~~Center~~ | ~~세정 노즐 중심 분사 이상 (20%)~~ | ~~A1(step=세정) → A4 → A2~~ | ~~세정 장비 알람/BM 이력~~ |
    | **Edge-Ring** | **식각 불균일 — 에지 플라즈마 밀도 (60%)** | **A1(step=식각) → A3(RF power/압력) → A4** | **etcher chamber 텔레메트리** |
    | Edge-Ring | CMP 엣지 과연마 (25%) | A1(step=CMP) → A3 → A2 | CMP 정비(패드 교체) 선후 |
    | Edge-Ring | 세정 문제 (15%) | A1(step=세정) → A4 → A2 | 세정 알람/정비 |
    | **Scratch** | **CMP 패드 마모/컨디셔닝 이상 (45%)** | **A1(step=CMP) → A6(패드 교체 이력·사용 시간) → A2** | **패드 사용 시간 누적 + 교체 선후** |
    | Scratch | CMP 슬러리 대입자 오염 (35%) | A1(step=CMP) → A6(슬러리 유량/입자) → A4 | 슬러리 계열 텔레메트리 및 알람 (교체 주기와 무관) |
    | Scratch | 세정 브러시 접촉 이상 (20%) | A1(step=세정) → A6(브러시 교체 이력) → A2 | 세정 정비 선후 |
    - 참고 (결함 및 원인 세부 설명)
        - Center
            - 특징: 웨이퍼의 기하학적 중심 부근에 불량 die가 집중된 형태
            - 추론 원인 공정 단계
                - Thin-film Deposition(박막 증착)
                - Chemical Mechanical Polishing (CMP, 화학적 기계적 연마)
                - Photolithography Alignment (웨이퍼의 회로 패턴을 새기는 단계)
                - Cleaning Processes (세정(Wet/Dry Cleaning) 단계)
            - 메커니즘
                - Thin-film Deposition(박막 증착) 관련
                    - 증착 과정에서의 변동성(variations)이나 균일하지 않은 도포(non-uniformities)가 발생하면, 웨이퍼 중심부의 표면 결함이나 박막 두께에 불일치가 생길 수 있음
                - CMP 관련
                    - 부적절하거나 불균일한 연마가 수행될 경우 웨이퍼 표면의 지형(surface topography) 변동이 발생함
                    - 특히 웨이퍼의 평탄도(planarity)를 일정하게 유지하는 것이 중요한 중심 영역에서 이러한 연마 불균형이 집중적인 결함으로 나타남
                - Photolithography Alignment 관련
                    - 웨이퍼의 회로 패턴을 새기는 단계에서, 특히 웨이퍼 중심 부근에서 패턴 왜곡(pattern distortions)이나 오버레이(overlay) 오류가 생길 수 있음
                - 세정 관련
                    - 세정 과정 중 잔류물(Residues)이나 입자들이 제거되지 않고 남아있는 상태에서, 웨이퍼 표면을 스치고 지나가며 긁힘을 만듦
        - Edge-Ring
            - 특징: 웨이퍼의 가장자리(perimeter)를 따라 링 형태의 불량 패턴이 나타남
            - 추론 원인 공정 단계
                - Etching(식각)
                - ~~Edge-bead removal(엣지 비드 제거)~~
                - Cleaning Processe
            - 메커니즘
                - 공정 단계에서의 결함이나 일관성 부족이 웨이퍼 테두리 근처에 오염 또는 물리적 손상을 발생시키며, 이것이 가장자리를 따라 원형의 결함 분포를 형성한다고 설명
        - Scratch
            - 특징: 선형적인 줄무늬(linear streaks)나 긁힘(scratches)이 웨이퍼 표면을 가로지르는 형태
            - 추론 원인 공정 단계
                - CMP
                - Cleaning Processes
            - 메커니즘
                - CMP 관련
                    - 슬러리(Slurry) 내의 연마 입자나 패드(Pad) 상태가 제대로 제어되지 않을 때 발생
                    - 표면의 불균일한 압력이나 연마 입자의 오염이 웨이퍼 표면에 스크래치를 형성
    - 같은 클래스의 원인들이 서로 다른 step / 장비 / 신호원에 단서를 두므로, Hypothesis Agent는 클래스명만으로 원인을 단정할 수 없고 체인을 실제로 실행해야 변별됨
    - recipe 변경 원인(A5)은 결함 클래스와 독립적이므로, 모든 클래스 시나리오에서의 후보 원인이 될 수 있음 (A1의 분기 ii 참고)

## 3.2 유형 B (B1~3) `반증 흐름(가설 기각)`

B1. Negative evidence로 장비 가설 기각 (모든 가설에 필수)

- 트리거:
    - A1~A6로 특정 장비/chamber가 의심 후보로 지목됨
    - 지지 증거가 아무리 강해도 이 시나리오를 건너뛰면 Critic이 반려함(D2)
- 시퀀스: T4 `get_normal_lot_ratio(equipment_id or chamber_id, time_range)` (불량 발생과 같은 시간 창으로 조회)
- 판단 분기:
    1. 해당 장비 통과 lot의 불량률이 배경 대비 유의하게 높음 → 가설 유지, 결과를 evidence table "지지"란에 기록
    2. 정상 lot이 다수 통과 (불량률이 배경과 비슷) → 가설 기각
    3. 통과 lot 모수 자체가 작음 → 판단 유보, "미확인"에 모수와 함께 기록 (C2 연계)
- 주의:
    - 분모 정의(라벨 확정 정상만 vs 미라벨 배경 물량 포함)가 응답에 명시되므로, evidence table에 그대로 옮겨 적음
    - 두 정의의 비율이 크게 다르면 그 자체를 불확실성으로 보고함

B2. 시간 선후 불일치로 이벤트 기각

- 트리거:
    - 그럴듯한 이벤트(PM, recipe 변경, 알람)를 원인 후보로 잡았으나 선후관계 미확인 상태 (ex. 불량 발생 이후의 PM)
- 시퀀스:
    - T9 `get_lot_timeline(불량 lot 대표 2~3개)` → 이벤트 시각과 각 lot의 해당 step 처리 시각(`ts_in`/`ts_out`) 비교
    - ~~필요 시 T8로 수율 변화점 시각을 함께 놓고 3자 비교~~
- 판단 분기:
    1. 이벤트가 불량 lot 처리보다 앞 → 시간 정합 통과, 가설 유지
    2. 이벤트가 불량 lot 처리보다 뒤 → 원인 후보에서 제외
        - "시간 선후 불일치"를 evidence table "반대"란에 명시

B3. 교란 신호 배제

- 트리거: A4/A3에서 발견한 알람/변동이 KG 메커니즘 또는 commonality 결과와 연결되지 않을 때
- 시퀀스: (Tool 호출이 아니고 판정 규칙임) 발견된 신호에 대해 다음 3문항을 체크
    1. 신호의 장비가 T3 결과의 몰림 장비인가? (아니면 무관 장비 알람일 가능성)
    2. 신호가 정상 범위를 실제로 이탈했는가? (T5 응답의 정상 범위 필드로 확인)
    3. KG에 해당 신호→결함 메커니즘 경로가 있는가? (MCP 밖, GraphRAG)
- 판단:
    - 위 3 문항 중 하나라도 "아니오"면 지지 증거로 쓰지 않고 "배제된 신호"로 기록만 함
    - 배제 기록 자체가 Critic의 faithfulness 점검(D3)에서 "확인했으나 무관"의 근거

## 3.3 유형 C (C1~4) `판단 불가 / 데이터 부족`

C1. 매칭 불가 ("판단 불가 + 다음 확인 항목" 반환)

- 트리거: 가설 루프를 전부 소진 (모든 KG 후보 원인에 대해 A 체인이 지지 증거를 찾지 못했고, B1/B2로 살아남은 가설이 없음)
- 시퀀스: 추가 툴 호출 없음. 지금까지의 evidence table을 근거로…
    1. "판단 불가"를 결론으로 명시 (그럴듯한 원인을 지어내지 않는다)
    2. 수행한 확인 목록(호출한 툴 / 범위 / 결과 요약)을 첨부
    3. 다음 확인 항목을 권고: 미조회 시간 창, 미확인 파라미터, `coverage.missing` 항목, 오프라인 확인(파괴 분석 등 시스템 범위 밖) 등
- 금지: "단서가 없으므로 가장 흔한 원인인 X로 추정" 식의 fallback (판단 불가 적정성 지표에서 오답 처리되며, 최빈 원인 고정 응답 베이스라인과 구분되지 않는 응답)

C2. 부분 커버리지 ( `coverage.missing` 처리)

- 트리거: 임의의 툴 응답에 `coverage.missing`이 비어 있지 않음 (예: "ETCH-02의 2일치 텔레메트리 없음")
- 처리 규칙:
    1. missing 구간에 대한 어떤 주장도 하지 않음: "그 기간 이상 없음"이라고 말하는 것도 금지(확인 못 한 것과 이상 없음은 다름)
    2. missing 항목을 evidence table "부족한 데이터"란에 그대로 인용
    3. missing 구간이 가설 판정에 결정적이면(예: 드리프트 시작 추정 시점이 하필 결측 구간) 해당 가설의 결론을 "미확인"으로 유지하고 다음 확인 액션에 올림
- 비고:
    - Critic은 최종 설명이 missing 항목을 "확인한 사실"처럼 인용했는지를 검사(D3)
    - 이 시나리오의 처리 품질이 faithfulness 점수를 좌우함

C3. 조회 범위 밖 (빈 결과 / 무효 키)

- 트리거
    1. 존재하지 않는 `lot_id`/`equipment_id`
    2. 타임라인(90일) 밖의 `time_range`
    3. 데이터가 아예 없는 조합 
- 서버 동작
    - 오류가 아니라 빈 결과 + coverage로 사유 명시를 반환(`time_range_available`과 대조 가능)
    - 그럴듯한 값 보간 금지
- Hypo 에이전트 동작:
    - 키 오타 가능성 → T2/T3 등 앞선 응답에서 받은 식별자를 재확인 후 1회 재시도
    - 실제로 범위 밖 → 그 사실을 기록하고 조회 계획을 수정 (반복 재시도 금지)

C4. 범위 밖 가설 (후공정 원인 차단)

- 트리거
    1. 에이전트가 후공정(패키징, final test) 원인 가설을 세움
    2. 사용자가 후공정 데이터를 요청
- 처리
    - 모든 응답의 `scope_note`("전공정~wafer test 단계 데이터. 패키징 이후 이력 없음")가 근거
    - Hypo 에이전트는 해당 가설을 "본 시스템에서 검증 불가"로 분류하고, 조사를 계속하는 대신 범위 제한을 사용자 응답에 명시
    - Critic은 후공정 가설이 인스턴스 증거를 가진 것처럼 서술되면 반려
- 변형: A0에서 VLM이 3클래스 외 패턴을 판독한 경우도 동일 골격 ("평가 구성 범위 밖"을 명시하되, commonality 등 클래스 무관 조회는 참고용으로 제공할 수 있음)

## 3.4 유형 D (D1~3) `Critic 관련`

<aside>
📌

- Critic은 Hypothesis의 조사를 재현하는 것이 아니라, 채택 가설의 필수 조건을 표적 재확인
- 호출량은 가설당 1~3회로 제한
</aside>

D1. 시간 정합 재확인

- 트리거: Hypothesis가 가설을 채택해 넘김 (항상 수행)
- 시퀀스: T9 `get_lot_timeline(채택 가설의 대표 불량 lot)` 1회 (지목된 원인 이벤트가 lot 처리보다 앞서는지 독립 재확인)
- 판정:
    - 선후가 뒤집혀 있으면 반려 + 재계획 지시
    - Hypo의 B2 수행 여부와 무관하게 독립적으로 확인(이중 방어)

D2. Negative evidence 수행 여부 점검

- 트리거: 채택 가설이 특정 장비/chamber/recipe를 지목함 (항상 수행)
- 시퀀스:
    - evidence table에 T4 결과가 있는지 확인
        1. → 없으면 즉시 반려 (호출 없이 판정 가능)
        2. → 있으면 T4를 동일 파라미터로 1회 재호출해 수치 일치 확인(전사 오류 / 선택적 인용 방지)
- 판정: T4 결과가 가설과 모순(정상 lot 다수 통과)인데 채택됐으면 반려

D3. Faithfulness (인용 검사)

- 트리거: 최종 설명문 생성 후 (항상 수행)
- 시퀀스: 설명문이 인용한 각 사실에 대해 근거 툴 응답이 존재하는지 대조
    - `coverage.missing`에 있는 항목을 확인된 사실처럼 인용 → faithfulness 실패 처리
    - 수치 증거 없이 패턴만으로 원인 단정("Edge-Ring이니까 식각") → 반려 (3클래스 체제의 1차 방어선)
    - KG 메커니즘 연결 문장 부재 → 재계획 지시 (상관≠인과)
    - "다음 확인 항목/권고 조치" 섹션 부재 → 보완 지시

## ~~3.5 유형 E (E1~5) `오용 / 안티 패턴 (서버/에이전트가 막아야 하는 호출임)` (Optional)~~

<aside>
📌

- E1~E5는 M3 통합 테스트에서 음성 테스트 케이스(호출했을 때 유출/폭주가 일어나지 않음을 확인)로 구현
</aside>

E1

- 안티 패턴: T1 `get_wafer_map` 응답에서 결함 라벨을 얻으려 함
- 올바른 동작
    - 서버는 라벨(`failureType`)을 절대 반환하지 않음
    - 판독은 VLM의 몫
    - 라벨 노출, 즉 정답 유출은 태스크 자체를 무효화하는 것임

E2

- 안티패턴: 툴 응답에 "원인 추정" 텍스트를 기대하거나, 응답 문구를 원인 결론으로 직인용
- 올바른 동작
    - 서버는 사실만 반환
    - Hypo 에이전트는 KG 메커니즘과 교차한 뒤에만 원인 서술 가능

E3

- 안티패턴: T5를 파라미터/기간 무제한으로 호출해 전체 텔레메트리 덤프
- 올바른 동작
    - 서버는 최대 포인트 수 제한 + 다운샘플링 적용
    - Hypo 에이전트는 KG가 지목한 파라미터와 좁힌 시간 창으로 호출해야 함

E4

- 안티패턴: T2를 수십 lot에 호출한 뒤 Hypo 에이전트가 컨텍스트 안에서 직접 공통 장비를 집계
- 올바른 동작
    - 집계는 T3 `run_commonality_analysis`의 역할
    - Hypo 에이전트가 직접 집계하는 것은 컨텍스트 폭주와 계산 오류를 부름

E5

- 안티패턴: ground truth에 접근하는 툴/파라미터 탐색
- 올바른 동작
    - 우리 시스템에서 다루지 않는 인터페이스임
    - ground truth는 서버가 읽지 않는 평가 전용 파일

# 4. Tool x 시나리오

<aside>
📌

- ●=핵심 호출, ○=조건부/보조 호출
- 읽는 법
    - 본 매트릭스에 미포함된 시나리오 C1/C2/C4/D3/E*는 특정 툴에 결부되지 않는 시나리오(판정 규칙/메타 필드 처리)
    - 모든 툴이 최소 하나의 핵심(●) 시나리오를 가짐
</aside>

| 툴 | A0 | A1 | A2 | A3 | A4 | A5 | A6 | B1 | B2 | C3 | D1 | D2 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T1 `get_wafer_map` | ● |  |  |  |  |  |  |  |  | ○ |  |  |
| T2 `get_lot_history` |  | ● |  |  | ○ | ● |  |  |  | ○ |  |  |
| T3 `run_commonality_analysis` |  | ● |  |  |  | ● | ○ |  |  |  |  |  |
| T4 `get_normal_lot_ratio` |  |  |  |  |  | ○ |  | ● |  |  |  | ● |
| T5 `query_telemetry` |  |  |  | ● |  |  | ● |  |  | ○ |  |  |
| T6 `get_alarm_history` |  |  |  |  | ● |  | ○ |  |  | ○ |  |  |
| T7 `get_maintenance_history` |  |  | ● |  |  |  | ● |  |  | ○ |  |  |
| T8 `detect_change_points` |  |  | ● | ○ |  | ● |  |  | ○ |  |  |  |
| T9 `get_lot_timeline` |  |  | ○ | ○ | ○ |  | ○ |  | ● |  | ● |  |

# 5. End-to-End 샘플 시나리오 (수정 중)

## 5.1 복잡한 시나리오

### 5.1.1 Center

<aside>
📌

- 데이터 설계
    - 진짜 원인은 “증착 챔버 중심부 불균일 (샤워헤드 막힘, 누적형 드리프트)”
    : CVD-03/CH-A의 샤워헤드 막힘
        - `shower_flow`가 정비 이벤트없이 점진 하강하는 누적형 드리프트(A1(step=증착) → A3(유량/압력) → A4)
        - 함정으로
            - (a) CVD-03에 무관 배경 알람 `HEATER_TEMP_DEV`가 전 기간 산발 주입(교란 신호)
            - (b) CLEAN-01은 불량 lot 다수가 통과하지만 정상 lot도 대량 통과(negative evidence 함정)
- 총 툴 호출 ~19회(T2 병렬 10회 포함)
- 원인이 이벤트형(PM)이 아닌 누적형이므로 시작점 근거가 T7 정비 이력이 아니라 T8 변화점이고, 임계 기반 알람(FLOW_LOW)이 드리프트에 크게 후행함을 보여줌
- "알람 기준치 ≠ 이상치"를 에이전트가 텔레메트리로 보완해야 하는 전형적인 사례임
- A1의 두 호출 패턴(시퀀스 1 step 지정 1차 → 시퀀스 2step 미지정 재호출)도 함께 커버함
</aside>

1. T1 get_wafer_map(L3108, 12) → VLM: "Center, 웨이퍼 중심부에 불균일한 결함"
2. KG 질의 (MCP 밖) → 후보: 샤워헤드 막힘 / CMP 중심 과연마 / 세정 노즐 분사 이상
3. T2 ×10 (불량 lot 10개 이력) ∥ 병렬
4. T3 run_commonality_analysis(10 lots,
step=증착) → CVD-03/CH-A 9/10 (90%) [A1 → KG 최우선 후보 공정으로 1차 축소]
    
    → 가설 H1: CVD-03/CH-A 샤워헤드 막힘
    
5. T4 get_normal_lot_ratio(CVD-03/CH-A) → 통과 62 lot 중 불량 13 (배경 불량률의 5배) [B1 → 가설 유지 결정]
6. T5 query_telemetry(CVD-03, D-30..D-1,
params=[shower_flow, pressure]) → shower_flow 완만 하강, D-12부터 정상 범위 이탈
coverage.missing: "D-22~D-21 텔레메트리 결측" [A3]
7. T8 detect_change_points(
metric=shower_flow, scope=CVD-03) → 변화점 D-25, 인접 이벤트 없음(PM/recipe 무관) [A3 → 시작점 특정]
8. T6 get_alarm_history(CVD-03, D-30..D-1)→ FLOW_LOW D-8부터 (드리프트보다 17일 후행 → 임계 기반 알람의 한계) + HEATER_TEMP_DEV 전 기간 산발 [A4]
9. HEATER_TEMP_DEV에 B3 3문항 → 정상 범위 내 변동 + KG 메커니즘 경로 없음
    
    → "배제된 신호"로 기록만 [B3 → 배제된 신호로 기록 (함정(a)에 해당)]
    
10. T9 get_lot_timeline(L3108) → 드리프트 시작(D-25) < 불량 lot 증착(D-16~D-4) [B2 → 시간 정합성 통과]
    
    → 가설 H2: CMP 중심 과연마 / H3: 세정 노즐
    
11. T3 run_commonality_analysis(10 lots) → step 미지정 전체 재호출: CLEAN-01 8/10 (80%), CMP 계열 분산(최대 4/10) [A1 분기 → H2 몰림 없음 → 약화]
12. T4 get_normal_lot_ratio(CLEAN-01) → 통과 195 lot 중 불량 9 (배경 수준) [B1 → H3 기각 결정 (함정(b)에 해당)]
13. evidence table 조립:
H1 지지: commonality 90%(step=증착) / D-25 시작 드리프트 및 D-12 범위 이탈 / FLOW_LOW 동시성 / 시간 정합
반대: 없음 미확인: D-22~D-21 결측(coverage.missing) 배제: HEATER_TEMP_DEV(B3)
H2 지지 없음(몰림 없음) → 약화 H3 반대: 정상 lot 다수 통과 → 기각
14. Critic: D1 (T9 재확인, 통과) / D2 (T4 기록 존재+재호출 일치, 통과)
/ D3 (missing 미인용, 배제 신호 기록 존재, KG 메커니즘 문장 존재, 통과)
→ 채택: "CVD-03 CH-A 샤워헤드 막힘 (증착 사이클 누적에 따른 유량 점진 저하)"
    - 다음 확인 항목: D-22~D-21 결측 구간 확보, 샤워헤드 오프라인 점검(파티클/막힘 육안 확인)

### 5.1.2 Edge-Ring

<aside>
📌

- 데이터 설계
    - 실제 원인은 “식각 불균일 (PM 후 RF power 드리프트)” ****: ETCH-02/CH-B의 RF power 드리프트(PM 이후 시작)
    - 함정으로 (a) CMP-01은 불량 lot 다수가 통과하지만 정상 lot도 대량 통과, (b) 불량 발생 이후 ETCH-01에 PM 기록
- 총 툴 호출 ~20회(T2 병렬 12회 포함)
</aside>

1. T1 get_wafer_map(L4522, 7) → VLM: "Edge-Ring, 웨이퍼 테두리 근처에 링 형태의 결함 패턴"
2. KG 질의 (MCP 밖) → 후보: 식각 불균일 / CMP 에지 과연마 / 세정
3. T2 ×12 (불량 lot 12개(임의값) 이력) ∥ 병렬
4. T3 run_commonality_analysis(12 lots) → ETCH-02/CH-B 11/12 (92%), CMP-01 10/12 (83%)
    
    → 가설 H1: ETCH-02/CH-B 식각 불균일
    
5. T4 get_normal_lot_ratio(ETCH-02/CH-B) → 통과 84 lot 중 불량 15 (배경 불량률의 6배) [B1 → 가설 유지 결론]
6. T7 get_maintenance_history(ETCH-02) → D-31 PM (ETCH 링 부품 교체) [A2]
7. T5 query_telemetry(ETCH-02, D-31..D-1,
params=[RF_power]) → D-31 이후 계단형 드리프트, 정상 범위 이탈 [A3 → 가설 지지 결론]
8. T9 get_lot_timeline(L4522) → PM(D-31) < 드리프트 < L4522 식각(D-18) [B2 → 시간 정합성 통과]
    
    → 가설 H2: CMP-01 에지 과연마
    
9. T4 get_normal_lot_ratio(CMP-01) → 통과 210 lot 중 불량 12 (배경 수준) [B1 → 기각 결정(함정(a)에 해당함)]
    
    → 함정(b) 점검
    
10. T9 (3번에서 확보한 이력과 대조) → ETCH-01 PM은 D-5, 불량 lot 처리는 D-20~D-9 [B2 → 이벤트가 불량 lot 처리보다 뒤에 있으므로 후보 제외 (함정(b)에 해당)]
11. evidence table 조립
    
    H1 지지: commonality 92% / PM 직후 드리프트 / 시간 정합 반대: 없음 미확인: D-14 CH-B 압력 결측(coverage.missing)
    H2 반대: 정상 lot 다수 통과 → 기각
    
12. Critic:
    
    D1 (T9 재확인, 통과) / D2 (T4 기록 존재+재호출 일치, 통과) / D3 (missing 미인용, KG 메커니즘 문장 존재, 통과)
    
    → 가설 채택: "ETCH-02 CH-B 에지 플라즈마 불균일 (PM 후 RF power 드리프트)" + 다음 확인 항목: D-14 압력 데이터 확보
    

### 5.1.3 Scratch

<aside>
📌

- 데이터 설계
    - 진짜 원인은 “CMP 패드 마모/컨디셔닝 이상 (수명 초과, 교체 직전 집중)” : CMP-02/PLATEN-1의 패드 과사용 마모
        - `pad_usage_hours`가 권장 수명을 D-10에 초과하고 컨디셔닝 이력이 없어, 불량이 패드 교체(D-1) 직전(D-9~D-2)에 집중되고 교체 후 소멸(A1(step=CMP) → A6(패드 교체 이력/사용 시간) → A2)
        - 함정/변별 요소
            - (a) D-1 패드 교체 기록 : "정비 직후 불량"(A2)으로 오독하면 오답이며 선후를 lot 단위로 확인해야 함
            - (b) 같은 CMP 장비의 경쟁 원인인 슬러리 대입자와의 변별: 슬러리 계열 파라미터는 전 구간 정상
            - (c) Scratch 소모수: 확보 lot 6개로 하한(5 lot) 근접
- 총 툴 호출 ~15회(T2 병렬 6회 포함)
</aside>

1. T1 get_wafer_map(L5017, 3) → VLM: "Scratch, 선형 흔적"
2. KG 질의 (MCP 밖) → 후보: CMP 패드 마모/컨디셔닝 / CMP 슬러리 대입자 / 세정 브러시
3. 동일 기간 동일 판독 lot 수집 → 6 lot (하한 5 이상 → 통계 판단 가능하나 소모수 명심, A6 특이점)
4. T2 ×6 (불량 lot 6개 이력) ∥ 병렬
5. T3 run_commonality_analysis(6 lots, step=CMP) → CMP-02/PLATEN-1 6/6 (100%, n=6)
T3 run_commonality_analysis(6 lots, step=세정) → 분산(최대 3/6) [A6-1 → H3 세정 브러시 조기 약화]
    
    →가설 H1: CMP-02 패드 마모/컨디셔닝 이상
    
6. T4 get_normal_lot_ratio(CMP-02/PLATEN-1,
D-14..D-1) → 통과 21 lot 중 불량 6 (배경 불량률의 9배) [B1 → 가설 유지 결정]
7. T7 get_maintenance_history(CMP-02) → 패드 교체 D-1, 직전 교체 D-43 (권장 주기 30일 초과 사용)
컨디셔닝 디스크 교체 이력 없음 [A6-2]
8. T5 query_telemetry(CMP-02, D-43..D-1,
params=[pad_usage_hours, motor_torque,
slurry_flow, slurry_particle]) → pad_usage_hours D-10에 권장 수명 초과,
motor_torque 상승 드리프트(마모 부하)
slurry_flow·particle 전 구간 정상 [A6-3]
9. 슬러리 가설(H2) 판정 → 슬러리 계열 파라미터 정상 + 불량 집중이 슬러리 교체
주기와 무관하고 패드 수명과 정합
    
    → H2 "지지 증거 없음" 기록 [A3 분기 및 변별(b)에 해당]
    
10. T9 get_lot_timeline(L5017) → 수명 초과(D-10) < 불량 lot CMP 처리(D-9~D-2) < 패드 교체(D-1)
원인 이벤트는 교체가 아니라 수명 초과 → 선후 정합 [B2 → 함정(a)에 해당]
11. T4 get_normal_lot_ratio(CMP-02, D-1..D+7) → 교체 후 통과 12 lot 전부 정상 : 교체로 불량이 멈춘 것이므로 마모 가설 보강 (교체≠원인, 교체=종결) [B1 → 변형]
12. evidence table 조립:
H1 지지: commonality 100%(단 n=6) / 패드 수명 초과 D-10 + torque 드리프트 / 컨디셔닝 부재
/ 불량이 교체 직전 집중 및 교체 후 소멸 / 시간 정합
반대: 없음 미확인: 소모수(n=6, 통계력 제한)를 명시적으로 기록
H2 지지 없음(슬러리 파라미터 정상) → 기각 H3 몰림 없음 → 약화
13. Critic: D1 (T9 재확인 — 수명 초과가 처리보다 앞섬, 통과) / D2 (T4 기록 존재+재호출 일치, 통과)
/ D3 (소모수 한계를 결론에 병기, KG 메커니즘 문장 존재, 통과)
→ 채택: "CMP-02 PLATEN-1 패드 과사용 마모 (권장 수명 초과 + 컨디셔닝 미실시)"
    - 다음 확인 항목: 교체된 패드 오프라인 표면 검사, 컨디셔닝 레시피/주기 설정 점검

## 5.2 간단 시나리오

<aside>
📌

- 
</aside>

### 5.2.1 Center : **CMP 중심 과연마 (`cmp_center_overpolish`)**

1. T1 get_wafer_map(L2201, 5) → VLM: "Center, 중심 클러스터"
2. KG 질의 (MCP 밖) → 후보: 증착 55% / CMP 중심 과연마 25% / 세정 노즐 20%
3. T2 ×8 (불량 lot 8개 이력) ∥ 병렬
4. T3 run_commonality_analysis(8 lots, step=DEPO) → 분산(최대 3/8) — 1순위 후보 약화
T3 run_commonality_analysis(8 lots, step=CMP) → CMP-01-CH2 7/8 (88%) [A1]
5. T4 get_normal_lot_ratio(CMP-01-CH2) → 통과 88 lot 중 불량 8 (배경의 4배) [B1: 유지]
6. T7 get_maintenance_history(CMP-01) → D-20 BM "부품 교체" [A2]
7. T5 query_telemetry(CMP-01, D-20..D-1,
params=[slurry_flow]) → D-20부터 선형 상승
(coverage.missing 1건 → "미확인" 기록) [A3]
8. T9 get_lot_timeline(L2201) → BM(D-20) < 드리프트 < CMP 처리(D-19~D-13) [B2: 정합]
9. evidence table: 지지 4건 / 반대 없음 / 미확인 1건(결측)
Critic D1·D2·D3 통과 → 채택: "CMP-01-CH2 중심 과연마 (부품 이상 후 slurry_flow 상승)"

### 5.2.2 **Edge-Ring : CMP 에지 과연마 (`cmp_edge_overpolish`)**

1. T1 get_wafer_map(L3310, 9) → VLM: "Edge-Ring, 테두리 링"
2. KG 질의 (MCP 밖) → 후보: 식각 60% / CMP 에지 과연마 25% / 세정 15%
3. T2 ×8 ∥ 병렬
4. T3 run_commonality_analysis(8 lots, step=ETCH) → 분산(최대 4/8) — 1순위 후보 약화
T3 run_commonality_analysis(8 lots, step=CMP) → CMP-02-CH1 7/8 (88%) [A1]
5. T4 get_normal_lot_ratio(CMP-02-CH1) → 통과 76 lot 중 불량 7 (배경의 5배) [B1: 유지]
6. T7 get_maintenance_history(CMP-02) → D-15 BM "부품 교체" [A2]
7. T5 query_telemetry(CMP-02, D-15..D-1,
params=[down_force]) → D-15부터 선형 상승, D-9부터 상한 간헐 돌파 [A3]
8. T6 get_alarm_history(CMP-02) → "down_force out of range" D-9~ (드리프트에 후행) [A4 보조]
9. T9 get_lot_timeline(L3310) → BM(D-15) < 불량 lot CMP 처리(D-14~D-8) [B2: 정합]
10. evidence table → Critic 통과 → 채택: "CMP-02-CH1 에지 과연마 (down_force 상승 드리프트)"

### 5.2.3 **Scratch : CMP 슬러리 대입자 (`cmp_slurry_particle`)**

1. T1 get_wafer_map(L6114, 2) → VLM: "Scratch, 선형 흔적"
2. KG 질의 (MCP 밖) → 후보: 패드 마모 45% / 슬러리 대입자 35% / 세정 브러시 20%
3. 동일 판독 lot 수집 → 5 lot (하한 충족, 소모수 명심)
4. T2 ×5 ∥ 병렬
5. T3 run_commonality_analysis(5 lots, step=CMP) → CMP-01-CH1 5/5 (100%, n=5) [A1]
6. T4 get_normal_lot_ratio(CMP-01-CH1) → 통과 19 lot 중 불량 5 (배경의 8배) [B1: 유지]
7. T5 query_telemetry(CMP-01, D-14..D-1,
params=[pad_usage_hours, slurry_flow]) → pad_usage_hours 정상(수명 내, 정기 리셋)
slurry_flow D-12부터 계단 상승 [A6: 패드 배제+슬러리 지지]
8. T7 get_maintenance_history(CMP-01) → D-12 BM "부품 교체" (정기 주기와 무관 시점) [A2]
9. T9 get_lot_timeline(L6114) → BM(D-12) < 불량 lot CMP 처리(D-11~D-6) [B2: 정합]
10. evidence table (미확인: n=5 소모수 명시) → Critic 통과
→ 채택: "CMP-01-CH1 슬러리 대입자 (slurry_flow 계단 이상, 패드 수명 정상)"

# 6. Agent 결합

1. Hypothesis Agent
    
    <aside>
    📌
    
    가설별 검증 계획에 MCP Tool을 매핑
    
    </aside>
    
    1. KG/문헌에서 결함 패턴(Center/Edge-Ring/Scratch)의 후보 원인 공정 확보
    2. `get_lot_history` + `run_commonality_analysis`로 불량 lot의 공통 인스턴스 확인
    3. 공통 장비에 대해 `query_telemetry` / `get_alarm_history` / `get_maintenance_history`로 시점 일치 확인
    4. `get_normal_lot_ratio`로 반대 근거 확인 → 약한 가설 기각
    5. 가설별 evidence table(지지/반대/미확인/다음 액션) 조립 (P8)
2. Critic Agent