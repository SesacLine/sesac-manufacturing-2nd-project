"""웨이퍼맵 판독 경로 한정 E2E 테스트 코드 — ground truth 시나리오 11종 전부.

범위: ① CNN 라벨 → ③ 관측(스태킹 멤버 규칙 및 VLM) → ④ KG 조회 진입 경계까지.
⑤ Hypothesis · ⑥ Critic · ⑦ 응답생성은 다루지 않는다.

실행 방법 (전부 @pytest.mark.data — CI의 `-m "not data"`에서는 자동 제외):

    uv run pytest -q -m data backend/tests/test_e2e_wafer_reading_path.py
    VLM_E2E=1 uv run pytest -q -m data backend/tests/test_e2e_wafer_reading_path.py

- fab.db가 없으면 전부 skip된다(secsgem-mcp/README.md "데이터 준비" 선행).
- VLM 실호출은 과금이 있으므로 환경변수 `VLM_E2E=1`을 준 사람만 돈다(대표 시나리오 1건만).
- 전체 배치 서버 경로는 uvicorn 기동이 필요해 pytest로 자동화하지 않는다.

CNN 입력은 2트랙이다:
- **정답 라벨 흉내(is_normal)** — ③④ 계약 게이트용. "①이 완벽했다면"을 고정해 모델 오분류가
  기준선 단언을 흔들지 못하게 한다. is_normal은 평가/테스트 하네스라 정답 누출과 무충돌
  (node_spec_01 §4-2와 같은 논리).
- **실 CNN 판정(공유 체크포인트)** — ①→③ 실배선 게이트용(`test_real_cnn_wiring`).
  팀 전원이 같은 체크포인트를 쓰기로 해(07-24) 결과가 결정적이다. 모델 정확도는 단언하지
  않고 배선만 단언한다 — 실측: SC-CENTER-01에서 실판정 필터 시 `random@center`
  (정답 라벨 기준 `cluster@center`보다 오염 — FP 혼입·미검출의 영향, 판독 정확도 평가 대상).

기준선표(BASELINES)는 07-24 실측이다. 시드 고정 fab.db + 정답 라벨 필터 기준이라 결정적이며,
**기대값과 다른 "오염된" 기준선도 그대로 고정**했다 — 아래 항목별 주석의 알려진 한계가 원인이고
(quantitative 대형 스택 한계, Scratch 스택 희석 — node_spec_03 §8-1), 그 한계가 고쳐지면 이
표가 빨간불로 알려주는 것이 의도다. 수치를 "정답"으로 읽지 말 것.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.data  # fab.db 필요 — CI(-m "not data")에서는 제외

REPO_ROOT = Path(__file__).resolve().parents[2]
FAB_DB = REPO_ROOT / "secsgem-mcp" / "datasets" / "fab.db"
GT_DIR = REPO_ROOT / "secsgem-mcp" / "datasets" / "ground_truth"
HYPOTHESES = REPO_ROOT / "kg_rca" / "outputs" / "hypotheses.json"
CKPT = REPO_ROOT / "wafer_reading" / "classifier" / "checkpoints" / "resnet18_5cls.pt"

# 시나리오별 기준선: (그룹 패턴, 정답 라벨 필터 signature, KG에 GT 매핑 후보가 있는가)
# gt_hit=None은 unmatched 시나리오(정답 원인 없음 — "판단 불가"가 정답)라 hit 단언 대상이 아님.
BASELINES: dict[str, tuple[str, str, bool | None]] = {
    "SC-CENTER-01": ("Center", "cluster@center", True),
    "SC-CENTER-02": ("Center", "ring@edge", True),  # ⚠️ 오염 — quantitative 대형 스택 한계(§8-1)
    "SC-CENTER-03": ("Center", "ring@edge", True),  # ⚠️ 〃
    "SC-EDGE-RING-01": ("Edge-Ring", "ring@edge", True),
    "SC-EDGE-RING-02": ("Edge-Ring", "ring@edge", True),
    "SC-EDGE-RING-03": ("Edge-Ring", "ring@edge", False),  # ⚠️ 문자열 대조 한계 — 정답 후보(excessive_down_force@CMP)는 존재하나 자동 tier라 matched_cause가 없음(로그 #8)
    "SC-SCRATCH-01": ("Scratch", "ring@edge", True),  # ⚠️ 오염 — Scratch 스택 희석(quantitative는 스택 기반, §8-1)
    "SC-SCRATCH-02": ("Scratch", "random@edge", True),  # ⚠️ 〃
    "SC-SCRATCH-03": ("Scratch", "random@edge", True),  # ⚠️ 〃
    "SC-UNMATCHED-01": ("Center", "ring@edge", None),
    "SC-UNMATCHED-02": ("Edge-Ring", "ring@edge", None),
}


@pytest.fixture(scope="module")
def fab_db():
    if not FAB_DB.exists():
        pytest.skip("fab.db 없음 — secsgem-mcp/README.md '데이터 준비' 선행 필요")
    os.environ["FAB_DB"] = str(FAB_DB)
    return FAB_DB


def _load_gt(scenario: str) -> dict:
    path = GT_DIR / f"{scenario}.json"
    if not path.exists():
        pytest.skip(f"{scenario}.json 없음 — fab.db 재생성 시 함께 생성됨")
    return json.loads(path.read_text(encoding="utf-8"))


def _fetch_wafers(fab_db: Path, lot_ids: list[str]) -> list[tuple[str, str, bytes, int]]:
    con = sqlite3.connect(f"file:{fab_db}?mode=ro", uri=True)
    try:
        ph = ",".join("?" * len(lot_ids))
        rows = con.execute(
            f"SELECT lot_id, wafer_id, die_map, is_normal FROM wafer "
            f"WHERE lot_id IN ({ph}) AND die_map IS NOT NULL",
            lot_ids,
        ).fetchall()
    finally:
        con.close()
    if not rows:
        pytest.skip("GT 로트의 die_map 웨이퍼가 fab.db에 없음 — fab.db·ground_truth 세대 불일치")
    return rows


def _label_state(fab_db: Path, scenario: str) -> tuple[dict, dict]:
    """정답 라벨(is_normal)로 CNN 판정을 흉내낸 ③ 입력 state — (state, gt) 반환."""
    gt = _load_gt(scenario)
    pattern = BASELINES[scenario][0]
    rows = _fetch_wafers(fab_db, gt["lot_ids"])
    state = {
        "groups": [
            {"group_id": "t", "pattern": pattern, "lot_ids": gt["lot_ids"], "status": "ok"}
        ],
        "cnn_results": [
            {"lot_id": lot, "wafer_id": wafer, "pattern": pattern if is_normal == 0 else "Normal"}
            for lot, wafer, _, is_normal in rows
        ],
    }
    return state, gt


# --- §0 사전 점검 ---------------------------------------------------------


def test_fab_db_is_test_only_build(fab_db):
    """fab.db가 Test-only 재빌드본(07-23)인지 — 시드 고정 빌드라 수치가 결정적이다."""
    con = sqlite3.connect(f"file:{fab_db}?mode=ro", uri=True)
    try:
        total = con.execute("SELECT COUNT(DISTINCT lot_id) FROM wafer").fetchone()[0]
        with_map = con.execute(
            "SELECT COUNT(DISTINCT lot_id) FROM wafer WHERE die_map IS NOT NULL"
        ).fetchone()[0]
    finally:
        con.close()
    assert total == 884, f"로트 {total}개 — 884(배경 800+시나리오 84)가 아니면 구세대 fab.db"
    assert with_map == 84, "die_map 보유 로트는 시나리오 84개여야 함 (배경은 NULL이 정상)"


def test_all_ground_truth_scenarios_covered(fab_db):
    """이 파일의 기준선표가 ground_truth 폴더의 시나리오를 전부 다루는지 (신규 시나리오 감지)."""
    on_disk = {p.stem for p in GT_DIR.glob("SC-*.json")}
    assert on_disk == set(BASELINES), (
        f"기준선표와 ground_truth 불일치 — 표에 없음: {on_disk - set(BASELINES)}, "
        f"디스크에 없음: {set(BASELINES) - on_disk} (fab.db 재생성/시나리오 추가 시 표 갱신)"
    )


# --- §2 관측 → KG 경계: 시나리오 11종 전부 (무과금) ------------------------


@pytest.mark.parametrize("scenario", list(BASELINES))
def test_observation_signature_baseline(fab_db, scenario):
    """정답 라벨 필터 관측의 signature가 07-24 기준선과 같은지 (멤버 규칙 PR #58 회귀 게이트).

    기준선이 패턴 기대와 다른 항목(⚠️ 주석)은 알려진 한계의 현재값 고정이다 — 한계가
    개선되면 여기가 빨간불이 되고, 그때 기준선을 올리면 된다.
    """
    from backend.nodes.vlm_describe import observe_groups

    state, _ = _label_state(fab_db, scenario)
    expected = BASELINES[scenario][1]
    obs = observe_groups(state)["groups"][0]["observation"]
    assert obs.get("signature") == expected, (
        f"{scenario}: signature={obs.get('signature')} (기준선 {expected}) — "
        "멤버 규칙/quantitative 회귀 또는 기준선 갱신 필요"
    )


@pytest.mark.parametrize("scenario", list(BASELINES))
def test_kg_candidates_baseline(fab_db, scenario):
    """④ 경계: 후보가 조회되고, GT 매핑 후보 존재 여부가 기준선과 같은지."""
    from backend.graph_client import KGClient
    from backend.nodes.vlm_describe import observe_groups

    if not HYPOTHESES.exists():
        pytest.skip("kg_rca/outputs/hypotheses.json 없음")
    state, gt = _label_state(fab_db, scenario)
    pattern, _, expected_hit = BASELINES[scenario]
    obs = observe_groups(state)["groups"][0]["observation"]
    cands = KGClient(HYPOTHESES).get_candidates(pattern, observation=obs)["candidates"]
    # 후보 수는 KG 재생성·관측에 따라 변하므로 하드코딩 금지(CLAUDE.md) — 존재만 확인
    assert cands, f"{scenario}: {pattern} 후보 0건 — KGClient/hypotheses.json 스키마 정합 확인"

    if expected_hit is None:
        return  # unmatched 시나리오 — 정답 원인이 없는 게 정상(최종 판정은 ⑤⑥ 몫)
    truths = set(gt["true_root_causes"])
    hit = [c for c in cands if any(t in json.dumps(c) for t in truths)]
    if expected_hit:
        assert hit, f"{scenario}: {truths} 매핑 후보가 KG에 없음 — kg_rca 재빌드/매핑 확인"
    else:
        # 문자열 대조 한계(로그 #8): 정답 후보는 자동 tier로 존재하나 matched_cause가 없다
        # (매핑은 근거없음 tier 전용). 매핑 커버리지가 확장되면 이 단언이 깨진다 → True로 갱신.
        assert not hit, f"{scenario}: matched_cause 커버리지가 확장된 듯 — 기준선 갱신(True) 필요"


def test_observation_survives_without_cnn_results(fab_db):
    """하위호환: cnn_results 없는 단독 호출은 로트 전체 폴백으로 여전히 관측을 만든다."""
    from backend.nodes.vlm_describe import observe_groups

    gt = _load_gt("SC-CENTER-01")
    state = {
        "groups": [
            {"group_id": "t", "pattern": "Center", "lot_ids": gt["lot_ids"], "status": "ok"}
        ]
    }
    obs = observe_groups(state)["groups"][0]["observation"]
    assert obs is not None and obs.get("pattern_candidate") == "Center"


# --- ①→③ 실배선: 공유 체크포인트 실판정 (무과금, 체크포인트 필요) ---------


def test_real_cnn_wiring(fab_db):
    """실 CNN 판정 → 멤버 필터 → 관측까지의 배선. 모델 정확도는 단언하지 않는다.

    배선은 시나리오와 무관하므로 대표 1건(SC-CENTER-01)만 쓴다. 공유 체크포인트
    (팀 드라이브, 07-24 전원 동일 합의) 전제라 결과가 결정적이다.
    실측: 결함 18장 정판정 + 정상 5장 오판정 혼입 → signature `random@center`
    (zone 정확·shape 오염). 격차는 모델 품질 문제라 zone(@center)까지만 단언한다.
    """
    if not CKPT.exists():
        pytest.skip("체크포인트 없음 — 팀 드라이브에서 받기 (team_test_guide §3) 또는 train.py")

    import io

    import numpy as np

    from backend.nodes.vlm_describe import observe_groups
    from wafer_reading.classifier.infer import WaferClassifier

    gt = _load_gt("SC-CENTER-01")
    rows = _fetch_wafers(fab_db, gt["lot_ids"])
    clf = WaferClassifier(str(CKPT))
    preds = clf.classify_batch(
        [np.load(io.BytesIO(blob), allow_pickle=False) for _, _, blob, _ in rows]
    )

    valid = {"Center", "Edge-Ring", "Scratch", "Unknown", "Normal"}
    assert all(p["pattern"] in valid for p in preds), "5클래스 밖의 라벨 — CLASSES 순서/계약 확인"
    assert any(p["pattern"] == "Center" for p in preds), "Center 판정 0장 — 체크포인트 세대 확인"

    state = {
        "groups": [
            {"group_id": "t", "pattern": "Center", "lot_ids": gt["lot_ids"], "status": "ok"}
        ],
        "cnn_results": [
            {"lot_id": lot, "wafer_id": wafer, "pattern": p["pattern"]}
            for (lot, wafer, _, _), p in zip(rows, preds)
        ],
    }
    obs = observe_groups(state)["groups"][0]["observation"]
    sig = obs.get("signature")
    assert sig, "실판정 기반 관측에 signature 없음 — ①→③ 배선 확인"
    assert sig.endswith("@center"), (
        f"signature={sig} — zone이 center가 아니면 멤버 필터/스태킹 회귀 의심"
    )


# --- §3 VLM 실호출 (opt-in — 과금) ----------------------------------------


def test_vlm_live_call_pty(fab_db):
    """VLM_E2E=1일 때만: pty 실호출 1회 — PR #55 계약(전부 observation 내부)을 실호출로 확인.

    과금 절약을 위해 대표 1건(SC-CENTER-01)만 호출한다 — 계약은 시나리오와 무관.
    """
    if os.getenv("VLM_E2E", "").lower() not in ("1", "true", "yes"):
        pytest.skip("과금 방지 opt-in — VLM_E2E=1을 주면 실행")
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY 없음 (.env)")

    state, _ = _label_state(fab_db, "SC-CENTER-01")
    os.environ["VLM_LIVE"] = "1"
    os.environ["VLM_TRACK"] = "pty"
    try:
        from backend.nodes.vlm_describe import observe_groups

        group = observe_groups(state)["groups"][0]
    finally:
        os.environ.pop("VLM_LIVE", None)

    obs = group["observation"]
    assert obs.get("vlm_track") == "pty", "VLM 실생성 메타 없음 — 호출 실패로 강등됐는지 확인"
    assert obs.get("image_mode") == "stacked", "Center는 스태킹 이미지여야 함(Scratch만 단일)"
    assert obs.get("location_text") and obs.get("morphology_text"), "VLM 자연어가 비어 있음"
    assert obs.get("total_description"), "total_description 없음 (사용자 노출용 — 이슈 #61)"
    # PR #55 계약: group 레벨에는 아무것도 안 붙는다
    for key in ("total_description", "vlm_track", "image_mode"):
        assert key not in group, f"group 레벨에 {key} 잔존 — PR #55 회귀"
    # 결정적 관측은 VLM이 못 건드린다 (faithfulness 원칙)
    assert obs.get("signature") == "cluster@center", "VLM 오버레이가 결정적 값을 훼손함"
