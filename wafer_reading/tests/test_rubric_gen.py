"""루브릭 평가 모듈 단위 테스트

— 데이터/GPU/API 키 없이 돎(fake backend 주입)
- pytest -q wafer_reading/tests  (CI의 -m "not data"에서도 그대로 통과해야 함)
- 검수 발견 3건(설계서 v2.0 §6)의 해소를 회귀로 고정한다:
  ① must-hit ∩ must-avoid 충돌 제거(merge)  ② 구 단위 매칭(score)  ③ 인스턴스 특이어 배제(merge)
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from wafer_reading.rubric_gen import models as rg_models
from wafer_reading.rubric_gen.generate import (
    RubricGenError,
    RubricGenerator,
    _agrees,
    build_unlabeled_messages,
    describe_unlabeled,
    parse_rubric,
)
from wafer_reading.rubric_gen.models import (
    ModelSeparationError,
    assert_distinct,
    base_model,
)
from wafer_reading.rubric_gen.judge import (
    JudgeCallError,
    LLMJudge,
    build_judge_prompt,
    parse_judgement,
)
from wafer_reading.rubric_gen.merge import merge_rubrics
from wafer_reading.rubric_gen.sampling import sample_groups, split_pool
from wafer_reading.rubric_gen.schema import (
    RubricSchemaError,
    normalize_phrase,
    phrases_of,
    split_phrases,
    validate_instance_rubric,
)
from wafer_reading.rubric_gen.score import bleu, rouge_l, score_dimension, score_output
from wafer_reading.vlm.adapter import VLMReader


VALID = {
    "pattern_candidate": "Edge-Ring",
    "location_text": "failing dies around the wafer edge.",
    "morphology_text": "a continuous high-density band.",
    "total_description": "a continuous ring at the periphery.",
}


def instance(
    zone="edge", distribution="circumferential band", clock="6 o clock",
    coords="center 0 0", spatial_avoid=("uniform distribution",),
    pattern_type="continuous band", density="high density",
    geometric="ring", texture="sharp continuous",
    morph_avoid=("grid like",), defect="Edge-Ring",
) -> dict:
    return {
        "defect_types": defect,
        "spatial_rubric": {
            "zone": zone,
            "distribution": distribution,
            "clock_position": clock,
            "coordinates_hint": coords,
            "spatial_avoid": list(spatial_avoid),
        },
        "morphology_rubric": {
            "pattern_type": pattern_type,
            "density": density,
            "geometric_structure": geometric,
            "texture_description": texture,
            "morphology_avoid": list(morph_avoid),
        },
        "summary": "edge ring defect",
    }


def _ring_map(size: int = 30) -> np.ndarray:
    """가장자리 링 형태의 합성 웨이퍼맵 (0=no die, 1=pass, 2=fail)."""
    y, x = np.mgrid[:size, :size]
    r = np.hypot((y - size / 2 + 0.5) / (size / 2), (x - size / 2 + 0.5) / (size / 2))
    arr = np.zeros((size, size), dtype=np.uint8)
    arr[r < 1.0] = 1
    arr[(r >= 0.8) & (r < 1.0)] = 2
    return arr


class FakeBackend:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.last_messages = None

    def generate(self, messages):
        self.calls += 1
        self.last_messages = messages
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


# schema

def test_split_phrases_accepts_string_and_list():
    assert split_phrases("Center, Edge; Mid-radius") == ["center", "edge", "mid radius"]
    assert split_phrases(["High-density", "high density"]) == ["high density"]  # 정규화 후 중복 제거
    assert split_phrases(None) == []


def test_split_phrases_strips_llm_meta_and_prose():
    """실측(gpt-5.5): "Must-hit keywords: a, b. A correct answer should…" 형식을 정리한다."""
    value = ("Must-hit keywords: central region, middle, center of wafer. "
             "A correct answer should state that defects are concentrated in the central zone.")
    assert split_phrases(value) == ["central region", "middle", "center of wafer"]


def test_split_phrases_drops_fillers_negations_and_sentences():
    assert split_phrases("Keywords: none specified, no clock-position dependence") == []
    sentence = "the defect field is compact and radially symmetric across the entire wafer area"
    assert split_phrases(sentence) == []  # 절 조각·문장은 키워드가 아니다
    assert split_phrases("dense central cluster") == ["dense central cluster"]  # 명사구는 유지


def test_normalize_phrase_collapses_punctuation():
    assert normalize_phrase("  Edge-Ring  pattern! ") == "edge ring pattern"


def test_validate_rejects_broken_schema():
    with pytest.raises(RubricSchemaError):
        validate_instance_rubric({"defect_types": "Center"})  # 블록 없음
    broken = instance()
    broken["morphology_rubric"]["morphology_avoid"] = "grid like"  # 리스트여야 함
    with pytest.raises(RubricSchemaError):
        validate_instance_rubric(broken)
    missing_key = instance()
    del missing_key["spatial_rubric"]["zone"]
    with pytest.raises(RubricSchemaError):
        validate_instance_rubric(missing_key)


# merge (검수 ①③)

def test_merge_keeps_only_repeated_phrases():
    """③ 표본 1건에만 나온 인스턴스 특이어는 고정 루브릭에 들어가지 않는다."""
    instances = [instance() for _ in range(3)]
    instances[0]["spatial_rubric"]["zone"] = "lower right quadrant"  # 1건뿐
    fixed = merge_rubrics(instances, "Edge-Ring", min_support=2)

    hits = phrases_of(fixed, "spatial", "must_hit")
    assert "edge" in hits and "circumferential band" in hits
    assert "lower right quadrant" not in hits
    assert any(d["phrase"] == "lower right quadrant" for d in fixed["dropped"]["low_support"])


def test_merge_excludes_instance_specific_axes():
    """③ clock_position/coordinates_hint만 출처인 구는 support를 넘겨도 must-hit에서 뺀다."""
    fixed = merge_rubrics([instance() for _ in range(3)], "Edge-Ring", min_support=2)
    hits = phrases_of(fixed, "spatial", "must_hit")
    assert "6 o clock" not in hits and "center 0 0" not in hits
    assert {d["phrase"] for d in fixed["dropped"]["instance_specific"]} == {"6 o clock", "center 0 0"}


def test_merge_resolves_hit_avoid_conflict():
    """① 같은 구가 must-hit과 must-avoid에 동시에 있으면 avoid에서 제거하고 기록한다."""
    instances = [instance(morph_avoid=("continuous band", "grid like")) for _ in range(3)]
    fixed = merge_rubrics(instances, "Scratch", min_support=2)

    assert "continuous band" in phrases_of(fixed, "morphology", "must_hit")
    assert "continuous band" not in phrases_of(fixed, "morphology", "must_avoid")
    assert "grid like" in phrases_of(fixed, "morphology", "must_avoid")
    assert [d["phrase"] for d in fixed["dropped"]["conflict_resolved"]] == ["continuous band"]


def test_merge_default_support_is_majority():
    fixed = merge_rubrics([instance() for _ in range(5)], "Edge-Ring")
    assert fixed["min_support"] == 3 and fixed["n_samples"] == 5


def test_merge_rejects_empty_input():
    with pytest.raises(ValueError):
        merge_rubrics([], "Center")


# score (검수 ②)

def test_hit_masking_prevents_substring_false_positive():
    """② avoid "radial"이 정상 서술 "radial dependency"를 환각으로 오탐하지 않는다."""
    result = score_dimension(
        "The defect shows a clear radial dependency toward the center.",
        must_hit=["radial dependency", "center"],
        must_avoid=["radial", "uniform distribution"],
    )
    assert result["hits"] == ["radial dependency", "center"]
    assert result["violations"] == []
    assert result["hit_coverage"] == 1.0 and result["score"] == 1.0


def test_avoid_still_detected_outside_hit_span():
    result = score_dimension(
        "Defects are radial and uniformly distributed with a radial dependency.",
        must_hit=["radial dependency"],
        must_avoid=["radial"],
    )
    assert result["violations"] == ["radial"]  # hit 구간 밖의 "radial"은 잡힌다
    # H=1.0(C=1.0) · A=1−0.25·1=0.75 → D=0.6·1.0+0.4·0.75=0.9
    assert result["avoid_score"] == 0.75 and result["score"] == 0.9


def test_word_boundary_and_hyphen_equivalence():
    result = score_dimension(
        "a high-density band at the edge", must_hit=["high density"], must_avoid=["bandwidth"]
    )
    assert result["hits"] == ["high density"] and result["violations"] == []


def test_soft_recall_caps_at_two_thirds_coverage():
    """H = min(1, 1.5·C) — 2/3만 담아도 만점(자연어 변동성 흡수, WaferSAGE 규약)."""
    result = score_dimension(
        "ring at the edge", must_hit=["ring", "edge", "clean interior"], must_avoid=["scratch"]
    )
    assert result["hit_coverage"] == round(2 / 3, 4)
    assert result["missed"] == ["clean interior"]
    assert result["hit_score"] == 1.0 and result["score"] == 1.0


def test_partial_coverage_below_soft_cap():
    """C=0.5 → H=0.75 → D=0.6·0.75+0.4·1.0=0.85"""
    result = score_dimension("ring only", must_hit=["ring", "clean interior"], must_avoid=[])
    assert result["hit_coverage"] == 0.5 and result["hit_score"] == 0.75
    assert result["score"] == 0.85


def test_avoid_penalty_is_per_violation_count():
    """A = max(0, 1 − 0.25·n_f) — 위반 '개수'당 감점(루브릭 avoid 목록 크기와 무관)."""
    two = score_dimension(
        "a linear scratch and a checkerboard texture",
        must_hit=["scratch"], must_avoid=["linear", "checkerboard", "ring", "blob"],
    )
    assert two["n_violations"] == 2 and two["avoid_score"] == 0.5
    assert two["score"] == round(0.6 * 1.0 + 0.4 * 0.5, 4)

    many = score_dimension(
        "linear checkerboard ring blob everywhere",
        must_hit=["scratch"], must_avoid=["linear", "checkerboard", "ring", "blob"],
    )
    assert many["avoid_score"] == 0.0  # 4건 × 0.25 → 0으로 클립
    assert many["score"] == 0.0  # H=0(미매칭) + A=0


def test_overall_uses_paper_dimension_weights():
    """S = Σ wᵢDᵢ — spatial 0.4 / morphology 0.35 (root_cause 제외 재정규화)."""
    fixed = merge_rubrics([instance() for _ in range(3)], "Edge-Ring", min_support=2)
    out = {  # spatial 만점 / morphology 전무 → 가중치가 그대로 드러난다
        "pattern_candidate": "Edge-Ring",
        "location_text": "failing dies along the edge in a circumferential band",
        "morphology_text": "nothing relevant here",
    }
    result = score_output(out, fixed)
    assert result["dimensions"]["spatial"]["score"] == 1.0
    assert result["dimensions"]["morphology"]["score"] == 0.4  # H=0, A=1.0 → 0.4
    assert result["overall"] == round((0.4 * 1.0 + 0.35 * 0.4) / 0.75, 4) == 0.72


def test_score_output_uses_field_per_dimension():
    fixed = merge_rubrics([instance() for _ in range(3)], "Edge-Ring", min_support=2)
    out = {
        "pattern_candidate": "Edge-Ring",
        "location_text": "failing dies along the edge in a circumferential band",
        "morphology_text": "a continuous band of high density with a sharp continuous ring",
        "total_description": "a continuous ring at the edge",
        "vlm_track": "pty",
        "image_mode": "stacked",
    }
    result = score_output(out, fixed)
    assert result["dimensions"]["spatial"]["hit_coverage"] == 1.0
    assert result["dimensions"]["morphology"]["hit_coverage"] == 1.0
    assert result["hallucinated"] is False
    assert result["overall"] == 1.0
    assert result["vlm_track"] == "pty"


def test_score_output_flags_hallucination():
    fixed = merge_rubrics([instance() for _ in range(3)], "Edge-Ring", min_support=2)
    out = {
        "pattern_candidate": "Edge-Ring",
        "location_text": "defects follow a uniform distribution across the wafer",
        "morphology_text": "a grid like texture",
        "total_description": "uniform grid like defects",
    }
    result = score_output(out, fixed)
    assert result["hallucinated"] is True
    # 두 축 모두 H=0(must-hit 전무) + avoid 위반 1건씩 → D = 0.4·0.75 = 0.3
    assert result["dimensions"]["spatial"]["n_violations"] == 1
    assert result["overall"] == 0.3


def test_negated_avoid_term_is_not_a_violation():
    """실측(07-26 Center 5/5 오탐): 부정문 안의 avoid 어휘는 환각이 아니다."""
    result = score_dimension(
        "It is dense and blob-like rather than linear or ring-shaped, with no strong alignment.",
        must_hit=["blob like"],
        must_avoid=["linear", "ring shaped"],
    )
    assert result["violations"] == []
    assert set(result["negated_violations"]) == {"linear", "ring shaped"}
    assert result["hits"] == ["blob like"] and result["score"] == 1.0


def test_avoid_term_outside_negation_still_counts():
    result = score_dimension(
        "There is no ring structure. A linear scratch crosses the wafer.",
        must_hit=["scratch"],
        must_avoid=["ring", "linear"],
    )
    assert result["violations"] == ["linear"]  # 부정절 밖의 언급은 그대로 위반
    assert result["negated_violations"] == ["ring"]


def test_negated_must_hit_does_not_count_as_hit():
    """부정 스코프는 절 경계까지 — "no A at B"는 B에 대해서도 아무것도 주장하지 않는다."""
    result = score_dimension(
        "The wafer shows no continuous ring at the edge. Defects sit in the center.",
        must_hit=["continuous ring", "edge", "center"],
        must_avoid=[],
    )
    assert result["hits"] == ["center"]  # 다음 문장(부정 밖)의 구만 인정
    assert set(result["negated_hits"]) == {"continuous ring", "edge"}
    assert result["hit_coverage"] == round(1 / 3, 4)


def test_fuzzy_absorbs_inserted_word():
    """실측: must-hit "diffuse halo" ↔ 서술 "diffuse surrounding halo" (삽입어)."""
    result = score_dimension(
        "a bright saturated core and a diffuse surrounding halo",
        must_hit=["diffuse halo"], must_avoid=[],
    )
    assert result["hits"] == ["diffuse halo"] and result["fuzzy_hits"] == ["diffuse halo"]
    assert result["hit_coverage"] == 1.0


def test_fuzzy_absorbs_inflection_and_word_order():
    """굴절형(rings)·어순 변화("uniform in thickness")를 흡수한다."""
    a = score_dimension("continuous rings at the edge", must_hit=["continuous ring"], must_avoid=[])
    b = score_dimension(
        "The ring is fairly uniform in thickness", must_hit=["fairly uniform thickness"], must_avoid=[]
    )
    assert a["hits"] == ["continuous ring"] and b["hits"] == ["fairly uniform thickness"]


def test_fuzzy_can_be_disabled():
    result = score_dimension(
        "a diffuse surrounding halo", must_hit=["diffuse halo"], must_avoid=[], fuzzy_threshold=None
    )
    assert result["hits"] == [] and result["fuzzy_hits"] == []


def test_fuzzy_does_not_bridge_synonyms_or_short_phrases():
    """동의어(rim↔periphery)는 범위 밖이고, 짧은 구는 fuzzy 자체를 금지한다(오탐 방지)."""
    syn = score_dimension(
        "defects along the wafer periphery", must_hit=["rim"], must_avoid=["arc"]
    )
    assert syn["hits"] == [] and syn["violations"] == []


def test_fuzzy_respects_window_locality():
    """구 토큰이 멀리 흩어져 있으면 매칭하지 않는다(문서 전체 산재 매칭 금지)."""
    result = score_dimension(
        "the pattern is dense at the wafer edge, and a separate small cluster sits far away",
        must_hit=["dense cluster"], must_avoid=[],
    )
    assert result["hits"] == []


def test_fuzzy_violations_are_tracked_separately():
    result = score_dimension(
        "a checkerboards texture across the wafer", must_hit=["texture"], must_avoid=["checkerboard"]
    )
    assert result["violations"] == ["checkerboard"]
    assert result["fuzzy_violations"] == ["checkerboard"]  # 감사용 분리 기록


def test_empty_must_hit_is_unscorable_not_zero():
    """must-hit이 없는 축은 0점이 아니라 채점 불가 — avoid 위반 탐지는 계속 유효하다."""
    result = score_dimension("a ring at the edge", must_hit=[], must_avoid=["ring"])
    assert result["applicable"] is False
    assert result["score"] is None and result["hit_coverage"] is None
    assert result["violations"] == ["ring"]


def test_score_output_skips_unscorable_dimension():
    """실측 Scratch 케이스: spatial must-hit 0개 → overall은 morphology만으로 낸다."""
    instances = [instance(zone="", distribution="", clock="", coords="") for _ in range(3)]
    fixed = merge_rubrics(instances, "Scratch", min_support=2)
    assert fixed["meta"]["unscorable_dimensions"] == ["spatial"]

    result = score_output(
        {"pattern_candidate": "Scratch", "location_text": "somewhere on the wafer",
         "morphology_text": "a continuous band, high density, ring, sharp continuous"},
        fixed,
    )
    assert result["scored_dimensions"] == ["morphology"]
    assert result["dimensions"]["spatial"]["score"] is None
    assert result["overall"] == result["dimensions"]["morphology"]["score"] == 1.0


def test_bleu_and_rouge_bounds():
    text = "a continuous ring of failing dies at the wafer edge"
    assert rouge_l(text, text)["f1"] == 1.0
    assert bleu(text, text) == 1.0
    assert rouge_l("", text)["f1"] == 0.0
    assert bleu("totally different words here", text) == 0.0


# generate / judge

def test_generator_parses_and_returns_rubric():
    backend = FakeBackend([json.dumps(instance())])
    rubric = RubricGenerator(backend=backend).convert(
        {"pattern_candidate": "Edge-Ring", "location_text": "edge", "morphology_text": "ring",
         "total_description": "edge ring"}
    )
    assert rubric["defect_types"] == "Edge-Ring"
    assert backend.calls == 1


def test_generator_retries_then_raises():
    backend = FakeBackend(["not json", json.dumps({"defect_types": "Center"}), "still not json"])
    with pytest.raises(RubricGenError):
        RubricGenerator(backend=backend).convert({"pattern_candidate": "Center"})
    assert backend.calls == 3  # 1 + 재시도 2


def test_parse_rubric_accepts_code_fence():
    fenced = "```json\n" + json.dumps(instance()) + "\n```"
    assert parse_rubric(fenced)["defect_types"] == "Edge-Ring"


def test_judge_parses_scores_and_mean():
    backend = FakeBackend([json.dumps({"spatial": 5, "morphology": 4, "faithfulness": 3, "rationale": "ok"})])
    result = LLMJudge(backend=backend).judge({"pattern_candidate": "Center"}, None, mode="plain")
    assert result["judge_mean"] == 4.0 and result["judge_mode"] == "plain"


def test_judge_rejects_out_of_range_then_exhausts():
    backend = FakeBackend([json.dumps({"spatial": 9, "morphology": 4, "faithfulness": 3})] * 3)
    with pytest.raises(JudgeCallError):
        LLMJudge(backend=backend).judge({"pattern_candidate": "Center"}, None, mode="plain")
    assert backend.calls == 3


def test_judge_rubric_mode_embeds_criteria():
    fixed = merge_rubrics([instance() for _ in range(3)], "Edge-Ring", min_support=2)
    system, query = build_judge_prompt({"pattern_candidate": "Edge-Ring"}, fixed, "rubric")
    assert "circumferential band" in system and "grid like" in system
    assert "Edge-Ring" in query
    with pytest.raises(ValueError):
        build_judge_prompt({}, None, "rubric")  # 루브릭 없이 rubric 모드 불가


def test_parse_judgement_rejects_missing_axis():
    with pytest.raises(Exception):
        parse_judgement(json.dumps({"spatial": 4, "morphology": 4}))


# 역할별 모델 분리 (#17)

def test_role_models_are_distinct_by_default():
    models = assert_distinct("pty")
    assert len({base_model(m) for m in models.values()}) == 3  # 서술/변환/판정 전부 다름


def test_same_model_in_two_roles_fails_fast(monkeypatch):
    monkeypatch.setattr(rg_models, "JUDGE_MODEL", rg_models.RUBRIC_GEN_MODEL)
    with pytest.raises(ModelSeparationError):
        assert_distinct("pty")


def test_date_pinned_variant_counts_as_same_model(monkeypatch):
    """gpt-5.5 와 gpt-5.5-2026-04-23 은 같은 모델 — 날짜 핀으로 분리를 우회할 수 없다."""
    assert base_model("gpt-5.5-2026-04-23") == base_model("gpt-5.5")
    monkeypatch.setattr(rg_models, "JUDGE_MODEL", "gpt-5.5")
    monkeypatch.setattr(rg_models, "RUBRIC_GEN_MODEL", "gpt-5.5-2026-04-23")
    with pytest.raises(ModelSeparationError):
        assert_distinct("pty")


def test_judge_free_run_only_checks_two_roles(monkeypatch):
    monkeypatch.setattr(rg_models, "JUDGE_MODEL", rg_models.RUBRIC_GEN_MODEL)
    models = assert_distinct("pty", judge_used=False)  # judge 미실행이면 검사 대상 아님
    assert models["rubric_generator"] == rg_models.RUBRIC_GEN_MODEL


# 라벨 없는 표본 생성 (#18)

def test_unlabeled_messages_leak_no_cnn_label():
    """루브릭 표본용 프롬프트에는 CNN 라벨이 어디에도 없어야 한다."""
    messages = build_unlabeled_messages("Stacked wafer map image of 9 wafers.", "ZmFrZQ==")
    texts = [b["text"] for m in messages for b in m["content"] if b["type"] == "text"]
    user_texts = [
        b["text"] for m in messages if m["role"] == "user"
        for b in m["content"] if b["type"] == "text"
    ]
    assert not any("CNN label" in t for t in texts)
    assert all("Center" not in t and "Edge-Ring" not in t for t in user_texts)
    assert any("pattern_candidate" in t for t in texts)  # few-shot 응답의 추론 시범은 유지


def test_unlabeled_description_infers_pattern_from_image():
    unlabeled = VALID | {"pattern_candidate": "Edge-Ring"}
    reader = VLMReader(track="pty", backend=FakeBackend([json.dumps(unlabeled)]))
    out = describe_unlabeled(reader, "Edge-Ring", [_ring_map() for _ in range(3)], None)
    assert out["pattern_candidate"] == "Edge-Ring"  # 모델이 이미지에서 추론한 값
    assert out["image_mode"] == "stacked" and out["vlm_track"] == "pty"


def test_agreement_filter_rejects_mismatched_reading():
    """모델이 이미지를 다르게 읽은 표본은 루브릭 재료로 쓰지 않는다."""
    assert _agrees("Edge-Ring", "edge ring") and _agrees("Center", "Center")
    assert not _agrees("Center", "Edge-Ring") and not _agrees("Unknown", "Scratch")


# sampling

def _fake_df(n: int = 40) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "waferMap": [np.ones((8, 8), dtype=np.uint8) for _ in range(n)],
            "lbl": ["Center"] * n,
            "lotName": [f"lot{i}" for i in range(n)],
            "waferIndex": pd.array(range(n), dtype="Int64"),
        }
    )


def test_rubric_and_eval_pools_are_disjoint():
    df = _fake_df()
    rubric_keys = set(split_pool(df, "Center", "rubric")["lotName"])
    eval_keys = set(split_pool(df, "Center", "eval")["lotName"])
    assert rubric_keys and eval_keys and not (rubric_keys & eval_keys)


def test_sample_groups_shapes_and_no_overlap():
    groups = sample_groups(_fake_df(), "Center", "rubric", n_groups=2, group_size=5)
    assert [len(g["maps"]) for g in groups] == [5, 5]
    keys = [k for g in groups for k in g["wafer_keys"]]
    assert len(set(keys)) == 10


def test_sample_groups_rejects_oversized_request():
    with pytest.raises(ValueError):
        sample_groups(_fake_df(20), "Center", "eval", n_groups=5, group_size=10)
