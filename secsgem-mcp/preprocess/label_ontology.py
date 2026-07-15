import typing

_ALIGN = {
    "Center":    "Center",
    "Donut":     "Donut",
    "Edge-Loc":  "Edge-Loc",
    "Edge-Ring": "Edge-Ring",
    "Loc":       "Loc",
    "Near-full": "Near-Full",
    "Scratch":   "Scratch",
    "Random":    "Random",
    "none":      "Normal",
}

SCENARIO_CLASSES = frozenset({"Center", "Edge-Ring", "Scratch"})
NORMAL_CLASS = "Normal"
EXCLUDED_CLASSES = frozenset({"Donut", "Edge-Loc", "Loc", "Near-Full", "Random"})

def to_kg_entity(label: str) -> str:
    norm = label.strip().replace("_", "-").lower()
    for raw, kg in _ALIGN.items():
        if norm in {raw.replace("_", "-").lower(), kg.replace("_", "-").lower()}:
            return kg
    raise KeyError(f"미정의 라벨: {label!r} — mapping_table과 정렬 사전 점검 필요")

def scope_of(kg_label: typing.Optional[str]) -> str:
    """scenario | normal | excluded | unlabeled"""
    if kg_label is None:
        return "unlabeled"
    if kg_label in SCENARIO_CLASSES:
        return "scenario"
    if kg_label == NORMAL_CLASS:
        return "normal"
    return "excluded"