"""⓪ 저수율 로트 선별. 결정적 함수, 모델 불필요.

wafer.die_map을 직접 집계해 저수율 로트를 뽑는다(fab.db는 read-only).
산출물_기능목록_유스케이스.md §1 참고.
"""

from __future__ import annotations

from ..state import RCAState


def select_low_yield_lots(state: RCAState) -> dict:
    """cursor_date 기준으로 완료된 로트 중 저수율 로트만 골라 target_lot_ids를 채운다.

    TODO: fab.db의 wafer.die_map을 lot_id별로 집계해 수율을 계산하고,
          임계값(고정값 or mean - k*std, 임계값 자체는 미확정 — jiun_work_0710.md 참고) 이하만 선별.
    """
    raise NotImplementedError
