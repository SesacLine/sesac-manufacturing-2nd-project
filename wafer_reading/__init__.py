"""웨이퍼맵 판독 컴포넌트 패키지

모듈 구성:
    - stacking: 누적 히트맵 스태킹 (런타임 및 dev 공통)
    - classifier: ResNet 기반 판독 (학습=dev, 추론=런타임)
    - vlm: VLM 어댑터 open/pty (런타임)
    - rubric_gen: 루브릭 생성 (dev 전용, 평가 프레임워크용)
"""
