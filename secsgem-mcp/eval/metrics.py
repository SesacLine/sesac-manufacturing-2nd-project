"""인스턴스 RCA 정확도 (top-1/top-3), 함정 기각률, 판단불가 적정성, 복합 원인 재현율, 툴 ablation, 시간 정합 오류율"""
import json, pathlib

def load_ground_truth(scenario_id):   # 평가 시점에만 ground_truth 접근
    return json.loads(pathlib.Path(
        f"datasets/ground_truth/{scenario_id}.json").read_text(encoding="utf-8"))

def rca_topk_accuracy(preds, k=1):
    hit = sum(gt_true_cause(p) in p["ranked_causes"][:k] for p in preds)
    return hit / len(preds)

def trap_rejection_rate(preds):
    """설계된 함정을 실제 기각한 비율"""
    traps = [p for p in preds if p["has_designed_trap"]]
    return sum(p["rejected_trap"] for p in traps) / len(traps)

def unmatched_appropriateness(preds):
    """매칭불가 시나리오의 '판단불가' 반환율 vs 정상 시나리오 오탐율"""
    unm = [p for p in preds if p["is_unmatched"]]
    nrm = [p for p in preds if not p["is_unmatched"]]
    return {
        "unknown_recall": sum(p["said_unknown"] for p in unm) / len(unm),
        "false_unknown_rate": sum(p["said_unknown"] for p in nrm) / len(nrm),
    }

def cause_discrimination(preds, mapping):
    """원인 변별력: 같은 결함 클래스 안에서 서로 다른 원인이 심어진
    시나리오들의 top-1 정확도를 '클래스→최빈 원인' 고정 응답 베이스라인과 비교.
    3클래스 체제의 지름길(암기) 방어가 작동했는지의 직접 검증."""
    def most_frequent(pattern):
        return max(mapping[pattern], key=lambda c: c["prob"])["cause"]
    agent = sum(p["ranked_causes"][:1] == [p["gt_cause"]] for p in preds) / len(preds)
    base = sum(most_frequent(p["pattern"]) == p["gt_cause"] for p in preds) / len(preds)
    return {"agent_top1": agent, "fixed_baseline_top1": base, "margin": agent - base}

# 실행 스크립트
# python -m eval.metrics  --pred eval/results.json --report eval/report.md