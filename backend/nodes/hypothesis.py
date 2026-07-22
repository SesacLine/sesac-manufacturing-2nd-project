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
from langchain_core.messages import ToolMessage
from ..mcp_client.client import _as_dict   # 도구 반환 정규화 헬퍼 재사용
import os
from langchain_openai import ChatOpenAI

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
# verify_one: 자동(Parameter) tier 후보를 에이전트(create_react_agent)로 검증한다.
#   시그니처: verify_one(candidate, suspect, base_evidence, time_range, tools, model) -> Hypothesis
#   base_evidence = Layer1 pre-pass(commonality/normal_ratio) 결과 — 에이전트는 그 위에 tier별 증거만 얹는다.
#   evidence는 LLM이 아니라 도구 반환(ToolMessage)에서 재구성한다(옵션 A). 반자동·근거없음은 결정론 경로 유지.


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

# 슬라이스1: 자동 후보 1개만 에이전트로 (경로 증명). 나머지는 결정론.
    agent_target = next((c for c in candidates if c["tier"] == "자동"), None)
    tools = model = None

    # 같은 (step, evidence_label, evidence)는 결과 재사용 — 결정①.
    verify_cache: dict[tuple, tuple] = {}
    hypotheses: list[Hypothesis] = []
    for candidate in candidates:
        if candidate is agent_target:                          # ── 에이전트 경로
            if tools is None:
                tools = await mcp.get_agent_tools()            # 그룹당 1회
                model = _make_model()
            suspect, base_evidence = await _prepass(candidate, lot_ids, mcp)
            if suspect is None:                                # 조사할 장비 없음 → 미조사
                base_evidence["defect_ts"] = defect_ts
                hypotheses.append(_det_hypothesis(candidate, suspect, base_evidence, investigated=False))
                continue
            hyp = await verify_one(candidate, suspect, base_evidence, time_range, tools, model)
            hyp["evidence"]["defect_ts"] = defect_ts
            hypotheses.append(hyp)                             # verify_one이 investigated=True 세팅
        else:                                                  # ── 결정론 경로
            key = (candidate["step"], candidate["evidence_label"], candidate["evidence"])
            if key not in verify_cache:
                verify_cache[key] = await _verify_unit(candidate, lot_ids, mcp, time_range)
            suspect, evidence = verify_cache[key]
            evidence = dict(evidence)
            evidence["defect_ts"] = defect_ts
            hypotheses.append(_det_hypothesis(candidate, suspect, evidence, investigated=False))

    return {"hypotheses": {group_id: hypotheses}}


def _make_model():
      return ChatOpenAI(model=os.environ["OPENAI_MODEL"], temperature=0)   # temp=0 = 재현성(§8-7)


def _det_hypothesis(candidate, suspect, evidence, investigated: bool) -> Hypothesis:
    return {
        "cause": candidate["cause"],
        "tier": candidate["tier"],
        "stage": candidate["step"],
        "equipment": suspect,
        "evidence": evidence,
        "citations": candidate.get("citations", []),
        "sentence": candidate["sentence"],
        "investigated": investigated,
    }


async def verify_one(candidate, suspect, base_evidence, time_range, tools, model) -> dict:
    agent = create_react_agent(model, tools)
    prompt = _build_prompt(candidate, suspect, time_range)     # 고정키 주입 + 소프트힌트
    result = await agent.ainvoke({"messages": [("user",prompt)]})
    return _to_hypothesis(candidate, result, suspect, base_evidence)


async def investigate_group(
    candidates: list[GraphRAGCandidate], lot_ids: list[str], mcp: MCPClient,
    time_range: tuple[str, str], tools, model,
) -> list[Hypothesis]:
    """그룹 조사관 본체 (S2-2): 자동 tier 후보 전부를 step 배치로 조사한다.

    step별로 묶어 pre-pass(공통조회) 1회 → suspect 확정 → 에이전트 1루프가
    query_telemetry 1콜(params 전부) → _to_hypotheses_batch로 후보별 분배.
    suspect가 없으면(공통 장비 특정 불가) 그 배치는 결정론 폴백(investigated=False).
    루프 상한/중단 기준은 S2-5에서 — 지금은 step 배치 순회 1패스.
    """
    hypotheses: list[Hypothesis] = []
    by_step: dict = {}
    for c in candidates:
        by_step.setdefault(c["step"], []).append(c)   # step=None(결정②)도 자기들끼리 한 배치

    for step, batch in by_step.items():
        suspect, base_evidence = await _prepass(batch[0], lot_ids, mcp)  # step 공통 → 대표 1개로 1회
        if suspect is None:                    # 조사할 장비 없음 → 배치 전체 미조사 폴백
            hypotheses.extend(
                _det_hypothesis(c, suspect, dict(base_evidence), investigated=False) for c in batch
            )
            continue
        params = list(dict.fromkeys(c["evidence"] for c in batch))   # 중복 제거 + 순서 보존
        agent = create_react_agent(model, tools)
        prompt = _build_group_prompt(batch, suspect, params, time_range)
        result = await agent.ainvoke({"messages": [("user", prompt)]})
        hypotheses.extend(_to_hypotheses_batch(batch, result, suspect, base_evidence))
    return hypotheses


def _build_prompt(candidate: GraphRAGCandidate, suspect: str, time_range: tuple[str, str]) -> str:
    return f"""너는 웨이퍼 결함의 원인 가설을 fab 운영데이터로 검증하는 에이전트다.

[검증 대상 — 아래 값은 확정된 사실이다. 바꾸거나 지어내지 마라]
- 의심 원인(cause): {candidate['cause']}
- 의심 장비(equipment_id): {suspect}
- 확인할 신호(evidence): {candidate['evidence']}
- 공정 단계(step): {candidate['step']}
- 조회 테이블(fab_table): {candidate['fab_table']}
- 예상 방향(direction): {candidate.get('direction')}
- 검증 시간창(time_range): {time_range[0]} ~ {time_range[1]}
- KG 문헌 근거: {candidate['sentence']}

[참고 힌트 — 조사 방향 참고용, 절대 사실로 인용하지 마라]
- 검증등급(tier): {candidate['tier']}  (자동 = query_telemetry로 센서 시계열 확인)
- 시나리오 힌트: {candidate.get('scenario_hint')}

[규칙]
- 도구 인자로는 위의 equipment_id / evidence / time_range 만 사용하라.
- 인용하는 수치는 반드시 도구가 반환한 값이어야 한다. 값을 추정하거나 지어내지 마라.
- 조회 결과 데이터가 없으면 "없음"으로 보고하라. 없는 것을 있는 것처럼 말하지 마라.
- 검증에 필요한 도구를 호출한 뒤, 무엇을 확인했고 이 원인 가설을
뒷받침하는지/반박하는지 한 문단으로 정리하라.
"""

def _build_group_prompt(
    candidates: list[GraphRAGCandidate], suspect: str, params: list[str], time_range: tuple[str, str]
) -> str:
    """배치 조사 프롬프트 — 후보 N개(같은 step·suspect)를 한 루프로 (S2-2, _build_prompt의 그룹판).

    B층 고정키(suspect/params/time_range/후보 목록)는 코드가 주입 — 날조 금지.
    max_points 상향은 downsample 함정 대응: 서버(telemetry.py)의 균일 다운샘플이
    param 섞인 리스트 전체에 걸리므로, 배치에선 500×param수로 올려 특정 param이
    샘플에서 통째로 빠지는 것을 막는다.
    후보별 KG sentence는 프롬프트 폭발 방지로 뺐다(옵션 A라 evidence 무영향, 서사 재료만 축소).
    """
    cause_lines = "\n".join(
        f"  - {c['cause']}: 확인할 신호={c['evidence']}, 예상 방향={c.get('direction')}"
        for c in candidates
    )
    max_points = 500 * len(params)
    return f"""너는 웨이퍼 결함의 원인 가설들을 fab 운영데이터로 검증하는 에이전트다.

[검증 대상 — 아래 값은 확정된 사실이다. 바꾸거나 지어내지 마라]
- 의심 장비(equipment_id): {suspect}
- 공정 단계(step): {candidates[0]['step']}
- 검증 시간창(time_range): {time_range[0]} ~ {time_range[1]}
- 조사할 원인 가설 목록 (신호=telemetry param):
{cause_lines}

[도구 호출 규칙]
- query_telemetry는 반드시 **한 번만** 호출하라: params={params!r} 전부를 한 리스트에 담고,
  max_points={max_points}로 호출한다. param마다 따로 부르지 마라.
- 도구 인자로는 위의 equipment_id / params / time_range / max_points 만 사용하라.

[보고 규칙]
- 인용하는 수치는 반드시 도구가 반환한 값이어야 한다. 값을 추정하거나 지어내지 마라.
- 조회 결과 데이터가 없는 param은 "없음"으로 보고하라. 없는 것을 있는 것처럼 말하지 마라.
- 호출을 마친 뒤, param별로 무엇을 확인했고 어느 가설을 뒷받침하는지/반박하는지
  한 문단으로 정리하라.
"""


def _to_hypothesis(candidate, result, suspect, base_evidence) -> Hypothesis:
    """단일 후보 재구성 — 배치(_to_hypotheses_batch)의 1개짜리 특수형 (S2-2에서 위임화)."""
    return _to_hypotheses_batch([candidate], result, suspect, base_evidence)[0]


def _to_hypotheses_batch(candidates, result, suspect, base_evidence) -> list[Hypothesis]:
    """배치 에이전트 결과(result["messages"])에서 후보 N개의 Hypothesis를 재구성한다 (옵션 A).

    query_telemetry 응답(들)을 param별로 갈라(_series_by_param) 각 후보의
    param(candidate["evidence"]) 조각으로만 판정한다. 숫자는 전부 도구 반환에서
    결정론으로 — LLM 서사는 rationale뿐 (옵션 A).

    - "조회됐는가"의 기준은 normal_ranges 키: 서버가 요청 params 전부에 엔트리를
    만들어 주므로(telemetry.py), param이 거기 있으면 series가 비어도
    "조회했고 데이터 없음"(정상 결과)으로 기록한다.
    - rationale(조사 서사)은 배치 1루프 공유 — 후보별 분담은 §5 미결(rationale 분담).
    """
    by_param: dict[str, list[dict]] = {}
    normal_ranges: dict = {}
    for m in result["messages"]:
        if not isinstance(m, ToolMessage) or m.name != "query_telemetry":
            continue
        data = _as_dict(m.content).get("data", {})
        by_param.update(_series_by_param(data.get("series", [])))   # 재호출 시 같은 param은 뒤가 이김
        normal_ranges.update(data.get("normal_ranges", {}))

    rationale = result["messages"][-1].content    # 마지막 AIMessage = 그룹 조사 서사

    hypotheses: list[Hypothesis] = []
    for candidate in candidates:
        param = candidate["evidence"]
        evidence = dict(base_evidence)            # 후보마다 독립 사본 (pre-pass 값 이어받기)
        if param in normal_ranges:                # 조회된 param만 telemetry 필드 기록
            series = by_param.get(param, [])
            normal_range = normal_ranges[param]
            direction = _drift_direction(series, normal_range)
            evidence["drift_detected"] = _detect_drift(series, normal_range)
            evidence["drift_direction"] = direction
            evidence["direction_match"] = _direction_match(direction, candidate.get("direction"))
            # §2.7 리치 보존 — 결정론 경로(_verify_candidate)와 동일 필드로 맞춤
            evidence["telemetry_collected"] = True
            evidence["telemetry_param"] = param
            evidence["telemetry_series"] = [{"ts": p.get("ts"), "value": p.get("value")} for p in series]
            evidence["telemetry_normal_range"] = list(normal_range) if normal_range else None
            evidence["telemetry_summary"] = f"{param} {len(series)}개 포인트, 정상범위 {normal_range}"
        hypotheses.append({
            "cause": candidate["cause"],
            "tier": candidate["tier"],
            "stage": candidate["step"],
            "equipment": suspect,
            "evidence": evidence,
            "citations": candidate.get("citations", []),
            "sentence": candidate["sentence"],
            "rationale": rationale,
            "investigated": param in normal_ranges,   # 실제 조회된 param만 True — 미조회는 ⑤ judge_unknown 재료(§3-3 C3)
        })
    return hypotheses


async def _prepass(candidate, lot_ids, mcp):
    """Layer1 결정론 공통조회: commonality→suspect + normal_ratio → (suspect, base_evidence)."""
    evidence = _empty_evidence()
    comm = await mcp.run_commonality_analysis(lot_ids, step=candidate["step"])  # 결정②
    suspect = _top_equipment(comm)
    evidence["commonality_rows"] = _commonality_rows(comm)  # §2.7 리치 보존
    if suspect is None:
        return suspect, evidence
    evidence["commonality_ratio"] = _ratio_for(comm, suspect)
    neg = await mcp.get_normal_lot_ratio(equipment_id=suspect)
    evidence["normal_ratio"] = neg["data"].get("normal_ratio")
    return suspect, evidence


async def _verify_unit(
    candidate: GraphRAGCandidate, lot_ids: list[str], mcp: MCPClient, time_range: tuple[str, str]
) -> tuple[str | None, EvidenceEntry]:
    """검증단위 하나당 MCP 호출 묶음. pre-pass(공통) + tier별 검증."""
    suspect, evidence = await _prepass(candidate, lot_ids, mcp)
    if suspect is None:
        return suspect, evidence
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
        direction = _drift_direction(series, normal_range)
        return {
            "drift_detected": _detect_drift(series, normal_range),  # 이탈 여부(방향은 drift_direction으로 별도)
            "drift_direction": direction,
            "direction_match": _direction_match(direction, candidate.get("direction")),
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
        # 기대 레시피가 KG에 없어 비교 불가(docs/KG_schema_v1.2.md에 명시된 한계) — 조회는 스킵,
        # recipe_match=None으로 "판정은 사람 몫"임을 그대로 남긴다.
        return {"recipe_match": None}

    return {}


def _empty_evidence() -> EvidenceEntry:
    return {
        "commonality_ratio": None,
        "drift_detected": None,
        "drift_direction": None,
        "direction_match": None,
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


def _drift_direction(series: list[dict], normal_range: list[float] | None) -> str | None:
    """드리프트 방향 — hi 초과만 'high', lo 미만만 'low', 정상/양방향 혼재는 None."""
    if not series or not normal_range:
        return None
    lo, hi = normal_range
    above = any(p["value"] > hi for p in series)
    below = any(p["value"] < lo for p in series)
    if above and not below:
        return "high"
    if below and not above:
        return "low"
    return None


def _direction_match(drift_direction: str | None, candidate_direction: str | None) -> bool | None:
    """drift 방향 ↔ candidate.direction 대조. 둘 다 있어야 판정, 아니면 None(n/a)."""
    if drift_direction is None or candidate_direction is None:
        return None
    return drift_direction == candidate_direction


def _series_by_param(series: list[dict]) -> dict[str, list[dict]]:
      """배치 telemetry 응답의 섞인 series를 param별로 가른다 (S2-2 배치 판정의 입구).

      query_telemetry(params=[...]) 1콜 응답은 여러 param 포인트가 ts순 한 리스트로
      섞여 온다(서버가 SELECT ts, param, value ... ORDER BY ts). param별로 갈라야
      단일 param 전제인 기존 판정 헬퍼(_detect_drift/_drift_direction)를 그대로
      재사용할 수 있다. ts 정렬은 원본 순서를 이어받는다(안정 append).
      point["param"]은 서버 계약상 항상 존재 — 없으면 KeyError로 시끄럽게 죽는 게 맞다.
      """
      by_param: dict[str, list[dict]] = {}
      for point in series:
          by_param.setdefault(point["param"], []).append(point)
      return by_param


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