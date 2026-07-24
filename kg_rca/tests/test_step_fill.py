"""P2 — 6_ask_graphrag.apply_mapping_fill의 step 보충(a)/교정(b) 회귀 테스트.

정본: docs 밖 living 문서 eval_scenario_kg_proposal.md §P2. path.step ↔ mapping.process
불일치를 KG 산출물 단계에서 자기완결적으로 메운다(backend D14 폴백을 무동작으로 만든다).

Neo4j 불필요 — 모듈 import는 Neo4jGraph를 인스턴스화하지 않고(main()에서만), 검증 대상은
순수함수 apply_mapping_fill이다. 숫자 파일명(6_ask_graphrag.py)이라 importlib으로 로드한다.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_KG_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "ask_graphrag_p2", _KG_DIR / "6_ask_graphrag.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _none_row(mod, step, cause, cause_name):
    """[근거없음] 행 1건 — apply_mapping_fill이 채우는 대상."""
    return {
        "step": step, "failure_mode": "fm", "cause": cause, "cause_name": cause_name,
        "evidence": "근거없음", "evidence_name": "문헌 서술", "evidence_label": "None",
        "fab_table": "-", "direction": None, "tier": mod.TIER_NONE, "route": "direct",
    }


# SC-CENTER-01 정답 cause — clean_nozzle_clog(process=CLEAN)에 키워드 앵커로 강하게 매칭된다.
_ANSWER_CAUSE = "particle_accumulations_near_the_chuck_center"
_ANSWER_NAME = "particle accumulations near the chuck center"


def test_a_step_none_filled_from_mapping_process(mod):
    """(a) step=None → mapping.process(CLEAN)로 보충 + [자동] 승격(flow_rate ∈ fab 어휘)."""
    row = _none_row(mod, None, _ANSWER_CAUSE, _ANSWER_NAME)
    mod.apply_mapping_fill("Center", [row])
    assert row["step"] == "CLEAN"
    assert row["tier"] == mod.TIER_AUTO          # flow_rate가 fab 어휘라 자동 승격
    assert row["mapping"]["process"] == "CLEAN"


def test_b_wrong_step_corrected_on_strong_match(mod):
    """(b) 오연결 step(DEPO)이 강한 매칭(score=1.0)에서 CLEAN으로 교정된다."""
    row = _none_row(mod, "DEPO", _ANSWER_CAUSE, _ANSWER_NAME)
    mod.apply_mapping_fill("Center", [row])
    assert row["step"] == "CLEAN", "강한 매칭이면 오연결 step을 매핑 공정으로 교정해야"


def test_b_weak_match_preserves_extracted_step(mod):
    """(b) 가드 — 매핑에 안 걸리는 무관 cause는 non-None step(추출 정본)을 건드리지 않는다."""
    row = _none_row(mod, "LITHO", "totally_unrelated_cause_xyz", "totally unrelated cause xyz")
    mod.apply_mapping_fill("Center", [row])
    assert row["step"] == "LITHO"
    assert row.get("mapping") is None            # 임계 미달 → 매핑 자체가 안 붙음


def test_override_threshold_is_stricter_than_match_threshold(mod):
    """설계 불변식 — non-None step 교정 임계가 매칭 임계보다 엄격해야(느슨한 덮어쓰기 방지)."""
    assert mod.MAPPING_STEP_OVERRIDE_THRESHOLD > mod.MAPPING_MATCH_THRESHOLD


# ── P1: 유사도매칭 대칭 (eval_scenario_kg_proposal.md §P1) ─────────────────────────────────
def _auto_row(mod, step, cause, cause_name):
    """이미 [자동] tier로 검증된 행(Parameter evidence 보유) — apply_mapping_fill이 예전엔 건너뛰던 것."""
    return {
        "step": step, "failure_mode": "fm", "cause": cause, "cause_name": cause_name,
        "evidence": "down_force", "evidence_name": "down_force", "evidence_label": "Parameter",
        "fab_table": "telemetry", "direction": "high", "tier": mod.TIER_AUTO, "route": "step",
    }


def test_p1_matched_cause_labeled_on_auto_tier_row(mod):
    """P1 핵심 — 자동 tier인 excessive_down_force가 cmp_edge_overpolish로 라벨링된다.
    (예전엔 tier!=NONE이라 mapping 자체를 안 붙여 eval에서 통째로 빠졌다.)"""
    row = _auto_row(mod, "CMP", "excessive_down_force", "excessive down force")
    mod.apply_mapping_fill("Edge-Ring", [row])
    assert row["mapping"]["matched_cause"] == "cmp_edge_overpolish"


def test_p1_auto_tier_row_evidence_untouched(mod):
    """P1 가드 — 라벨만 얹고 이미 검증된 자동 행의 tier/step/evidence/direction은 안 건드린다."""
    row = _auto_row(mod, "CMP", "excessive_down_force", "excessive down force")
    mod.apply_mapping_fill("Edge-Ring", [row])
    assert row["tier"] == mod.TIER_AUTO
    assert row["step"] == "CMP"
    assert row["evidence"] == "down_force"
    assert row["direction"] == "high"


def test_p1_center_edge_cmp_symmetry(mod):
    """P1 취지 — Center CMP가 이어지면 Edge CMP도 이어져야(대칭)."""
    center = _none_row(mod, None, "center_polishing_too_fast", "center polished too fast")
    edge = _auto_row(mod, "CMP", "excessive_down_force", "excessive down force")
    mod.apply_mapping_fill("Center", [center])
    mod.apply_mapping_fill("Edge-Ring", [edge])
    assert center["mapping"]["matched_cause"] == "cmp_center_overpolish"
    assert edge["mapping"]["matched_cause"] == "cmp_edge_overpolish"
