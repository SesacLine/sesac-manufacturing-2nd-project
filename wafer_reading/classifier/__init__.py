"""ResNet 기반 웨이퍼맵 개별 이미지 결함 패턴 판독 모듈

런타임 프로세스상 위치:
저수율 로트 선별 → !!ResNet 개별 판독!! → grouper → stacking → VLM → KG

- data.py:  WM-811K 로더 — trainTestLabel 기준 Training 내 9:1 split, fab.db 등재 웨이퍼
            제외(임시 누출 차단 규칙), 5클래스 리매핑
- train.py: ResNet-18 학습 (가중 샘플링 + flip/90°회전 증강)
- infer.py: 체크포인트 로드 → 웨이퍼맵 1장 → {pattern, confidence}
"""

CLASSES = ["Center", "Edge-Ring", "Scratch", "Unknown", "Normal"]
