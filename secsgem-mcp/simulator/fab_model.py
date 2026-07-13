"""fab_model.yaml 로더 — 파라미터 정상 범위 조회.

server/tools/query_telemetry 가 정상 범위 표시에 쓴다.
사실만 반환(P5): 범위 밖 여부 '판단'은 에이전트 몫, 여기선 숫자만 준다.
"""
import functools
import pathlib

import yaml

YAML_PATH = pathlib.Path(__file__).parent / "fab_model.yaml"


@functools.lru_cache(maxsize=1)
def load() -> dict:
    return yaml.safe_load(YAML_PATH.read_text())


def group_of(equipment_id: str) -> str | None:
    """'CLEAN-02' 또는 'CLEAN-02-CH1' → 'CLEAN' (fab_model 그룹 키)."""
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
