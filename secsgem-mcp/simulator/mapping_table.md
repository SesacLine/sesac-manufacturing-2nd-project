<!-- 자동 생성: python -m simulator.render_mapping_md — 직접 편집 금지 -->
# 결함↔후보 원인 매핑 테이블

이 테이블은 (a) 시나리오 생성 스펙, (b) KG 구축 시드, (c) 평가 정답지의 공통 원천.
단일 진실원본은 `mapping_table.yaml`이며 본 문서는 리뷰용 렌더링.
리뷰 코멘트(현직자 검토)는 이 파일이 아니라 `mapping_table_review.md`에 남김.

## Edge-Ring

| cause | process | equipment_group | prob | telemetry (param / drift) | citation |
|---|---|---|---|---|---|
| etch_nonuniformity | ETCH | ETCH | 0.6 | rf_power / step_up | Wang et al., IEEE TSM 2020; 인터뷰 1-3 |
| cmp_edge_overpolish | CMP | CMP | 0.25 | down_force / linear_up | TODO(M1 리뷰 게이트): 문헌 확정 필요 |
| clean_residue | CLEAN | CLEAN | 0.15 | flow_rate / none | TODO(M1 리뷰 게이트): 문헌 확정 필요 |

## Center

| cause | process | equipment_group | prob | telemetry (param / drift) | citation |
|---|---|---|---|---|---|
| deposition_center_thickness | DEPO | DEPO | 0.6 | chamber_pressure / step_up | Wu et al., IEEE TSM 2015 (WM-811K 원 논문); TODO: 기전 문헌 보강 |
| cmp_center_overpolish | CMP | CMP | 0.25 | slurry_flow / linear_up | TODO(M1 리뷰 게이트): 문헌 확정 필요 |
| clean_nozzle_clog | CLEAN | CLEAN | 0.15 | flow_rate / linear_down | TODO(M1 리뷰 게이트): 문헌 확정 필요 |

## Scratch

| cause | process | equipment_group | prob | telemetry (param / drift) | citation |
|---|---|---|---|---|---|
| handling_mechanical | CMP | CMP | 0.65 | none / none | Wu et al., IEEE TSM 2015; 인터뷰 1-3 |
| cmp_slurry_particle | CMP | CMP | 0.35 | slurry_flow / step_up | TODO(M1 리뷰 게이트): 문헌 확정 필요 |
