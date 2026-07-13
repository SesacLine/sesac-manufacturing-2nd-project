"""인스턴스 RCA 정확도 (top-1/top-3), 함정 기각률, 판단불가 적정성, 복합 원인 재현율, 툴 ablation, 시간 정합 오류율"""
import json, pathlib

def load_ground_truth(scenario_id):   # 평가 시점에만 ground_truth 접근
    return json.loads(pathlib.Path(
        f"datasets/ground_truth/{scenario_id}.json").read_text())

def rca_topk_accuracy(preds, k=1):
    hit = sum(gt_true_cause(p) in p["ranked_causes"][:k] for p in preds)
    return hit / len(preds)

def trap_rejection_rate(preds):
    """설계된 함정을 실제 기각한 비율 (§4.4-2, P3)."""
    traps = [p for p in preds if p["has_designed_trap"]]
    return sum(p["rejected_trap"] for p in traps) / len(traps)

def unmatched_appropriateness(preds):
    """매칭불가 시나리오의 '판단불가' 반환율 vs 정상 시나리오 오탐율 (P7)."""
    unm = [p for p in preds if p["is_unmatched"]]
    nrm = [p for p in preds if not p["is_unmatched"]]
    return {
        "unknown_recall": sum(p["said_unknown"] for p in unm) / len(unm),
        "false_unknown_rate": sum(p["said_unknown"] for p in nrm) / len(nrm),
    }

def mixed_cause_recall(preds):
    """MW38: 주입 원인 집합 대비 발견 원인 재현율/정밀도 (§4.4-6, one-hot 정답지)."""
    out = []
    for p in preds:
        gt, found = set(p["gt_causes"]), set(p["found_causes"])
        rec = len(gt & found) / len(gt) if gt else 0
        prec = len(gt & found) / len(found) if found else 0
        out.append({"recall": rec, "precision": prec})
    return out