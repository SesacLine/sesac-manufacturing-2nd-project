"""④ Hypothesis 노드. 결정적 함수(룰베이스), LLM 미사용 — 2026-07-09 노드화 결정.

kg_rca가 이미 순회해 둔 candidate마다, candidate.tier가 어떤 MCP 도구를 부를지 결정한다.
candidate.cause/failure_mode 문자열은 fab.db와 join key가 아니다 — 실제 join은
candidate.evidence(Parameter/Maintenance/Recipe id)로만 이루어진다
(personalspace/0711 work/qna_0711.md Q5).

호출 규칙(모두 personalspace/0708 work/산출물_데이터모델설계.md §3.0/3.1 정본):
    - 모든 candidate 공통: run_commonality_analysis, get_normal_lot_ratio
    - tier == "자동"    (evidence_label == "Parameter") : + query_telemetry, 즉시 채택/기각까지
    - tier == "반자동"  (evidence_label == "Maintenance"): + get_maintenance_history, 사람 판정 필요
    - tier == "반자동"  (evidence_label == "Recipe")     : + get_lot_history(recipe_id 비교), 사람 판정 필요
    - tier == "근거없음"                                  : MCP 호출 없음

주의: mapping_table.yaml(fab.db 시나리오 근거)과 kg_rca cause 어휘가 대부분 안 겹친다.
"자동" candidate라도 fab.db에 실제로 주입된 신호가 없으면 "증거 없음"이 정상 결과다 —
personalspace/0711 work/kg_mapping_vocabulary.md 참고.
"""

from __future__ import annotations

from ..mcp_client import MCPClient
from ..state import EvidenceEntry, GraphRAGCandidate, Hypothesis, RCAState
from langgraph.prebuilt import create_react_agent    # 또는 수동 루프(LangGraph_fs.md 7.2)

# --- 0713 Walking Skeleton: 팀 결정 3가지를 전부 "가장 단순한 선택"으로 하드코딩했다.
# 나중에 팀원과 다시 짤 때 이 세 지점부터 보면 된다(personalspace/0713 work/skeleton_kickoff.md §5).
#
# 결정① MCP 호출 단위 — 처음엔 가설 단위(candidate마다 매번 새로 호출)로 짰다가, 실제로
#        돌려보니 Center 244건 기준 타임아웃이 나서(§5에서 우려했던 게 실측으로 확인됨),
#        같은 (step, evidence_label, evidence)는 결과를 재사용하는 캐싱만 최소로 넣었다
#        (아래 verify_cache). "검증 단위로 제대로 설계"까지는 아니고 응급 처치 수준 —
#        팀원과 다시 짤 때는 여기부터 손보는 게 좋다.
# 결정② route="direct"(step=null) 후보 — 그냥 step=None으로 commonality를 불러서
#        전체 공정 뭉뚱그린 결과를 그대로 쓴다(신호가 흐려지는 걸 감수).
# 결정③ direction=null인 [자동] 후보 — 방향 상관없이 정상범위 이탈이면 drift_detected=True.
#        (사실 모든 [자동] 후보에 이 규칙을 통일 적용한다 — candidate.direction 자체를 안 본다)


async def build_hypotheses(state: RCAState, group_id: str, mcp: MCPClient) -> dict:
    """group_id의 graphrag_candidates 각각에 증거를 모아 hypotheses[group_id]를 채운다."""
    group = next((g for g in state["groups"] if g["group_id"] == group_id), None)
    if group is None:
        return {"hypotheses": {group_id: []}}
    lot_ids = group["lot_ids"]

    graphrag_result = state["graphrag_candidates"].get(group_id)
    candidates = graphrag_result["candidates"] if graphrag_result else []
    if not candidates:
        return {"hypotheses": {group_id: []}}

    time_range = await _group_time_range(lot_ids, mcp)
    defect_ts = await _group_defect_ts(lot_ids, mcp)

    # cause는 서로 달라도 (step, evidence_label, evidence)가 같으면 MCP에 던지는 질문이
    # 완전히 동일하다 — 결정①.
    verify_cache: dict[tuple, tuple] = {}

    hypotheses: list[Hypothesis] = []
    for candidate in candidates:
        key = (candidate["step"], candidate["evidence_label"], candidate["evidence"])
        if key not in verify_cache:
            verify_cache[key] = await _verify_unit(candidate, lot_ids, mcp, time_range)
        suspect, evidence = verify_cache[key]
        evidence = dict(evidence)          
        evidence["defect_ts"] = defect_ts

        hypotheses.append(
            {
                "cause": candidate["cause"],
                "tier": candidate["tier"],
                "stage": candidate["step"],
                "equipment": suspect,
                "evidence": evidence,
                "citations": candidate.get("citations", []),
                "sentence": candidate["sentence"],
            }
        )

    return {"hypotheses": {group_id: hypotheses}}


async def verify_one(candidate, suspect, time_range, tools, model) -> dict:
    agent = create_react_agent(model, tools)
    prompt = _build_prompt(candidate, suspect, time_range)     # 고정키 주입 + 소프트힌트
    result = await agent.ainvoke({"messages": [("user",prompt)]})
    return _to_hypothesis(candidate, result)

async def _verify_unit(
    candidate: GraphRAGCandidate, lot_ids: list[str], mcp: MCPClient, time_range: tuple[str, str]
) -> tuple[str | None, EvidenceEntry]:
    """검증단위(step, evidence_label, evidence) 하나당 MCP 호출 묶음을 한 번만 실행한다."""
    evidence = _empty_evidence()

    comm = await mcp.run_commonality_analysis(lot_ids, step=candidate["step"])  # 결정②
    suspect = _top_equipment(comm)
    evidence["commonality_rows"] = _commonality_rows(comm)  # §2.7 리치 보존
    if suspect is None:
        return suspect, evidence

    evidence["commonality_ratio"] = _ratio_for(comm, suspect)
    neg = await mcp.get_normal_lot_ratio(equipment_id=suspect)
    evidence["normal_ratio"] = neg["data"].get("normal_ratio")
    evidence.update(await _verify_candidate(candidate, suspect, mcp, time_range))
    return suspect, evidence


async def _verify_candidate(
    candidate: GraphRAGCandidate, suspect_equipment: str, mcp: MCPClient, time_range: tuple[str, str]
) -> dict:
    """candidate.tier에 따라 정해진 MCP 도구만 호출해 EvidenceEntry의 tier별 필드를 채운다."""
    if candidate["tier"] == "근거없음":
        return {}

    if candidate["tier"] == "자동":  # Parameter
        telemetry = await mcp.query_telemetry(
            suspect_equipment, time_range, params=[candidate["evidence"]]
        )
        series = telemetry["data"]["series"]
        normal_range = telemetry["data"]["normal_ranges"].get(candidate["evidence"])
        return {
            "drift_detected": _detect_drift(series, normal_range),  # 결정③: direction 무시
            "telemetry_summary": f"{candidate['evidence']} {len(series)}개 포인트, 정상범위 {normal_range}",
            # §2.7 리치 보존 — 근거 모달 telemetry 섹션이 그대로 소비
            "telemetry_collected": True,
            "telemetry_param": candidate["evidence"],
            "telemetry_series": [
                {"ts": p.get("ts"), "value": p.get("value")} for p in series
            ],
            "telemetry_normal_range": list(normal_range) if normal_range else None,
        }

    if candidate["evidence_label"] == "Maintenance":
        maint = await mcp.get_maintenance_history(suspect_equipment, time_range)
        rows = maint["data"]
        result: dict = {
            "maintenance_hit": len(rows) > 0,
            # §2.7 리치 보존 — events 섹션 rows (알람은 파이프라인 미연동이라 maintenance만)
            "events_collected": True,
            "events_rows": [
                {
                    "ts": r["ts"],
                    "type": "maintenance",
                    "equipment_id": r.get("equipment_id", suspect_equipment),
                    "kind": r.get("type"),
                    "detail": r.get("parts", ""),
                }
                for r in rows
            ],
        }
        if rows:
            result["maintenance_ts"] = rows[0]["ts"]
            result["maintenance_summary"] = f"{rows[0]['type']} — {rows[0]['parts']}"
        return result

    if candidate["evidence_label"] == "Recipe":
        # 기대 레시피가 KG에 없어 비교 불가(docs/KG_schema_v1.3.md에 명시된 한계) — 조회는 스킵,
        # recipe_match=None으로 "판정은 사람 몫"임을 그대로 남긴다.
        return {"recipe_match": None}

    return {}


def _empty_evidence() -> EvidenceEntry:
    return {
        "commonality_ratio": None,
        "drift_detected": None,
        "maintenance_hit": None,
        "maintenance_ts": None,
        "defect_ts": None,
        "recipe_match": None,
        "alarm_hit": None,
        "normal_ratio": None,
    }


def _top_equipment(commonality: dict) -> str | None:
    stats = commonality["data"]["commonality"]["equipment_id"]
    return stats[0]["value"] if stats else None


def _commonality_rows(commonality: dict) -> list[dict]:
    """commonality 전체 테이블을 §2.7 rows 형태로 보존한다.

    chamber_id는 null 고정 — MCP 집계가 장비/챔버를 별개 카운터로 내서 장비별 챔버를
    특정할 수 없다(BACKEND_DECISIONS.md D5). suspect의 챔버도 같은 이유로 null이다.
    """
    data = commonality["data"]
    n_lots = data.get("n_lots", 0)
    return [
        {
            "equipment_id": s["value"],
            "chamber_id": None,
            "matched_lots": s["lot_count"],
            "total_lots": n_lots,
            "ratio": s["ratio"],
            "note": None,
        }
        for s in data["commonality"]["equipment_id"]
    ]


def _ratio_for(commonality: dict, equipment_id: str) -> float | None:
    stats = commonality["data"]["commonality"]["equipment_id"]
    return next((s["ratio"] for s in stats if s["value"] == equipment_id), None)


def _detect_drift(series: list[dict], normal_range: list[float] | None) -> bool | None:
    if not series or not normal_range:
        return None
    lo, hi = normal_range
    return any(not (lo <= point["value"] <= hi) for point in series)


async def _group_time_range(lot_ids: list[str], mcp: MCPClient) -> tuple[str, str]:
    """그룹 대표(첫 로트)의 공정 진행 구간을 검증 시간창으로 쓴다."""
    history = await mcp.get_lot_history(lot_ids[0])
    rows = history["data"]
    if not rows:
        return ("2026-01-01 00:00:00", "2026-12-31 00:00:00")
    return (min(r["ts_in"] for r in rows), max(r["ts_out"] for r in rows))

async def _group_defect_ts(lot_ids: list[str], mcp: MCPClient) -> str | None:
    """그룹 대표(첫 로트)의 결함 확정(EDS) 시각. Critic 시간정합의 비교 기준 — ④가 수집(firewall)."""
    timeline = await mcp.get_lot_timeline(lot_ids[0])
    eds_events = [e for e in timeline["data"] if e["detail"] == "EDS"]
    return max(e["ts"] for e in eds_events) if eds_events else None