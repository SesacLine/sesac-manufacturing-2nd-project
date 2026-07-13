# SECS/GEM MCP Server

WM-811K / MixedWM38 웨이퍼맵과 SECS/GEM 시뮬레이터 기반 합성 공정·장비 데이터를
lot/wafer 키로 결합해 제공하는 인스턴스 수준 RCA(근본 원인 분석)용 MCP 서버.

지식그래프/문헌 RAG가 "이 결함 유형은 일반적으로 어떤 공정 원인과 연결되는가"(일반 지식)를
답한다면, 이 서버는 "이 lot/wafer는 실제로 어떤 장비를 지났고 그때 무슨 일이 있었는가"
(인스턴스 사실)를 답한다.

에이전트는 두 소스를 교차시켜 가설을 검증한다.

    사용자 (웨이퍼맵 + 질문)
      → Planner/Router
      → VLM 판독 (결함 패턴 서술)
      → Hypothesis 에이전트
            ↺ 지식그래프/문헌 RAG ......... "Edge-Ring → 식각 균일성 문제 가능성" (일반 지식)
            ↺ 본 MCP 서버 툴 9종 ......... "그 lot들, 실제로 ETCH-03에 몰렸나?" (인스턴스 사실)
      → Critic 에이전트 (시간 정합·반대 근거 검사)
      → 응답 (결함 서술 + 채택 가설 + 문헌 근거 + 인스턴스 근거)

---

## 1. 데이터가 만들어지는 방식

이 서버가 조회하는 데이터는 전부 빌드 타임에 시뮬레이터가 생성한다.
실시간 SECS/GEM(HSMS) 통신은 하지 않는다 — 서버는 사전 생성된 데이터의 조회 인터페이스다.

    [실측 웨이퍼맵]                  [가상 팹 모델]
    WM-811K (811,457 wafer)         fab_model.yaml   : 6개 공정 스텝 × 장비군(다중 인스턴스·챔버),
    MixedWM38 (38,015 wafer)                           파라미터 정상범위, PM 주기
         │                          mapping_table.yaml: 결함 패턴 ↔ 후보 원인(확률, 문헌 인용)
         │                               │
         └────────► python -m simulator.generate ◄────┘
                          │  (시드 고정 — 두 번 빌드해도 byte-identical)
                          ▼
      datasets/fab.db          : 조회용 SQLite (아래 스키마)
      datasets/raw_secs_logs/  : S6F11 trace / S5F1 alarm 원본 로그
      datasets/ground_truth/   : 시나리오별 정답 카드 (평가 전용 — 서버는 절대 읽지 않음)

생성 규모(기본 시드 20260101): 가상 팹 90일치 — 배경 lot 800개 + 시나리오 lot 78개,
텔레메트리 58,320행, 정비 94건, 알람 ~130건, 시나리오 12개(그중 매칭불가 2개).

시나리오에는 원인 장비의 파라미터 drift·정비 이벤트 같은 지지 신호뿐 아니라,
정상 lot이 다수 통과한 장비·불량 이후의 PM 같은 함정 신호, 무작위 알람 같은
교란 신호가 함께 주입된다. 결함 패턴만 보고 원인을 역산할 수 없도록
같은 패턴에 여러 후보 원인이 확률적으로 배정된다(순환성 회피).

## 2. 웨이퍼맵과 공정 데이터의 결합 (join key)

| 원천 | 결합 키 | 방식 |
|---|---|---|
| WM-811K | `(lotName, waferIndex)` → `(lot_id, wafer_id)` | 실측 lot 이름을 그대로 가상 팹의 lot 공정 이력에 배정 |
| MixedWM38 | lot 정보 없음 → 가상 lot `SVLOT-xxx` 생성 | 복합 결함(one-hot 멀티라벨) wafer를 가상 lot에 묶어 배정 |

시나리오 lot은 정답 원인 장비·챔버를 t0 시점 전후로 강제 통과하도록 스케줄되고,
배경 lot 800개는 장비들에 무작위 분산된다 — 그래서 불량 lot들의 공통 장비 분석
(commonality)이 의미 있는 신호가 된다.

## 3. fab.db 스키마 (조회 대상)

| 테이블 | 컬럼 | 내용 |
|---|---|---|
| `wafer` | source, lot_id, wafer_id, die_map(BLOB), die_size, is_normal | 웨이퍼맵 (die_map은 np.save 바이트) |
| `lot_history` | lot_id, step, equipment_id, chamber, recipe_id, ts_in, ts_out | lot의 스텝별 장비 통과 이력 |
| `telemetry` | equipment_id, ts, param, value | 장비 파라미터 시계열 (S6F11 유래, 2시간 간격) |
| `alarm` | equipment_id, lot_id, ts, alarm_id, text | 알람 이력 (S5F1 유래) |
| `maintenance` | equipment_id, ts, type, parts | PM(정기)/BM(돌발) 정비 이력 |
| `metric_series` | metric, scope, ts, value | 장비별 일간 수율 등 집계 지표 |
| `event_log` | scope, ts, kind, detail | 기타 이벤트 |

직접 조회도 가능하다(읽기 전용 권장):

    sqlite3 datasets/fab.db "SELECT step, equipment_id, chamber FROM lot_history WHERE lot_id='lot33091'"

단, 에이전트는 SQL이 아니라 아래 MCP 툴로 접근한다 — 툴이 다운샘플링·커버리지 명시 등
컨텍스트 안전장치를 제공하기 때문이다. 서버 코드는 fab.db를 `mode=ro`(읽기 전용)로만 연다.

## 4. MCP 툴 9종

모든 툴의 응답은 공통 스키마를 따른다:

    {
      "data": { ... },                        // 사실만. 원인 해석·판단 문구 없음
      "meta": {
        "source": "synthetic (SECS/GEM simulator v1, dataset seed 20260101)",
        "coverage": { "time_range_queried": ..., "missing": [...] },   // 없는 데이터는 없다고 명시
        "scope_note": "전공정~wafer test 단계 데이터. 패키징 이후 이력 없음."
      }
    }

| 툴 | 인자 | 반환 (data) | RCA에서의 역할 |
|---|---|---|---|
| `get_wafer_map` | lot_id, wafer_id | PNG(base64) + 해상도·die_size. 라벨은 반환하지 않음 | VLM이 결함 패턴을 직접 판독 (정답 누출 차단) |
| `get_lot_history` | lot_id | 스텝별 (장비, 챔버, recipe, 입/출 시각) | 용의선상 장비 목록 확보 |
| `run_commonality_analysis` | lot_ids, step? | 장비/챔버별 (통과 lot 수, 비율) 집계 | 불량 lot들의 공통 장비 좁히기 — 첫 번째 필터 |
| `get_normal_lot_ratio` | equipment_id?, time_range | 해당 장비 통과 lot의 정상/불량 수 | 반대 근거: 정상 lot도 잔뜩 지나갔다면 그 장비 가설 기각 |
| `query_telemetry` | equipment_id, time_range, params?, max_points=500 | 파라미터 시계열(다운샘플) + 정상범위 | 원인 시점(t0)의 drift/이상 확인 |
| `get_alarm_history` | equipment_id?, lot_id?, time_range | 알람 목록 | 시점 일치하는 이벤트 확인 |
| `get_maintenance_history` | equipment_id, time_range | PM/BM 이력 | 정비 직후 문제 발생 패턴 확인 |
| `detect_change_points` | metric, scope, time_range | 변화점 시각 목록 (ruptures) | 수율 급변 시점 탐지 |
| `get_lot_timeline` | lot_id | lot 관련 전체 이벤트 시간순 정렬 | 시간 정합 검사: 원인이 불량보다 앞서는가 |

설계 규칙: ① 툴은 사실만 반환, 해석은 에이전트 몫 ② 없는 구간은 보간하지 않고
`coverage.missing`에 명시 ③ 시계열은 최대 포인트 제한으로 컨텍스트 폭주 방지
④ 웨이퍼 라벨(failureType 등)은 어떤 툴도 반환하지 않음.

## 5. 멀티 에이전트 연결

stdio 방식 MCP 서버라 클라이언트가 필요할 때 자동 기동한다. 서버를 미리 띄워둘 필요 없음.

**Claude Code:**

    claude mcp add secsgem \
      -e PYTHONPATH=$(pwd) -e FAB_DB=$(pwd)/datasets/fab.db \
      -- python -m server.main

**LangGraph (langchain-mcp-adapters):**

    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient({
        "secsgem": {
            "transport": "stdio",
            "command": "python", "args": ["-m", "server.main"],
            "env": {"PYTHONPATH": "/path/to/secsgem-mcp",
                    "FAB_DB": "/path/to/secsgem-mcp/datasets/fab.db"},
        }
    })
    tools = await client.get_tools()      # → LangGraph 에이전트에 바인딩

**권장 가설 검증 흐름** (Hypothesis 에이전트의 툴 매핑):

    1. KG/문헌      : 결함 패턴의 후보 원인 공정 확보          (이 서버 밖)
    2. commonality  : run_commonality_analysis(불량 lot들)     → 공통 장비 후보
    3. 시점 일치    : query_telemetry / get_alarm_history /
                      get_maintenance_history(후보 장비, t0 전후)
    4. 반대 근거    : get_normal_lot_ratio(후보 장비)          → 약한 가설 기각
    5. 시간 정합    : get_lot_timeline                         → 원인이 불량보다 앞서는지 (Critic)

예: Center 결함 lot 8개 → commonality에서 CLEAN-01과 LITHO-01이 둘 다 8/8 —
여기까지는 구분 불가(함정 포함). query_telemetry로 CLEAN-01 flow_rate의 t0 이후
정상범위 이탈을 확인하고, get_normal_lot_ratio로 LITHO-01은 정상 lot 다수 통과임을
확인해 기각하면 CLEAN-01만 남는다. 이 교차 검증이 이 서버의 존재 이유다.

---

## 설치

    python3.11 -m venv .venv && source .venv/bin/activate
    pip install -e . && pip install pytest pyyaml kaggle

## 데이터 준비 (원천 데이터는 배포에 미포함)

    # WM-811K — MIR Lab 공식 배포본
    wget -P .. http://mirlab.org/dataSet/public/MIR-WM811K.zip
    unzip ../MIR-WM811K.zip -d ..
    cp ../MIR-WM811K/Python/WM811K.pkl datasets/raw/

    # MixedWM38 — Kaggle (kaggle CLI 인증 필요)
    # https://www.kaggle.com/datasets/co1d7era/mixedtype-wafer-defect-datasets
    kaggle datasets download -d co1d7era/mixedtype-wafer-defect-datasets -p ../MixedWM38 --unzip
    cp ../MixedWM38/Wafer_Map_Datasets.npz datasets/raw/

    # 합성 fab 데이터 빌드 (시드 고정 — byte-identical 재현)
    python -m simulator.generate --wm811k datasets/raw/WM811K.pkl \
      --mw38 datasets/raw/Wafer_Map_Datasets.npz --out datasets --seed 20260101

## 테스트

    pytest -q -m "not data"    # 데이터 없이 도는 단위 테스트 (CI와 동일)
    pytest -q                  # 데이터 빌드 후 전체 회귀

## 범위와 한계

- 전공정~wafer test(EDS)로 한정. 패키징 이후 미지원 — 모든 응답의 `scope_note`에 명시됨.
- 데이터는 전부 합성: "인과 구조가 알려진 통제 환경에서의 에이전트 추론 평가"가 목적.
  실팹 수치의 사실적 재현이 아니다. 실 데이터 연동 시에도 동일 툴 시그니처 유지가 목표.
- `datasets/ground_truth/`(정답 카드)는 평가 전용이며, 서버 코드가 읽지 않도록
  회귀 테스트로 강제된다.
