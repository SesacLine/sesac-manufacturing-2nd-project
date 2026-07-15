import functools
import pathlib

import yaml

YAML_PATH = pathlib.Path(__file__).parent / "fab_model.yaml"


@functools.lru_cache(maxsize=1)
def load() -> dict:
    return yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))


def group_of(equipment_id: str) -> str | None:
    """'CLEAN-02' 또는 'CLEAN-02-CH1' → 'CLEAN' (fab_model 그룹 키)"""
    base = equipment_id.split("-CH")[0]
    for grp, spec in load()["equipment"].items():
        if base in spec["instances"]:
            return grp
    return None


def normal_range(equipment_id: str, param: str) -> list[float] | None:
    grp = group_of(equipment_id)
    if grp is None:
        return None
    p = load()["equipment"][grp]["params"].get(param)
    return list(p["normal"]) if p else None
