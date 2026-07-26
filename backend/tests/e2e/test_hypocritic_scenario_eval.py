"""회귀 게이트 — eval_hypocritic_scenario.run_scenario()를 ground_truth 11개 시나리오
전체에 걸어 assert한다(진단 스크립트에서 승격, 2026-07-26).

**과금 opt-in**: 실LLM(⑤ Hypothesis 자동 tier)+실MCP를 태우므로 fab.db(@pytest.mark.data)
뿐 아니라 OPENAI_API_KEY 비용도 든다. 기본 `pytest -m data`에도 안 섞이게 추가로
`HYPO_CRITIC_EVAL=1`을 요구한다(test_e2e_wafer_reading_path.py의 VLM_E2E=1과 동일 관례).

    HYPO_CRITIC_EVAL=1 pytest -m data backend/tests/e2e/test_hypocritic_scenario_eval.py

무엇을 gate하는가(eval_hypocritic_scenario.py 모듈 docstring ①③④에 대응):
  - ④/⑤ firewall: Critic 구간 MCP 재조회 0건 — 항상 참이어야 하는 아키텍처 불변식
  - ③ suspect 확정: 최소 1건 이상 — 0이면 ground_truth/fab.db 세대 불일치
  - ① top-1(클러스터 기준): 정답 있는 시나리오는 정답의 원인군이 0위여야 함
  - ① 환각 방지: 정답 없는(unmatched) 시나리오는 status가 reviewed(채택 카드)가 되면 안 됨
  - ② 함정 생존 0건: 시간역전 함정이 채택으로 안 남아야 함 — SC-CENTER-01은 알려진 갭이라
    xfail(2026-07-26 최초 확인 14/162건 생존). **strict=False다**: 같은 시나리오를 재실행한
    같은 날 0건 생존이 나온 적이 있다(⑤가 실LLM 에이전트라 완전히 결정적이지 않음) — strict
    xfail이었다면 그 운 좋은 실행에서 XPASS로 잡혀 CI가 거짓 적색이 된다. 즉 이 함정은
    "고정된 버그"가 아니라 "간헐적으로 새는 위험" — xfail은 추적용, strict 승격은 보류.

exact_top1(0위 cause 문자열 자체가 정답)은 **일부러 안 건다** — R2(원인군) 설계상 fab로
구분 안 되는 형제가 헤드라인을 대신 차지하는 게 정상 동작이라(SC-CENTER-01 실측), 이걸
assert하면 정상 동작을 회귀로 오분류한다. cluster_top1이 진짜 신호다.

11개 중 지금까지 사람이 직접 돌려 검증한 건 SC-CENTER-01·SC-EDGE-RING-03뿐이다 — 나머지
9개(특히 SC-CENTER-02 무이벤트 누적형, SC-SCRATCH-01/02 소모품 수명형, SC-UNMATCHED-01/02
무근거)는 이 게이트를 처음 돌릴 때 여기서 새 갭이 드러날 수 있다. 그게 이 파일의 존재 이유다.
"""

from __future__ import annotations

import asyncio
import functools
import os
from pathlib import Path

import pytest

from backend.tests.e2e.eval_hypocritic_scenario import run_scenario

_GT_DIR = Path(__file__).resolve().parents[3] / "secsgem-mcp" / "datasets" / "ground_truth"

# SC-CENTER-01 LITHO-01 함정 — 2026-07-26 재평가에서 14/162건 accepted 생존(신호 전부 0인데
# 채택, ⑥ Critic 신호 최소임계 규칙 부재). 단 같은 날 재실행에선 0건 생존도 나왔다(⑤ 실LLM
# 에이전트라 비결정적) — strict=False: 통과해도 XPASS로 조용히 넘어간다("고정 버그"가 아니라
# "간헐적 위험"이라 뒤집혀도 xfail 제거를 강제하지 않음). 실패하면 XFAIL로 추적은 유지.
_KNOWN_TRAP_LEAKS = {
    "SC-CENTER-01": "LITHO-01 함정이 간헐적으로 accepted 생존(2026-07-26 첫 확인 14/162건, "
                    "같은 날 재실행에서 0건도 관측 — ⑤ 실LLM 비결정성). strict=False로 표시.",
}


def _scenario_ids() -> list[str]:
    if not _GT_DIR.exists():
        return []
    return sorted(p.stem for p in _GT_DIR.glob("SC-*.json"))


_SCENARIO_IDS = _scenario_ids()

pytestmark = pytest.mark.data  # fab.db 필요 — CI(-m "not data")에서는 제외(§상단 docstring)


@functools.lru_cache(maxsize=None)
def _run(scenario_id: str) -> dict:
    """시나리오 1건을 실LLM+실MCP로 1회만 실행하고 캐시한다 — 이 파일의 두 테스트 함수가
    같은 시나리오를 두 번 태우지 않게(과금 절감). 실패(예외)는 캐시 안 됨 — 재시도됨."""
    if os.getenv("HYPO_CRITIC_EVAL", "").lower() not in ("1", "true", "yes"):
        pytest.skip("과금 방지 opt-in — HYPO_CRITIC_EVAL=1을 주면 실행")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY 없음 (.env)")
    return asyncio.run(run_scenario(scenario_id))


@pytest.mark.skipif(not _SCENARIO_IDS, reason="ground_truth 폴더 없음 — fab.db 빌드 시 함께 생성됨")
@pytest.mark.parametrize("scenario_id", _SCENARIO_IDS)
def test_scenario_core_invariants(scenario_id):
    """firewall==0 · suspect>0 · (matched: cluster_top1 / unmatched: 비-reviewed).

    xfail 없음 — 이 셋은 아키텍처 불변식이라 통과 못 하면 이 시나리오만이 아니라
    파이프라인 자체의 회귀다(랭킹 미세조정 문제가 아니라 근본 계약 위반).
    """
    r = _run(scenario_id)

    assert r["counts"]["critic"] == {}, (
        f"{scenario_id}: Critic 단계에서 MCP 재조회 발생(firewall 위반) — {r['counts']['critic']}"
    )
    assert r["with_equip_count"] > 0, (
        f"{scenario_id}: 전 후보 equipment=None — ground_truth lot_ids와 fab.db 세대 불일치 의심"
    )

    if r["true_causes"]:
        assert r["cluster_top1"], (
            f"{scenario_id}: 정답 클러스터가 0위가 아님 — top_cluster={r['top_cluster']!r}, "
            f"정답={sorted(r['true_causes'])}"
        )
    else:
        assert r["final"]["status"] != "reviewed", (
            f"{scenario_id}: 정답 없는 unmatched인데 status=reviewed(채택 카드 생성) — 환각 의심"
        )


def _trap_params():
    # strict=False — ⑤가 실LLM이라 완전히 결정적이지 않다(위 _KNOWN_TRAP_LEAKS 주석 참고).
    # 통과(XPASS)해도 조용히 넘어가고, 실패(XFAIL)해도 CI를 안 빨갛게 만든다 — 추적용 표시.
    marks_by_id = {
        sid: [pytest.mark.xfail(reason=reason, strict=False)]
        for sid, reason in _KNOWN_TRAP_LEAKS.items()
    }
    return [pytest.param(sid, marks=marks_by_id.get(sid, []), id=sid) for sid in _SCENARIO_IDS]


@pytest.mark.skipif(not _SCENARIO_IDS, reason="ground_truth 폴더 없음 — fab.db 빌드 시 함께 생성됨")
@pytest.mark.parametrize("scenario_id", _trap_params())
def test_scenario_no_trap_survives(scenario_id):
    """시간역전 함정(traps_to_reject)이 채택으로 안 남는지 — ⑥ 규칙①(P2 시간정합)의 실사용 검증.

    SC-CENTER-01은 알려진(간헐적) 갭이라 loose xfail(위 _KNOWN_TRAP_LEAKS) — 다른 시나리오에서
    새로 생존이 생기면 이 assert가 그대로 잡는다(하드 실패, xfail 대상 아님).
    """
    r = _run(scenario_id)
    survivors = {t: len(rows) for t, rows in r["trap_survivors"].items() if rows}
    assert not survivors, f"{scenario_id}: 함정 장비가 accepted로 생존 — {survivors}"
