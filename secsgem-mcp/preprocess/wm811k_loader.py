import numpy as np
import pandas as pd
from preprocess.label_ontology import to_kg_entity, scope_of

def load_wm811k(pkl_path: str, labeled_split: str | None = "Test") -> pd.DataFrame:
    """WM-811K 로드
    - labeled_split이 주어지면 라벨 있는 웨이퍼를 해당 trainTestLabel split로 제한
    - CNN 판독 모델이 Training split로 학습되므로, fab.db에 Training 웨이퍼가 섞이면 학습-평가 누출이 생김
    - 무라벨 배경 웨이퍼(trainTestLabel='0')는 split 개념이 없어 유지됨
    - None을 주면 종전처럼 전체 사용(구버전 재현용으로 살려둠)
    """
    df = pd.read_pickle(pkl_path)          # 811,457행
    df["wafer_id"] = df["waferIndex"].astype("Int64").astype(str)  # int 캐스팅 (1~25)  
    df["lot_id"] = df["lotName"].astype(str)
    df["source"] = "wm811k"

    def _lbl(v):
        if v is None:
            return ""
        a = np.asarray(v, dtype=object).ravel()
        if not a.size:
            return ""
        s = str(a[0])
        return "" if s in ("0", "0.0", "nan", "None") else s   # 결측 표기 -> 미라벨
    df["raw_label"] = df["failureType"].map(_lbl)

    df["has_label"] = df["raw_label"] != ""                # ~172,950행
    df["is_background"] = ~df["has_label"]                 # 라벨 미확인 = 배경 물량

    if labeled_split is not None:
        df["train_test"] = df["trainTestLabel"].map(_lbl)  # 'Training'|'Test'|''(무라벨)
        df = df[~df["has_label"] | (df["train_test"] == labeled_split)]

    df["kg_label"] = df["raw_label"].where(df["has_label"]).map(
        lambda v: to_kg_entity(v) if isinstance(v, str) and v else None)  # NaN(truthy) 방어
    df["is_normal"] = df["kg_label"] == "Normal"           # 정상 모수 기본
    df["scope"] = df["kg_label"].map(lambda v: scope_of(v if isinstance(v, str) else None))
    return df[["source", "lot_id", "wafer_id", "waferMap",
               "dieSize", "kg_label", "has_label", "is_background", "is_normal", "scope"]]