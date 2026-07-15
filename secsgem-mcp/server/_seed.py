import hashlib

import numpy as np

GLOBAL_SEED = 20260101

def rng(*salt: str | int) -> np.random.Generator:
    """salt로 파생 시드를 만듦. 같은 salt → 같은 스트림 (재현 보장)"""
    key = f"{GLOBAL_SEED}|" + "|".join(map(str, salt))
    h = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "little")
    return np.random.default_rng(h)
