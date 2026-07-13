import numpy as np
import pandas as pd
from preprocess.label_ontology import to_kg_entity

def load_wm811k(pkl_path: str) -> pd.DataFrame:
    df = pd.read_pickle(pkl_path)          # 811,457행
    df["wafer_id"] = df["waferIndex"].astype("Int64").astype(str)  # int 캐스팅 (1~25)
    df["lot_id"] = df["lotName"].astype(str)
    df["source"] = "wm811k"

    # failureType은 numpy 배열([['none']])·빈 배열·문자열·결측 센티널(0/nan) 혼재 → 정규화
    def _lbl(v):
        if v is None:
            return ""
        a = np.asarray(v, dtype=object).ravel()
        if not a.size:
            return ""
        s = str(a[0])
        return "" if s in ("0", "0.0", "nan", "None") else s   # 결측 표기 → 미라벨
    df["raw_label"] = df["failureType"].map(_lbl)

    df["has_label"] = df["raw_label"] != ""                # ~172,950행
    df["is_background"] = ~df["has_label"]                 # 라벨 미확인 = 배경 물량
    df["kg_label"] = df["raw_label"].where(df["has_label"]).map(
        lambda v: to_kg_entity(v) if isinstance(v, str) and v else None)  # NaN(truthy) 방어
    df["is_normal"] = df["kg_label"] == "Normal"           # P3 정상 모수 기본
    return df[["source", "lot_id", "wafer_id", "waferMap",
               "dieSize", "kg_label", "has_label", "is_background", "is_normal"]]