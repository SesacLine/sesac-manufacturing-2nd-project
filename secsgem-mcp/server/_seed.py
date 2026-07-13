import hashlib

import numpy as np

GLOBAL_SEED = 20260101

def rng(*salt: str | int) -> np.random.Generator:
    """salt로 파생 시드를 만든다. 같은 salt → 같은 스트림 (재현 보장).

    내장 hash()는 문자열에 프로세스별 무작위 솔트가 붙어(PYTHONHASHSEED)
    실행마다 값이 달라진다 → hashlib으로 프로세스 간 안정 해시를 쓴다.
    """
    key = f"{GLOBAL_SEED}|" + "|".join(map(str, salt))
    h = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "little")
    return np.random.default_rng(h)
