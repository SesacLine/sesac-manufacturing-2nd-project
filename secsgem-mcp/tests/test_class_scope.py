import pytest
pytestmark = pytest.mark.data


def test_scope_counts(wm811k_df):
    counts = wm811k_df["scope"].value_counts().to_dict()
    print(f"스코프별 실측: {counts}")
    assert counts["scenario"] > 0 and counts["normal"] > 0


def test_excluded_never_in_scenario(wm811k_df):
    sc = wm811k_df[wm811k_df.scope == "scenario"]
    assert set(sc.kg_label.unique()) <= {"Center", "Edge-Ring", "Scratch"}