# 시나리오 드리프트 충돌(단서 덮어쓰기) 검증 — 데이터 빌드(simulator.generate) 이후에만 유효
import json
import pathlib

import pytest

pytestmark = pytest.mark.data   # fab.db 필요 — CI(-m "not data")에서는 제외


def _cards():
    return [json.loads(p.read_text())
            for p in sorted(pathlib.Path("datasets/ground_truth").glob("SC-*.json"))]


def test_no_clue_overwritten_with_default_config():
    """기본 시나리오 수에서는 충돌 회피가 작동해 단서 소실이 없어야 한다."""
    flagged = [c["scenario_id"] for c in _cards() if c.get("clue_overwritten")]
    assert not flagged, f"단서가 덮인 시나리오 {flagged} — 회피 샘플링 확인"


def test_drift_sites_unique_across_scenarios():
    """(장비, 파라미터) 드리프트 주입 지점이 시나리오 간에 겹치지 않아야 한다."""
    seen = {}
    for c in _cards():
        for clue in c.get("telemetry_clues", []):
            key = (clue["equipment"], clue["param"])
            assert key not in seen, \
                f"{key} 충돌: {seen[key]} vs {c['scenario_id']}"
            seen[key] = c["scenario_id"]


def test_promised_drift_clues_exist_in_telemetry():
    """정답 카드가 '단서 있음'이라 약속한 드리프트가 실제 텔레메트리에 있어야 한다.
    (t0 이후 평균이 드리프트 방향으로 이동 — 덮어쓰기로 소실됐다면 실패)"""
    from server.db import query
    checked = 0
    for c in _cards():
        if c["is_unmatched"] or c.get("clue_overwritten"):
            continue
        for clue in c["telemetry_clues"]:
            rows = query("SELECT ts, value FROM telemetry "
                         "WHERE equipment_id=? AND param=?",
                         (clue["equipment"], clue["param"]))
            before = [r["value"] for r in rows if r["ts"] < c["t0"]]
            after = [r["value"] for r in rows if r["ts"] >= c["t0"]]
            assert before and after, f"{c['scenario_id']} {clue}: t0 전후 데이터 없음"
            diff = sum(after) / len(after) - sum(before) / len(before)
            direction = 1 if clue["drift"].endswith("_up") else -1
            assert diff * direction > 0, \
                (f"{c['scenario_id']} {clue['equipment']}/{clue['param']}: "
                 f"{clue['drift']} 약속인데 평균 변화 {diff:+.4f} — 단서 소실 의심")
            checked += 1
    assert checked > 0, "검사된 단서가 0건 — telemetry_clues 필드 확인"
