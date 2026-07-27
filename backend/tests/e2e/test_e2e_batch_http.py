"""배치 HTTP E2E — POST /api/v1/batches → 폴링 → GET .../analyses/{id} 실서버 경로 관통.

범위: ⓪~⑦ 전체를 **실제 HTTP 계약**으로(TestClient, in-process ASGI) — 노드를 직접 부르는
게 아니라 라우터·비동기 배치 태스크·store 영속화까지 실제 코드 경로를 태운다.
`test_hypocritic_scenario_eval.py`(④→⑤→⑥ 노드 직접 호출, ground_truth lot_ids 정밀 타격,
랭킹·함정 회귀)와 상호 보완 관계 — 여기는 "전체 배선이 실제로 끝까지 붙어 있는가"만 본다,
랭킹/정답 여부는 안 본다(그건 그 파일 몫).

**이전에 "안 됨"으로 문서화됐던 것을 뒤집는다**: 이 파일의 옛 자리
(secsgem-mcp/tests/test_e2e_samples.py, M4 스텁 — backend 존재 이전에 쓰인 가상 API
`.verdict`/`has_next_actions_section`라 실제 계약과 대응이 없어 이 파일로 대체하며 제거)와
test_e2e_wafer_reading_path.py 모듈 docstring 둘 다 "전체 배치 서버 경로는 uvicorn 기동이
필요해 pytest로 자동화하지 않는다"고 적어놨었다. 실측해보니 틀렸다 — `with TestClient(app)
as c:` 블록은 lifespan으로 이벤트루프를 살려두고, 배치가 `asyncio.create_task()`로 뜨는
장수 코루틴이라 그 루프 위에서 그대로 진행된다(2026-07-27 프로브: POST 후 GET을 반복하는
동안 current_step·logs가 실제로 진행됨을 확인). uvicorn 없이도 완전히 자동화된다.

과금 opt-in: ⑤ Hypothesis가 실LLM+실MCP를 태우므로 `BATCH_E2E=1` 없이는 skip
(VLM_E2E/HYPO_CRITIC_EVAL과 동일 관례).

    BATCH_E2E=1 pytest -m data backend/tests/e2e/test_e2e_batch_http.py
"""

from __future__ import annotations

import importlib
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.data  # fab.db 필요 — CI(-m "not data")에서는 제외

REPO_ROOT = Path(__file__).resolve().parents[3]
FAB_DB = REPO_ROOT / "secsgem-mcp" / "datasets" / "fab.db"

POLL_INTERVAL_S = 3
POLL_TIMEOUT_S = 600  # 실LLM 배치라 여유 있게(대부분 1~2분 내 완료)

# §2.5 status enum(v2.0, normal_reading 포함 — #69) · §2.5 confidence(R1, "high" 없음)
VALID_STATUSES = {"reviewed", "insufficient", "unmapped", "novel", "normal_reading"}
VALID_CONFIDENCE = {"medium", "low"}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """모듈 전체가 공유하는 TestClient — app_state.db를 임시 파일로 격리해 개발자의
    실제 DB나 "하루 1회 완료 배치" 가드와 충돌하지 않는다. FAB_DB는 절대경로로 고정한다
    (cwd 의존 방지 — test_e2e_wafer_reading_path.py와 동일 관례).
    """
    if os.getenv("BATCH_E2E", "").lower() not in ("1", "true", "yes"):
        pytest.skip("과금 방지 opt-in — BATCH_E2E=1을 주면 실행")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY 없음 (.env)")
    if not FAB_DB.exists():
        pytest.skip("fab.db 없음 — secsgem-mcp/README.md '데이터 준비' 선행 필요")

    db_path = tmp_path_factory.mktemp("app_state") / "app_state_test.db"
    prev_app_db = os.environ.get("APP_STATE_DB")
    prev_fab_db = os.environ.get("FAB_DB")
    os.environ["APP_STATE_DB"] = str(db_path)
    os.environ["FAB_DB"] = str(FAB_DB)
    try:
        from backend import main as main_module

        importlib.reload(main_module)  # main import 시점에 init_db가 돌므로 env 설정 후 리로드
        with TestClient(main_module.app) as c:
            yield c
    finally:
        for key, prev in (("APP_STATE_DB", prev_app_db), ("FAB_DB", prev_fab_db)):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev


def _poll_until_done(client: TestClient, batch_id: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_S
    batch = None
    while time.monotonic() < deadline:
        batch = client.get(f"/api/v1/batches/{batch_id}").json()
        if batch["status"] in ("completed", "failed"):
            return batch
        time.sleep(POLL_INTERVAL_S)
    pytest.fail(f"배치가 {POLL_TIMEOUT_S}s 안에 끝나지 않음 — 마지막 상태: {batch}")


@pytest.fixture(scope="module")
def completed_batch(client: TestClient) -> dict:
    """모듈 안에서 실배치를 딱 1회만 완료까지 돌리고 두 테스트가 공유(과금 절감)."""
    r = client.post("/api/v1/batches")
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "running"
    return _poll_until_done(client, r.json()["batch_id"])


def test_batch_completes_via_http_and_produces_valid_analyses(client, completed_batch):
    """배치가 완료되고, 만들어진 분석 전부가 §2.5 계약(status·confidence·필드 존재)을
    지키며, 대기열(§2.2)에도 그대로 보이는지 — "배선이 끝까지 붙어있는가"만 본다."""
    batch = completed_batch
    assert batch["status"] == "completed", (
        f"배치 실패 — error={batch['error']}  logs(끝5)={batch['logs'][-5:]}"
    )
    assert batch["result_ids"], "완료 배치인데 result_ids가 빈 목록(그룹 0개?)"

    for analysis_id in batch["result_ids"]:
        detail = client.get(f"/api/v1/analyses/{analysis_id}")
        assert detail.status_code == 200, f"{analysis_id} 상세 조회 실패: {detail.text}"
        body = detail.json()

        assert body["status"] in VALID_STATUSES, f"{analysis_id}: 알 수 없는 status {body['status']}"
        assert body["confidence"] in VALID_CONFIDENCE, f"{analysis_id}: confidence={body['confidence']}"
        assert body["lot_ids"], f"{analysis_id}: lot_ids 빈 목록"
        assert isinstance(body["actions"], list)
        assert isinstance(body["hypotheses"], list)
        # §2.5 정렬 불변식 — reviewed는 최소 1건 채택이 있어야 그 status가 되므로 index 0은
        # 항상 accepted다(response.py _ordered_hypotheses: accepted를 먼저 채운다).
        if body["status"] == "reviewed" and body["hypotheses"]:
            assert body["hypotheses"][0]["verdict"] == "accepted", (
                f"{analysis_id}: index 0이 accepted가 아님(§2.5 정렬 불변식 위반)"
            )

    # 배치→저장→대기열 3단이 실제로 이어졌는지 — GET /analyses(§2.2)에도 그대로 보여야 함.
    queue = client.get("/api/v1/analyses?sort=latest&limit=50&offset=0").json()
    queued_ids = {item["analysis_id"] for item in queue["items"]}
    assert set(batch["result_ids"]) <= queued_ids, "배치 결과가 대기열(GET /analyses)에 안 보임"


def test_duplicate_batch_same_day_is_409(client, completed_batch):
    """§2.3 하루 1회 정책 — 완료 배치가 있으면 재요청은 409.

    completed_batch가 이미 이 모듈의 app_state.db에 완료 배치를 1건 만들어놨다(위 테스트와
    공유) — 여기서 새 실배치를 또 돌리지 않고 그 상태를 그대로 재사용한다.
    """
    r = client.post("/api/v1/batches")
    assert r.status_code == 409
    assert "완료된 분석" in r.json()["detail"]
