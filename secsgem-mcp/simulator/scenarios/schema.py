"""SECS/GEM 시뮬레이터가 생성하는 시나리오의 데이터 구조를 Pydantic으로 강제하는 스키마"""
from pydantic import BaseModel, Field
from typing import Literal, Optional

class SupportSignal(BaseModel):        # 가설 지지 신호 (2개 이상 필수) (신호: commonality 통계, 공정 순서, 텔레메트리 드리프트, 알람)
    kind: Literal["commonality", "sequence", "telemetry_drift", "alarm"]
    equipment_id: Optional[str] = None
    param: Optional[str] = None
    detail: str

class TrapSignal(BaseModel):           # 가설 반대 신호/함정 (정상 lot도 해당 장비를 통과하는 경우, 불량 발생 이후의 이벤트라 인과 성립 안 되는 경우)
    kind: Literal["normal_lot_passthrough", "post_defect_event"]
    equipment_id: str
    detail: str                        # 이 가설을 지목하면 오답

class Scenario(BaseModel):
    scenario_id: str
    defect_pattern: str                # KG 엔티티명 (label_ontology.py 참조)
    lot_ids: list[str]
    root_cause: Optional[str]          # None = 매칭불가 시나리오
    support_signals: list[SupportSignal] = Field(min_length=2)
    trap_signals: list[TrapSignal] = Field(default_factory=list, min_length=1)
    distractor_count: int = 5          # 정답과 무관한 교란 신호 개수
    is_unmatched: bool = False         # 정답 = "판단 불가 + 확인 항목" (정상이 없는 문항 유형)

# 평가 전용 — 서버가 절대 읽지 않음 (datasets/ground_truth/ 로만 저장) (Critic 전용 루브릭)
class GroundTruthCard(BaseModel):
    scenario_id: str
    true_root_causes: list[str]        # 멀티라벨이면 원인 집합
    key_evidence_path: list[str]       # 정답 증거 경로
    traps_to_reject: list[str]         # 기각되어야 할 함정 가설