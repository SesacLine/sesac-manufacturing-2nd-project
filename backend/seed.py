"""데모 시딩 — 서버 기동 시 `SEED_UNTIL`까지의 과거 배치를 하루 한 건씩 따라잡는다.

## 왜 필요한가

시연은 "이미 며칠치가 쌓여 있는 화면에서 오늘치를 눌러 누적시키는" 흐름이다. 그런데 빈
`app_state.db`로 서버를 올리면 그 '이전 내역'이 없다. 손으로 배치를 여러 번 누르면 되지만
그건 시연 전에 사람이 해야 하고, 서버를 새로 올릴 때마다(EC2 재배포·DB 리셋) 반복된다.
그 준비를 서버가 스스로 하게 만드는 장치다.

## 왜 "하루 한 배치"인가 — 그냥 한 번 돌리면 안 되나

안 된다. `batch_runner._cursor_range()`는 커서가 없으면 EPOCH부터 전부를 **한 배치**로 잡는다
(BACKEND_DECISIONS D2 "직전 배치 없음 = 전체 누적"). 그 한 방으로는:

  - 한 달치가 카드 몇 장으로 뭉쳐, 정상 운영에서는 나올 수 없는 화면이 된다.
  - **분석 참조 로트(코호트)가 형성되지 않는다.** 판독 이력(`wafer_reading`)은 배치가 끝나야
    저장되므로, 한 배치 안의 날짜들은 서로를 못 본다(cohort_front_proposal.md 확인사항).
  - `analyzed_date`가 전부 같은 날이 되어 대기열이 "하루에 몰아 분석한 것"처럼 보인다.

그래서 **커서를 EPOCH 하루 전에 심어 두고** 시작한다. 커서가 있으면 `config.event_date_for`가
`cursor + 2일`을 '오늘'로 잡으므로, 그 뒤로는 배치마다 정확히 하루씩만 처리된다:

    커서 12/31 → 오늘 1/2, 대상 1/1  →  커서 1/1 → 오늘 1/3, 대상 1/2  →  ...

## 왜 "비어 있으면 시딩"이 아니라 "목표까지 따라잡기"인가

목표(SEED_UNTIL)와 현재 커서의 **차이**만 채우면 세 가지가 한 번에 풀린다:
  - `SEED_UNTIL`을 뒤로 옮기고 재시작하면 그 구간만 이어서 돈다(날짜 변경이 곧 반영).
  - 시딩 도중 서버가 죽어도 재시작하면 끊긴 지점부터 재개된다.
  - 이미 도달했으면 아무것도 안 한다(재시작·다중 기동에 안전).

## 시연 날짜와의 관계

    대상(버튼이 돌릴 날) = SEED_UNTIL + 1일
    화면1 '오늘' 배지     = SEED_UNTIL + 2일

`EVENT_DATE`는 **커서가 없을 때만** 쓰이므로(config.event_date_for) 시딩이 끝나면 무관하다.
다만 DB를 지우면 다시 기준점이 되니 `SEED_UNTIL + 2`로 맞춰 두는 편이 헷갈리지 않는다.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os

from . import batch_runner, store
from .config import DATA_EPOCH, compact, event_date_for

logger = logging.getLogger(__name__)

# 폭주 방지 — 데이터축은 90일이라 이 상한에 닿는 건 설정 실수뿐이다.
MAX_SEED_BATCHES = 200


def seed_target() -> str | None:
    """`SEED_UNTIL`(YYYY-MM-DD). 미설정이면 None = 시딩 기능 자체를 끈다(기본).

    import 시점이 아니라 호출 시점에 읽는다 — 테스트가 monkeypatch로 껐다 켤 수 있게.
    """
    raw = (os.getenv("SEED_UNTIL") or "").strip()
    if not raw:
        return None
    try:
        datetime.date.fromisoformat(raw)
    except ValueError:
        logger.warning("SEED_UNTIL='%s'은 YYYY-MM-DD가 아닙니다 — 시딩을 건너뜁니다.", raw)
        return None
    return raw


async def catch_up_to(target: str, kg_client, mcp) -> int:
    """커서가 target에 닿을 때까지 하루 한 배치씩 돌린다. 실행한 배치 수를 반환.

    이미 target 이상이면 0(no-op). 배치가 실패하거나 처리할 날이 없으면 거기서 멈춘다 —
    같은 날짜를 무한 재시도하지 않기 위해서다.
    """
    if store.find_batch_by_status(["running"]):
        logger.info("[seed] 진행 중인 배치가 있어 시딩을 건너뜁니다.")
        return 0

    cursor = store.get_cursor()
    if cursor is None:
        # D2(전체 누적 캐치업) 분기를 피하려고 EPOCH 하루 전에 커서를 심는다 — 위 docstring.
        cursor = (
            datetime.date.fromisoformat(DATA_EPOCH) - datetime.timedelta(days=1)
        ).isoformat()
        store.set_cursor(cursor)
        logger.info("[seed] 커서 시작점 %s (= %s 전날)", cursor, DATA_EPOCH)

    if cursor >= target:
        logger.info("[seed] 커서 %s — 목표 %s에 이미 도달(할 일 없음).", cursor, target)
        return 0

    logger.info("[seed] %s → %s 시딩 시작 (하루 한 배치)", cursor, target)
    ran = 0
    for _ in range(MAX_SEED_BATCHES):
        cursor = store.get_cursor()
        if cursor is not None and cursor >= target:
            break

        start, end = batch_runner.pending_range()
        if start >= end:            # start는 배타 — 같거나 크면 처리할 날이 없다
            logger.info("[seed] 대상 구간 없음(%s → %s) — 종료", start, end)
            break

        today = event_date_for(store.get_cursor())
        seq = store.next_batch_seq()
        batch_id = f"batch_{compact(today)}_{seq:02d}"
        started_at = f"{today}T{datetime.datetime.now().strftime('%H:%M:%S')}Z"
        store.create_batch(batch_id, seq, started_at, cursor_start=store.get_cursor())
        await batch_runner.run_batch(batch_id, kg_client, mcp)
        ran += 1

        row = store.get_batch(batch_id)
        if row["status"] != "completed":
            # 실패한 날짜는 커서를 전진시키지 않는다 → 다시 돌면 같은 날에 갇힌다. 멈추고 알린다.
            logger.error("[seed] %s 실패(%s) — 시딩 중단", batch_id, row["error"])
            break
        if row["result_ids"]:
            logger.info("[seed] %s 완료 — 분석 %d건", batch_id, len(row["result_ids"]))
    else:
        logger.warning("[seed] 상한 %d배치 도달 — SEED_UNTIL 설정을 확인하세요.", MAX_SEED_BATCHES)

    cursor = store.get_cursor()
    logger.info(
        "[seed] 종료 — 배치 %d건 실행, 커서 %s. 화면1 '오늘'=%s, 버튼 대상=%s",
        ran, cursor, event_date_for(cursor), batch_runner.pending_range()[1],
    )
    return ran


def launch_if_configured() -> asyncio.Task | None:
    """SEED_UNTIL이 있으면 시딩을 **백그라운드로** 띄운다(기동을 막지 않는다).

    시딩은 배치마다 LLM을 부르므로 수 분이 걸린다. 기동을 붙잡으면 헬스체크가 실패하고
    프론트도 못 뜬다. 백그라운드로 돌리면 대기열이 실시간으로 채워지는 게 화면에 보인다.

    싱글턴(KGClient·MCPClient)은 **시딩이 켜져 있을 때만** 깨운다 — 여기서 미리 만들면
    시딩을 안 쓰는 환경(운영·CI)에서도 기동 때마다 MCP stdio 서브프로세스가 뜬다.
    """
    target = seed_target()
    if target is None:
        return None

    async def _run() -> None:
        try:
            from . import deps  # 지연 import — 시딩이 꺼져 있으면 싱글턴을 건드리지 않는다

            await catch_up_to(target, deps.kg_client(), deps.mcp_client())
        except asyncio.CancelledError:      # 서버 종료 — 다음 기동이 끊긴 지점부터 재개한다
            logger.info("[seed] 종료 신호로 시딩 중단 — 다음 기동에 이어서 돕니다.")
            raise
        except Exception:  # noqa: BLE001 — 시딩 실패가 서버를 죽이면 안 된다(수동 배치는 여전히 가능)
            logger.exception("[seed] 시딩 중 예외 — 서버는 계속 동작합니다.")

    return asyncio.create_task(_run())
