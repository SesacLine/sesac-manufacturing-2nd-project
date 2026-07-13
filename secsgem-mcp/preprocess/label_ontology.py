"""KG 명명과 3자 일치 필수. 여기가 어긋나면 에이전트의 그래프 검색이 어긋남."""

# MixedWM38 one-hot 8차원 순서 (C2~C9) — 공식 문서 기준
MW38_ONEHOT_ORDER = [
    "Center", "Donut", "Edge_Loc", "Edge_Ring",
    "Loc", "Near_Full", "Scratch", "Random",
]

# (MW38 명칭, WM-811K failureType 명칭) -> KG 표준 엔티티
_ALIGN = {
    "Center":    ("Center",    "Center"),
    "Donut":     ("Donut",     "Donut"),
    "Edge_Loc":  ("Edge-Loc",  "Edge-Loc"),
    "Edge_Ring": ("Edge-Ring", "Edge-Ring"),
    "Loc":       ("Loc",       "Loc"),
    "Near_Full": ("Near-full", "Near-Full"),
    "Scratch":   ("Scratch",   "Scratch"),
    "Random":    ("Random",    "Random"),
    # Normal: MW38 all-zero, WM-811K 'none'
    "Normal":    ("none",      "Normal"),
}

def to_kg_entity(label: str) -> str:
    """어떤 표기(MW38/WM811K/변형)든 KG 표준 엔티티명으로 통일."""
    norm = label.strip().replace("_", "-").lower()
    for mw38, (wm811k, kg) in _ALIGN.items():
        if norm in {mw38.replace("_", "-").lower(),
                    wm811k.replace("_", "-").lower(),
                    kg.replace("_", "-").lower()}:
            return kg
    raise KeyError(f"미정의 라벨: {label!r} — mapping_table과 정렬 사전 점검 필요")

def onehot_to_kg(vec) -> list[str]:
    """MW38 one-hot(8) -> KG 엔티티 리스트. all-zero면 ['Normal']."""
    kgs = [to_kg_entity(MW38_ONEHOT_ORDER[i]) for i, v in enumerate(vec) if v == 1]
    return kgs or [to_kg_entity("Normal")]