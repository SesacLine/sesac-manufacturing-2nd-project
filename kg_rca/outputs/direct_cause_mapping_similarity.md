# Direct 가설(step=null) cause ↔ mapping_table 유사도 매칭 결과

- **작성일**: 2026-07-11
- **입력 데이터**: `outputs/hypotheses.json` (generated_at 2026-07-10, model gpt-5.4-mini), `mapping_table.yaml`
- **대상**: `path.step == null`인 가설 (= `route: "direct"`, 전부 `tier: "근거없음"`) — 총 **12건** (Center 4, Scratch 3, Edge-Ring 5)

## 1. 목적

step 경유 없이 문헌에서 결함 패턴 → cause로 직접 연결된 가설들은 fab 데이터로 검증할 수 없어 "근거없음" tier로 남는다. 이 가설들의 cause가 `mapping_table.yaml`에 정의된 패턴별 cause와 의미적으로 대응되는지 확인하면, direct 가설을 기존 매핑 테이블 항목으로 흡수(→ telemetry 검증 경로 확보)할 수 있는지 판단할 수 있다.

## 2. 방법

- **임베딩 모델**: OpenAI `text-embedding-3-small`
- **가설 측 텍스트**: `detail.cause_name + ". " + detail.cause_description` (영문 표현 + 한글 설명)
- **매핑 테이블 측 텍스트**: cause 슬러그의 영문 풀이 + yaml 한글 주석 (예: `deposition_center_thickness` → "deposition center thickness anomaly. 증착 중앙부 두께 이상")
- **유사도**: 코사인 유사도, 같은 패턴 내 cause 3개와만 비교
- **판정 기준(경험적)**: **0.45 이상**이면 의미 있는 매칭 후보, 그 미만은 어휘 겹침 수준의 노이즈로 간주

## 3. 결과

### 3.1 Center — mapping causes: `deposition_center_thickness`(DEPO) / `cmp_center_overpolish`(CMP) / `clean_nozzle_clog`(CLEAN)

| rank | cause (가설 슬러그) | 문헌 표현 (cause_name) | description | DEPO 두께이상 | CMP 중앙과연마 | 세정노즐 막힘 | 최고 매칭 | 판정 |
|---|---|---|---|---|---|---|---|---|
| 59 | irregular_rf_operation | Irregular radio frequency (RF) operation | 무선 주파수 동작이 불규칙한 상태 | 0.157 | **0.220** | 0.166 | cmp_center_overpolish (0.22) | ❌ 무매칭 |
| 60 | unusual_liquid_flow | unusual liquid flow | 액체 유동이 비정상적인 상태 | **0.357** | 0.235 | 0.300 | deposition_center_thickness (0.36) | ⚠️ 약함 |
| 61 | nonuniformities_created_in_thin_film_deposition_process | nonuniformities created in the thin film deposition process | 박막 증착 공정에서 생성된 비균일성 | **0.453** | 0.272 | 0.343 | deposition_center_thickness (0.45) | ✅ 매칭 |
| 62 | uneven_temperature_distribution_during_rapid_thermal_annealing_process | uneven temperature distribution during the rapid thermal annealing process | RTA 공정 중 온도 분포 불균일 | **0.289** | 0.191 | 0.231 | deposition_center_thickness (0.29) | ❌ 무매칭 |

### 3.2 Scratch — mapping causes: `cmp_pad_wear`(CMP) / `cmp_slurry_particle`(CMP) / `clean_brush_contact`(CLEAN)

| rank | cause (가설 슬러그) | 문헌 표현 (cause_name) | description | 패드 마모 | 슬러리 대입자 | 브러시 접촉 | 최고 매칭 | 판정 |
|---|---|---|---|---|---|---|---|---|
| 8 | scratches_on_wafer_surface_by_transfer_robots | scratches on the wafer surface by transfer robots | 이송 로봇에 의한 웨이퍼 표면 긁힘 | 0.319 | 0.355 | **0.363** | clean_brush_contact (0.36) | ⚠️ 약함 (슬러리 0.35와 박빙) |
| 9 | surface_damage_by_humans | surface damage by humans | 사람에 의한 웨이퍼 표면 손상 | **0.301** | 0.170 | 0.257 | cmp_pad_wear (0.30) | ❌ 무매칭 |
| 10 | scratches_caused_by_polishing_during_cmp | scratches caused by polishing during chemical–mechanical polishing (CMP) | CMP 연마 중 발생하는 긁힘 | **0.486** | 0.396 | 0.380 | cmp_pad_wear (0.49) | ✅ 매칭 (슬러리 0.40도 유효) |

### 3.3 Edge-Ring — mapping causes: `etch_nonuniformity`(ETCH) / `cmp_edge_overpolish`(CMP) / `clean_residue`(CLEAN)

| rank | cause (가설 슬러그) | 문헌 표현 (cause_name) | description | 식각 불균일 | CMP 에지과연마 | 세정 잔류 | 최고 매칭 | 판정 |
|---|---|---|---|---|---|---|---|---|
| 49 | anomalous_temperature_regulation_during_rapid_thermal_process_rtp | anomalous temperature regulation during rapid thermal process (RTP) | RTP 중 온도 조절 비정상 | **0.343** | 0.339 | 0.209 | etch_nonuniformity (0.34) | ❌ 무매칭 |
| 50 | insufficient_heating_due_to_wafer_thickness_variations | insufficient heating due to wafer thickness variations | 웨이퍼 두께 변동으로 인한 가열 부족 | **0.445** | 0.274 | 0.188 | etch_nonuniformity (0.44) | ⚠️ 착시 의심 |
| 51 | uneven_temperature_distribution_during_rapid_thermal_annealing_process | uneven temperature distribution during the rapid thermal annealing process | RTA 공정 중 온도 분포 불균일 | **0.513** | 0.244 | 0.185 | etch_nonuniformity (0.51) | ⚠️ 착시 (공정 불일치) |
| 52 | nonuniform_thin_film_deposition_process | nonuniformities created in the thin film deposition process | 박막 증착 공정의 비균일성 | **0.585** | 0.327 | 0.350 | etch_nonuniformity (0.59) | ⚠️ 착시 (DEPO≠ETCH) |
| 53 | cold_process | cold process | 공정 온도가 낮은 상태 | 0.314 | **0.352** | 0.259 | cmp_edge_overpolish (0.35) | ❌ 무매칭 |

## 4. 해석

1. **신뢰할 만한 매칭은 2건**:
   - Center #61 → `deposition_center_thickness` (0.45): 박막 증착 비균일 ↔ 증착 중앙부 두께 이상. 의미·공정(DEPO) 모두 일치.
   - Scratch #10 → `cmp_pad_wear` (0.49) / `cmp_slurry_particle` (0.40): CMP 연마 긁힘. 공정(CMP) 일치, 두 cause 모두 상위 개념의 세분화로 볼 수 있음.
2. **Edge-Ring #51·#52의 높은 점수(0.51, 0.59)는 착시**: "nonuniformity/불균일" 어휘 겹침으로 `etch_nonuniformity`에 붙었을 뿐, 실제 언급 공정은 RTA·DEPO라 ETCH와 의미가 다르다. Edge-Ring 매핑 테이블에 DEPO/열처리 계열 cause가 없어서 생기는 강제 매칭이다.
3. **매핑 테이블에 대응 항목 자체가 없는 cause 계열**:
   - RF 이상 (Center #59)
   - RTP/RTA 온도 계열 (Center #62, Edge-Ring #49·#50·#51, #53 cold process)
   - 핸들링/사람에 의한 기계적 손상 (Scratch #8·#9)
   이들은 최고 점수도 0.2~0.44에 그쳐 "매칭 없음"으로 처리하는 것이 타당하다.

## 5. 시사점

- direct 가설 12건 중 **매핑 테이블로 흡수 가능한 것은 2건**(Center #61, Scratch #10)뿐이며, 나머지는 매핑 테이블의 커버리지 밖이다.
- 매핑 테이블 확장을 검토한다면 우선순위는: (a) **RTP/RTA 온도 불균일** 계열 (Edge-Ring·Center에서 반복 등장, 4건), (b) **핸들링/로봇 긁힘** (Scratch 2건).
- 임베딩 유사도만으로 자동 매칭할 경우 어휘 겹침 착시(Edge-Ring #52 유형)가 최고점을 차지할 수 있으므로, **공정(process) 일치 여부를 함께 검사**하는 필터가 필요하다.

## 6. 재현 방법

중간 산출물·스크립트 (`outputs/similarity_match/`):

- `direct_hyps.json` — hypotheses.json에서 step=null 가설 12건 추출본
- `sim_match.py` — 임베딩·코사인 유사도 계산 스크립트 (`.env`의 OPENAI_API_KEY 사용)
- `sim_results.json` — 패턴별 전체 유사도 점수

핵심 로직: 가설별로 같은 패턴의 mapping cause 3개와만 비교, `text-embedding-3-small` 임베딩의 코사인 유사도를 내림차순 정렬 후 최고값을 best로 기록.
