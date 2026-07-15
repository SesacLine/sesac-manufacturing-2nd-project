"""evidence table(가설 검증 테이블)
검증 패턴 임시 구현: KG 후보원인 → commonality → telemetry/alarm/maintenance → normal_ratio → evidence table
"""
def verify_hypothesis(defect_pattern, lot_ids, mcp):
    # 1) KG/문헌에서 후보 원인 공정 확보 (기존 GraphRAG 도구)
    candidates = kg_candidate_causes(defect_pattern)

    # 2) 공통 인스턴스 확인
    comm = mcp.run_commonality_analysis(lot_ids=lot_ids)

    evidence = []
    for cand in candidates:
        suspect = top_equipment_for(comm, cand["equipment_group"])
        # 3) 시점 일치 확인
        tele = mcp.query_telemetry(suspect, cand["time_range"], cand["params"])
        mnt  = mcp.get_maintenance_history(suspect, cand["time_range"])
        alm  = mcp.get_alarm_history(equipment_id=suspect, time_range=cand["time_range"])
        # 4) 반대 근거 — 약한 가설 기각
        neg  = mcp.get_normal_lot_ratio(equipment_id=suspect, time_range=cand["time_range"])

        evidence.append({                                       # 5) evidence table
            "hypothesis": cand["cause"],                        # 검증 대상 가설
            "support":   collect_support(comm, tele, mnt, alm), # 지지 근거
            "against":   neg,                                   # 반대 근거 (T4 negative envidence 결과 (예: 정상 lot 다수 통과 등))
            "unverified":collect_missing([tele, mnt, alm, neg]),# 미확인 (Tool 응답의 coverage.missing을 그대로 인용 (예: D-14 CH-B 압력 결측))
            "next_actions": suggest_next(cand, tele),           # 다음 확인 액션 (예: D-14 압력 데이터 확보 등))
        })
    return evidence