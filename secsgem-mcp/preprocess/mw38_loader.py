import numpy as np
from preprocess.label_ontology import onehot_to_kg
from server._seed import rng

def load_mw38(npz_path: str, wafers_per_vlot=(20, 25)) -> list[dict]:
    d = np.load(npz_path)
    maps, labels = d["arr_0"], d["arr_1"]   # (N,52,52), (N,8)
    n = len(maps)

    # 결정적 VLOT 그룹핑: index 순서를 시드로 셔플 후 20~25장씩 묶음
    r = rng("mw38", "vlot")
    order = r.permutation(n)
    records, i, seq = [], 0, 0
    while i < n:
        size = int(r.integers(wafers_per_vlot[0], wafers_per_vlot[1] + 1))
        group, seq = order[i:i + size], seq + 1
        vlot = f"VLOT-{seq:04d}"
        for idx in group:
            records.append({
                "source": "mw38",
                "lot_id": vlot,
                "wafer_id": f"MW38-{int(idx):05d}",
                "waferMap": maps[idx],
                "dieSize": None,                       # WM-811K만 보유
                "kg_labels": onehot_to_kg(labels[idx]),  # 멀티라벨 (혼합 원인 정답지)
                "onehot": labels[idx].tolist(),
                "has_label": True,
                "is_normal": bool(labels[idx].sum() == 0),
            })
        i += size
    return records