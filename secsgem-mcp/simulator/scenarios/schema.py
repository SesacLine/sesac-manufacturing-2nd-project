"""시나리오 설계 원칙 구현"""
from pydantic import BaseModel, Field
from typing import Literal

class SupportSignal(BaseModel):        # 지지 신호 (2개 이상 필수)
    kind: Literal["commonality", "sequence", "telemetry_drift", "alarm"]
    equipment_id: str | None = None
    param: str | None = None
    detail: str

class TrapSignal(BaseModel):           # 반대 신호/함정
    kind: Literal["normal_lot_passthrough", "post_defect_event"]
    equipment_id: str
    detail: str                        # 이 가설을 지목하면 오답

class Scenario(BaseModel):
    scenario_id: str
    defect_pattern: str                # KG 엔티티명 (정렬)
    lot_ids: list[str]
    root_cause: str | None             # None = 매칭불가 시나리오 (P7)
    support_signals: list[SupportSignal] = Field(min_length=2)
    trap_signals: list[TrapSignal] = Field(default_factory=list, min_length=1)
    distractor_count: int = 5          # 교란 신호
    is_unmatched: bool = False         # P7: 정답 = "판단 불가 + 확인 항목"
    is_mixed_cause: bool = False       # MixedWM38 전용

# 평가 전용 — 서버가 절대 읽지 않음 (datasets/ground_truth/ 로만 저장)
class GroundTruthCard(BaseModel):
    scenario_id: str
    true_root_causes: list[str]        # 멀티라벨이면 원인 집합
    key_evidence_path: list[str]       # 정답 증거 경로
    traps_to_reject: list[str]         # 기각되어야 할 함정 가설