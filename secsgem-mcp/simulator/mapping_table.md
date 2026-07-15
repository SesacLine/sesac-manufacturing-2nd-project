<!-- 자동 생성: python -m simulator.render_mapping_md — 직접 편집 금지 -->
# 결함↔후보 원인 매핑 테이블

이 테이블은 (a) 시나리오 생성 스펙, (b) KG 구축 시드, (c) 평가 정답지의 공통 원천임
원본은 `mapping_table.yaml`이며 본 문서는 리뷰용 렌더링.
리뷰 코멘트(현직자 검토)는 `mapping_table_review.md`에 남김.

## Edge-Ring

| cause | process | equipment_group | prob | telemetry (param / drift) | shape | maint_event | part | citation |
|---|---|---|---|---|---|---|---|---|
| etch_nonuniformity | ETCH | ETCH | 0.6 | rf_power / step_up | - | true | RF 매칭 유닛 | Wang et al., IEEE TSM 2020 |
| cmp_edge_overpolish | CMP | CMP | 0.25 | down_force / linear_up | - | true | 리테이너 링 | NO_CITATION |
| clean_residue | CLEAN | CLEAN | 0.15 | flow_rate / none | - | true | 약액 공급 필터 | NO_CITATION |

## Center

| cause | process | equipment_group | prob | telemetry (param / drift) | shape | maint_event | part | citation |
|---|---|---|---|---|---|---|---|---|
| deposition_center_thickness | DEPO | DEPO | 0.55 | chamber_pressure / linear_up | - | false | - | Wu et al., IEEE TSM 2015 |
| cmp_center_overpolish | CMP | CMP | 0.25 | slurry_flow / linear_up | - | true | 슬러리 공급 펌프 | NO_CITATION |
| clean_nozzle_clog | CLEAN | CLEAN | 0.2 | flow_rate / linear_down | - | true | 분사 노즐 | NO_CITATION |

## Scratch

| cause | process | equipment_group | prob | telemetry (param / drift) | shape | maint_event | part | citation |
|---|---|---|---|---|---|---|---|---|
| cmp_pad_wear | CMP | CMP | 0.45 | pad_usage_hours / linear_up | consumable_wear | true | 연마 패드 | Wu et al., IEEE TSM 2015 |
| cmp_slurry_particle | CMP | CMP | 0.35 | slurry_flow / step_up | - | true | 슬러리 필터 | NO_CITATION |
| clean_brush_contact | CLEAN | CLEAN | 0.2 | none / none | - | true | 세정 브러시 | NO_CITATION |
