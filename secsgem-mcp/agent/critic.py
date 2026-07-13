"""
시간 정합: 원인 이벤트가 불량 lot 처리보다 앞서는가 (get_lot_timeline 재확인)
negative evidence 처리 여부: 정상 lot 대조 수행·모순 없는가
"""
def critique(adopted_hypothesis, mcp):
    tl = mcp.get_lot_timeline(adopted_hypothesis["representative_lot"])
    # 시간 정합: 원인 이벤트 ts < 불량 처리 ts
    if not cause_precedes_defect(adopted_hypothesis, tl):
        return reject("시간 선후 뒤집힘")
    # negative evidence 처리 확인 (P3)
    if adopted_hypothesis.get("against") is None:
        return reject("정상 lot 대조 미수행 (P3)")
    # 미확인 데이터를 확인한 듯 서술 → faithfulness 실패 (가드레일)
    if cites_missing_as_fact(adopted_hypothesis):
        return reject("coverage.missing 항목을 사실처럼 인용")
    # 메커니즘 연결(KG) 없이 상관→인과 서술 금지
    if not has_kg_mechanism_link(adopted_hypothesis):
        return replan("KG 기반 메커니즘 연결 문장 부재 (P5)")
    return accept()