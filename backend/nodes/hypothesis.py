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
from langgraph.errors import GraphRecursionError
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
# investigate_group(S2-2): 자동(Parameter) tier 후보 전부를 그룹 조사관(에이전트)이 step 배치로 검증한다.
#   step당 pre-pass(commonality/normal_ratio) 1회 → query_telemetry 1콜(params 전부) → 후보별 분배.
#   evidence는 LLM이 아니라 도구 반환(ToolMessage)에서 재구성한다(옵션 A). 반자동·근거없음은 결정론 경로 유지.
#   (슬라이스1의 verify_one/_build_prompt는 배치로 흡수·삭제 — 필요하면 git 히스토리 참고)


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

    # S2-2: 자동 tier 전부 → 그룹 조사관(에이전트, step 배치). 반자동·근거없음 → 결정론 유지.
    auto = [c for c in candidates if c["tier"] == "자동"]
    agent_hyps: dict[int, Hypothesis] = {}
    if auto:
        tools = await mcp.get_agent_tools()            # 그룹당 1회
        model = _make_model()
        results = await investigate_group(auto, lot_ids, mcp, time_range, tools, model)
        agent_hyps = dict(zip((id(c) for c in auto), results))  # 반환 순서 = 입력 순서 계약

    # 같은 (step, evidence_label, evidence)는 결과 재사용 — 결정①.
    # 이제 반자동·근거없음 전용 (자동 tier의 캐시 역할은 배치 telemetry 1콜이 흡수).
    verify_cache: dict[tuple, tuple] = {}
    hypotheses: list[Hypothesis] = []
    for candidate in candidates:          # 원순서(kg rank)로 조립 — _annotate_clusters zip 전제. 최종 순서는 _rank_hypotheses가 결정
        if id(candidate) in agent_hyps:
            hypotheses.append(agent_hyps[id(candidate)])
            continue
        key = (candidate["step"], candidate["evidence_label"], candidate["evidence"])
        if key not in verify_cache:
            verify_cache[key] = await _verify_unit(candidate, lot_ids, mcp, time_range)
        suspect, evidence = verify_cache[key]
        hypotheses.append(_det_hypothesis(candidate, suspect, dict(evidence), investigated=False))

    # 클러스터 id + cause 대표 행 주석 — 순서·행 수 불변
    _annotate_clusters(candidates, hypotheses)

    # S2-4: fab 증거 재랭킹 (C4) — 여기서부터의 순서가 곧 최종 표시 순서 (⑤⑥은 보존만)
    hypotheses = _rank_hypotheses(hypotheses)

    for hyp in hypotheses:                # 시간정합 기준(defect_ts) 일괄 스탬프 — ④가 수집(firewall)
        hyp["evidence"]["defect_ts"] = defect_ts

    return {"hypotheses": {group_id: hypotheses}}


# S2-5: 배치당 에이전트 루프 스텝 상한 (기획안 §9 "검증 라운드 상한" 이행).
# 정상 경로 = agent→tools(1콜)→agent 3스텝. 8이면 예상 밖 재호출 2~3번까지 허용하되
# 폭주(1콜 지시 불이행 반복)는 끊는다. 초과 시 그 배치는 미조사 폴백(아래 investigate_group).
AGENT_RECURSION_LIMIT = 8


def _make_model():
      return ChatOpenAI(model=os.environ["OPENAI_MODEL"], temperature=0)   # temp=0 = 재현성(§8-7)


def _det_hypothesis(candidate, suspect, evidence, investigated: bool) -> Hypothesis:
    return {
        "cause": candidate["cause"],
        "matched_cause": candidate.get("matched_cause"),   # 평가 전용 운반
        "tier": candidate["tier"],
        "stage": candidate["step"],
        "equipment": suspect,
        "evidence": evidence,
        "citations": candidate.get("citations", []),
        "sentence": candidate["sentence"],
        "investigated": investigated,
    }



async def investigate_group(
    candidates: list[GraphRAGCandidate], lot_ids: list[str], mcp: MCPClient,
    time_range: tuple[str, str], tools, model,
) -> list[Hypothesis]:
    """그룹 조사관 본체 (S2-2): 자동 tier 후보 전부를 step 배치로 조사한다.

    step별로 묶어 pre-pass(공통조회) 1회 → suspect 확정 → 에이전트 1루프가
    query_telemetry 1콜(params 전부) → _to_hypotheses_batch로 후보별 분배.
    suspect가 없으면(공통 장비 특정 불가) 그 배치는 결정론 폴백(investigated=False).
    배치당 에이전트 스텝 상한 = AGENT_RECURSION_LIMIT(S2-5) — 초과(폭주) 시에도
    같은 미조사 폴백으로 안전하게 무너진다. 조기 종료는 없음(후보 전량이 증거를 받아야 함).

    반환 순서 = 입력 candidates 순서. build_hypotheses의 원순서 조립과
    _annotate_clusters의 zip이 이 계약을 전제한다 — S2-4 재랭킹이 생긴 뒤에도
    유지되는 계약이다(재랭킹은 주석이 끝난 뒤 _rank_hypotheses가 별도로 한다).
    """
    by_step: dict = {}
    for c in candidates:
        by_step.setdefault(c["step"], []).append(c)   # step=None(결정②)도 자기들끼리 한 배치

    pairs: list[tuple[GraphRAGCandidate, Hypothesis]] = []
    for step, batch in by_step.items():
        suspect, base_evidence = await _prepass(batch[0], lot_ids, mcp)  # step 공통 → 대표 1개로 1회
        if suspect is None:                    # 조사할 장비 없음 → 배치 전체 미조사 폴백
            pairs.extend(
                (c, _det_hypothesis(c, suspect, dict(base_evidence), investigated=False)) for c in batch
            )
            continue
        params = list(dict.fromkeys(c["evidence"] for c in batch))   # 중복 제거 + 순서 보존
        agent = create_react_agent(model, tools)
        prompt = _build_group_prompt(batch, suspect, params, time_range)
        try:
            result = await agent.ainvoke(
                {"messages": [("user", prompt)]},
                {"recursion_limit": AGENT_RECURSION_LIMIT},
            )
        except GraphRecursionError:
            # 상한 초과 = 폭주. "조사됐다 거짓 표시" 대신 배치 전체 미조사 폴백 —
            # suspect None 폴백과 같은 안전한 무너짐(⑤ judge_unknown 재료).
            pairs.extend(
                (c, _det_hypothesis(c, suspect, dict(base_evidence), investigated=False)) for c in batch
            )
            continue
        pairs.extend(zip(batch, _to_hypotheses_batch(batch, result, suspect, base_evidence)))

    order = {id(c): i for i, c in enumerate(candidates)}
    return [h for _, h in sorted(pairs, key=lambda p: order[id(p[0])])]


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
            "matched_cause": candidate.get("matched_cause"),   # 평가 전용 운반
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


def _cluster_key(candidate: GraphRAGCandidate) -> str:
    """클러스터 병합 키 = unit + direction (S2-3, terms §2-1 "함축의 바닥").

    같은 (step, evidence_label, evidence)에 예상 방향까지 같으면 fab 증거로는 영원히
    구분 불가한 경쟁 가설 묶음이다. 방향이 다르면 방향 대조(S2-1)로 갈리는 경쟁
    클러스터라 묶지 않는다. direction은 실측(drift_direction)이 아니라 KG 예상
    (candidate.direction) 기준 — "같은 질문 + 같은 기대"가 병합 조건이다.
    """
    return f"{candidate['step']}|{candidate['evidence_label']}|{candidate['evidence']}|{candidate.get('direction')}"


def _evidence_strength(evidence: EvidenceEntry) -> int:
    """cause 대표(주 증거) 행 선정용 서수 (S2-3, terms §5 파편화 대응).

    확실성 우선: telemetry 판정(drift_detected가 not None) > maintenance 정황 > 무신호.
    telemetry 안에서는 지지 세기 순. "정상범위(음성)"도 maintenance보다 위인 이유:
    §5 "Parameter 핸들을 가진 cause는 그 Parameter가 주 증거"(telemetry가 더 확실) —
    확실한 반박도 그 cause의 대표 검증 결과다. 이 서수는 S2-4 랭킹
    (_rank_hypotheses)의 클러스터 세기로도 재사용된다 — 대표 행 선정과
    클러스터 순위가 같은 확실성 축을 공유한다.
    """
    drift = evidence.get("drift_detected")
    if drift is True:
        match = evidence.get("direction_match")
        return 5 if match is True else (4 if match is None else 3)
    if drift is False:
        return 2                       # telemetry 정직한 음성 — 그래도 telemetry 확실성
    if evidence.get("maintenance_hit"):
        return 1
    return 0                           # 무신호/미조사


def _annotate_clusters(candidates: list[GraphRAGCandidate], hypotheses: list[Hypothesis]) -> None:
      """S2-3: 클러스터 id + cause 대표(주 증거) 행을 주석한다. 순서·행 수 불변(annotation only).
  
      candidates↔hypotheses는 같은 순서라는 전제(zip) — investigate_group의
      "반환 순서 = 입력 순서" 계약과 build_hypotheses의 원순서 조립이 이를 보장한다.
      정렬(클러스터 순위·prior 내부 정렬)은 여기서 하지 않는다 — 바로 뒤에 호출되는 _rank_hypotheses의 몫.

      - cluster_id: 같은 unit+direction(_cluster_key) 행들의 묶음 표식. 표시층(⑥/프론트)이
        이 id로 원인군 카드를 묶는다(terms §6). 행 구조는 안 바꾼다(API §2.5 무변경).
      - is_primary: 같은 cause가 여러 unit에 걸칠 때(파편화 32%, terms §5) 대표 행 1개만
        True. 확실성 서수(_evidence_strength) 최강 행, 동률이면 먼저 온 행(= prior 순서,
        "prior는 타이브레이커").
      """
      for candidate, hyp in zip(candidates, hypotheses):
          hyp["cluster_id"] = _cluster_key(candidate)

      best: dict[str, tuple[int, int]] = {}          # cause -> (최강 세기, 그 행 index)
      for i, hyp in enumerate(hypotheses):
          strength = _evidence_strength(hyp["evidence"])
          cause = hyp["cause"]
          if cause not in best or strength > best[cause][0]:   # 동률은 갱신 안 함 → 먼저 온 행 유지
              best[cause] = (strength, i)
      for i, hyp in enumerate(hypotheses):
          hyp["is_primary"] = (best[hyp["cause"]][1] == i)


def _rank_hypotheses(hypotheses: list[Hypothesis]) -> list[Hypothesis]:
    """S2-4: fab 증거 재랭킹 (C4 구현) — 파이프라인에서 처음으로 순서가 바뀌는 지점.

    행이 아니라 클러스터(unit+direction) 단위로 정렬한다: 같은 클러스터 행들은
    fab 증거가 동일해(함축의 바닥, terms §2-1) fab으로는 서로 구분 불가 —
    묶음째 움직이고 내부는 prior(kg rank) 순서를 유지한다. 행 수·내용 불변.

    클러스터 정렬 키(위가 우선):
    ① 증거 세기(_evidence_strength) 내림차순 — 구성원 증거가 동일하므로 첫 행이 대표
    ② normal_ratio 오름차순 — 반대 증거 할인(같은 장비가 정상 로트도 많이 냈으면 약화).
        None(미조회)은 중립 0.5로 취급
    ③ 최초 등장 index 오름차순 — 완전 동률이면 prior(kg rank)가 타이브레이커

    ⑤ Critic·⑦ response가 순서를 보존만 하므로 최종 accepted[0] = 대표 원인이
    여기서 결정된다(BACKEND_DECISIONS.md D1). cluster_id가 없으면 KeyError로
    시끄럽게 죽는 게 맞다 — _annotate_clusters 뒤에서만 부르라는 계약.
    """
    clusters: dict[str, list[Hypothesis]] = {}
    for hyp in hypotheses:
        clusters.setdefault(hyp["cluster_id"], []).append(hyp)   # 삽입 순 = 최초 등장 순

    def sort_key(item):
        prior, members = item
        evidence = members[0]["evidence"]          # 클러스터 내 증거 동일 → 첫 행이 대표
        ratio = evidence.get("normal_ratio")
        return (-_evidence_strength(evidence), ratio if ratio is not None else 0.5, prior)

    ranked = sorted(enumerate(clusters.values()), key=sort_key)
    return [hyp for _, members in ranked for hyp in members]


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