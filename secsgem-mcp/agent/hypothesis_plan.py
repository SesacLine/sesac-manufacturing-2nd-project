"""P8 - evidence table
검증 패턴 임시 구현: KG 후보원인 → commonality → telemetry/alarm/maintenance → normal_ratio → evidence table
"""
def verify_hypothesis(defect_pattern, lot_ids, mcp):
    # 1) KG/문헌에서 후보 원인 공정 확보 (기존 GraphRAG 도구)
    candidates = kg_candidate_causes(defect_pattern)          # 기획안 범위

    # 2) 공통 인스턴스 확인 (P1)
    comm = mcp.run_commonality_analysis(lot_ids=lot_ids)

    evidence = []
    for cand in candidates:
        suspect = top_equipment_for(comm, cand["equipment_group"])
        # 3) 시점 일치 확인 (P2)
        tele = mcp.query_telemetry(suspect, cand["time_range"], cand["params"])
        mnt  = mcp.get_maintenance_history(suspect, cand["time_range"])
        alm  = mcp.get_alarm_history(equipment_id=suspect, time_range=cand["time_range"])
        # 4) 반대 근거 (P3) — 약한 가설 기각
        neg  = mcp.get_normal_lot_ratio(equipment_id=suspect, time_range=cand["time_range"])

        evidence.append({                                     # 5) evidence table (P8)
            "hypothesis": cand["cause"],
            "support":   collect_support(comm, tele, mnt, alm),
            "against":   neg,                 # 정상 lot 多 → 기각 신호
            "unverified":collect_missing([tele, mnt, alm, neg]),  # coverage.missing 인용
            "next_actions": suggest_next(cand, tele),
        })
    return evidence