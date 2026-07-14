### 테이블 필드 (generate.py의 CREATE TABLE 기준)

> ⚠ 동기화 필요 (데이터 모델 설계_v2.0 §6 F-2): 이 문서는 4테이블만 기록하나,
> 설계 문서 v1.0은 `metric_series`(장비 단위 스코프)·`wafer`(die_map) 테이블을 추가로 언급한다.
> (07-13 X1E 정리 반영: `pad_usage_hours`는 fab에 실재 → CMP 행에 추가됨.
>  `shower_flow`/`pressure`는 `chamber_pressure`로 처리(별칭). `motor_torque`·`slurry_particle`은
>  제거 결정 — 고려 불가 변수로 잔여, 정합성검토 X1E 기록 참조.)

**`lot_history`** — lot의 장비 통과 이력 (모든 추적의 시작점)

| 필드 | 타입 | 의미 |
|---|---|---|
| `lot_id` | TEXT | lot 식별자 (join key) |
| `step` | TEXT | 공정 스텝 (LITHO/ETCH/DEPO/CMP/CLEAN/EDS) |
| `equipment_id` | TEXT | 장비 인스턴스 (예: ETCH-03) |
| `chamber` | TEXT | 챔버 (예: ETCH-03-CH1) |
| `recipe_id` | TEXT | 레시피 (예: RCP-ETCH-2) |
| `ts_in` | TEXT | 처리 시작 시각 |
| `ts_out` | TEXT | 처리 종료 시각 |

**`telemetry`** — 장비 파라미터 시계열 (S6F11 유래). 정상범위는 이 테이블에 없고 `fab_model.yaml`에서 조회해 합침.

| 필드 | 타입 | 의미 |
|---|---|---|
| `equipment_id` | TEXT | 장비 |
| `ts` | TEXT | 측정 시각 (2시간 간격) |
| `param` | TEXT | 파라미터명 (예: rf_power) |
| `value` | REAL | 측정값 |

**`alarm`** — 알람 이력 (S5F1 유래)

| 필드 | 타입 | 의미 |
|---|---|---|
| `equipment_id` | TEXT | 장비 |
| `lot_id` | TEXT | 관련 lot (교란 알람은 `NULL`) |
| `ts` | TEXT | 발생 시각 |
| `alarm_id` | INT | 알람 코드 (교란 1000번대, 시나리오 지지 3000번대) |
| `text` | TEXT | 알람 문구 |

**`maintenance`** — 정비 이력

| 필드 | 타입 | 의미 |
|---|---|---|
| `equipment_id` | TEXT | 장비 |
| `ts` | TEXT | 정비 시각 |
| `type` | TEXT | `PM`(정기) 또는 `BM`(돌발) |
| `parts` | TEXT | 교체 부품/내용 |

### 장비군별 파라미터 이름 (Quick Reference)

파라미터 집합이 갈리는 단위는 **개별 장비가 아니라 장비군(공정 스텝)** 이다.
즉 ETCH-01/02/03 은 파라미터가 동일하고, ETCH vs DEPO 는 다르다.

| 장비군 | 파라미터 이름 | 개수 |
|---|---|---|
| **LITHO** | `exposure_dose` · `focus_offset` · `stage_temp` · `alignment_offset` | 4 |
| **ETCH** | `rf_power` · `chamber_pressure` · `he_flow` · `temperature` · `etch_rate` | 5 |
| **DEPO** | `chamber_pressure` · `rf_power` · `gas_flow` · `susceptor_temp` · `deposition_rate` | 5 |
| **CMP** | `down_force` · `slurry_flow` · `pad_usage_hours` | 3 |
| **CLEAN** | `flow_rate` · `megasonic_power` · `chemical_temp` · `rinse_time` | 4 |
| **EDS** | `chuck_temp` · `contact_resistance` | 2 |
