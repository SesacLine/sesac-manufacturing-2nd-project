"""루브릭 기반 VLM 평가 모듈 (dev 전용)

흐름:
    generate.py  VLM output(표본 5건/패턴) → 변환 LLM → 인스턴스 루브릭 rubrics/raw/*.json
    merge.py     인스턴스 루브릭 N건 → 패턴 고정 루브릭 rubrics/{pattern}.json
    evaluate.py  eval 풀 VLM output → score.py(결정적) + judge.py(LLM-as-Judge) → reports/

모듈:
    schema     루브릭 스키마 / 정규화 / 검증
    prompts    변환 프롬프트 / 판정 프롬프트
    sampling   Training split의 rubric/eval 풀 불교차 분할
    score      결정적 채점(구 단위 매칭, hit 우선 마스킹) + BLEU/ROUGE-L 보조
    judge      LLM-as-Judge (plain | rubric)
"""
