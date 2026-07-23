import json
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from backend.nodes.hypothesis import _to_hypothesis, _empty_evidence


def test_to_hypothesis_reconstructs_drift():
    candidate = {"cause": "slurry_flow_too_high", "tier": "자동", "step": "CMP",
                "evidence": "slurry_flow", "sentence": "...", "citations": []}
    base_evidence = {**_empty_evidence(), "normal_ratio": 0.1, "commonality_ratio": 0.9}
    fake_telemetry = {"data": {
        "series": [{"ts": "2026-03-04 10:00:00", "param": "slurry_flow", "value": 250.0}],  # [195,210] 밖
        "normal_ranges": {"slurry_flow": [195, 210]},
    }, "meta": {}}
    result = {"messages": [
        HumanMessage(content="..."),
        ToolMessage(content=json.dumps(fake_telemetry), name="query_telemetry", tool_call_id="t1"),
        AIMessage(content="slurry_flow가 정상범위를 벗어나 drift 관측됨."),
    ]}

    hyp = _to_hypothesis(candidate, result, suspect="CMP-01", base_evidence=base_evidence)

    assert hyp["evidence"]["drift_detected"] is True      # 250 > 210 → 이탈
    assert hyp["evidence"]["normal_ratio"] == 0.1         # base_evidence 이어받음
    assert hyp["equipment"] == "CMP-01"
    assert hyp["investigated"] is True
    assert "drift" in hyp["rationale"]


def test_drift_direction_and_match():
    from backend.nodes.hypothesis import _drift_direction, _direction_match
    nr = [195, 210]
    assert _drift_direction([{"value": 250.0}], nr) == "high"     # hi 초과
    assert _drift_direction([{"value": 100.0}], nr) == "low"      # lo 미만
    assert _drift_direction([{"value": 200.0}], nr) is None       # 정상
    assert _direction_match("high", "high") is True
    assert _direction_match("high", "low") is False               # 반박
    assert _direction_match("high", None) is None                 # candidate.direction 없음


def test_series_by_param():
    from backend.nodes.hypothesis import _series_by_param, _detect_drift, _drift_direction

    series = [  # 배치 1콜 응답 형태: 두 param이 ts순으로 섞여 온다 (ORDER BY ts)
        {"ts": "2026-03-04 10:00:00", "param": "slurry_flow", "value": 202.1},
        {"ts": "2026-03-04 10:00:00", "param": "down_force", "value": 5.0},
        {"ts": "2026-03-04 10:00:05", "param": "slurry_flow", "value": 251.3},
        {"ts": "2026-03-04 10:00:05", "param": "down_force", "value": 4.9},
    ]
    g = _series_by_param(series)
    assert set(g) == {"slurry_flow", "down_force"}
    assert [p["value"] for p in g["slurry_flow"]] == [202.1, 251.3]   # ts순 보존
    assert _series_by_param([]) == {}                                  # 빈 응답 = 빈 dict

    # 갈라낸 조각이 기존 단일 param 헬퍼에 그대로 들어가는지 (S2-2 재사용 계약)
    assert _detect_drift(g["slurry_flow"], [195, 210]) is True         # 251.3 > 210
    assert _drift_direction(g["slurry_flow"], [195, 210]) == "high"
    assert _detect_drift(g["down_force"], [4.5, 5.5]) is False         # 전부 정상범위


def test_to_hypotheses_batch_splits_params():
    from backend.nodes.hypothesis import _to_hypotheses_batch

    candidates = [
        {"cause": "slurry_flow_too_high", "tier": "자동", "step": "CMP",
        "evidence": "slurry_flow", "direction": "high", "sentence": "...", "citations": []},
        {"cause": "down_force_low", "tier": "자동", "step": "CMP",
        "evidence": "down_force", "direction": "low", "sentence": "...", "citations": []},
        {"cause": "pad_worn", "tier": "자동", "step": "CMP",
        "evidence": "pad_usage_hours", "direction": "high", "sentence": "...", "citations": []},  # 응답에 없는 param
    ]
    base_evidence = {**_empty_evidence(), "normal_ratio": 0.1, "commonality_ratio": 0.9}
    fake = {"data": {
        "series": [
            {"ts": "t1", "param": "slurry_flow", "value": 250.0},   # [195,210] 위로 이탈
            {"ts": "t1", "param": "down_force", "value": 5.0},      # [4.5,5.5] 정상
            {"ts": "t2", "param": "slurry_flow", "value": 255.0},
        ],
        "normal_ranges": {"slurry_flow": [195, 210], "down_force": [4.5, 5.5]},
    }, "meta": {}}
    result = {"messages": [
        HumanMessage(content="..."),
        ToolMessage(content=json.dumps(fake), name="query_telemetry", tool_call_id="t1"),
        AIMessage(content="배치 조사 서사"),
    ]}

    hyps = _to_hypotheses_batch(candidates, result, suspect="CMP-01", base_evidence=base_evidence)
    h_flow, h_force, h_pad = hyps

    # 후보1: 위로 drift + 예상방향 high → 일치 / 자기 param 조각만 실림
    assert h_flow["evidence"]["drift_detected"] is True
    assert h_flow["evidence"]["drift_direction"] == "high"
    assert h_flow["evidence"]["direction_match"] is True
    assert [p["value"] for p in h_flow["evidence"]["telemetry_series"]] == [250.0, 255.0]
    # 후보2: 같은 1콜에서 동시 판정 — 정상범위라 drift 아님
    assert h_force["evidence"]["drift_detected"] is False
    assert h_force["evidence"]["drift_direction"] is None
    assert h_force["investigated"] is True
    # 후보3: 조회 안 된 param → telemetry 필드 미기록 + investigated=False (judge_unknown 재료)
    assert h_pad["evidence"]["drift_detected"] is None
    assert h_pad["evidence"].get("telemetry_collected") is None
    assert h_pad["investigated"] is False
    # 공통: base 이어받기 + 배치 서사 공유
    assert all(h["evidence"]["normal_ratio"] == 0.1 for h in hyps)
    assert all(h["rationale"] == "배치 조사 서사" for h in hyps)


def test_investigate_group_batches_by_step(monkeypatch):
    import asyncio
    from backend.nodes import hypothesis as H

    candidates = [
        {"cause": "A", "tier": "자동", "step": "CMP", "evidence": "slurry_flow",
        "direction": "high", "sentence": "...", "citations": []},
        {"cause": "C", "tier": "자동", "step": "DEPO", "evidence": "susceptor_temp",
        "direction": None, "sentence": "...", "citations": []},
        {"cause": "B", "tier": "자동", "step": "CMP", "evidence": "down_force",
        "direction": "low", "sentence": "...", "citations": []},
    ]

    class FakeMCP:
        async def run_commonality_analysis(self, lot_ids, step=None):
            eq = {"CMP": "CMP-01", "DEPO": "DEPO-02"}[step]
            return {"data": {"n_lots": 2, "commonality": {"equipment_id": [
                {"value": eq, "lot_count": 2, "ratio": 1.0}]}}}
        async def get_normal_lot_ratio(self, equipment_id):
            return {"data": {"normal_ratio": 0.2}}

    prompts = []
    class FakeAgent:
        async def ainvoke(self, inp, config=None):
            prompt = inp["messages"][0][1]
            prompts.append(prompt)
            if "CMP-01" in prompt:   # CMP 배치: 두 param이 한 응답에
                fake = {"data": {"series": [
                    {"ts": "t1", "param": "slurry_flow", "value": 250.0},
                    {"ts": "t1", "param": "down_force", "value": 5.0},
                ], "normal_ranges": {"slurry_flow": [195, 210], "down_force": [4.5, 5.5]}}}
            else:                    # DEPO 배치
                fake = {"data": {"series": [{"ts": "t1", "param": "susceptor_temp", "value": 400.0}],
                                "normal_ranges": {"susceptor_temp": [390, 410]}}}
            return {"messages": [
                ToolMessage(content=json.dumps(fake), name="query_telemetry", tool_call_id="t"),
                AIMessage(content="배치 서사"),
            ]}

    monkeypatch.setattr(H, "create_react_agent", lambda model, tools: FakeAgent())

    hyps = asyncio.run(H.investigate_group(
        candidates, ["LOT1", "LOT2"], FakeMCP(),
        ("2026-03-04 00:00:00", "2026-03-05 00:00:00"), tools=None, model=None,
    ))

    assert len(hyps) == 3
    assert len(prompts) == 2                      # ← 배치의 핵심: step 2종 = 루프 2회 (후보 3회 아님)
    by_cause = {h["cause"]: h for h in hyps}
    assert by_cause["A"]["equipment"] == "CMP-01"
    assert by_cause["A"]["evidence"]["drift_detected"] is True    # 250 > 210
    assert by_cause["A"]["evidence"]["direction_match"] is True
    assert by_cause["B"]["evidence"]["drift_detected"] is False   # 같은 1콜에서 동시 판정
    assert by_cause["C"]["equipment"] == "DEPO-02"
    assert by_cause["C"]["evidence"]["drift_detected"] is False   # 400 ∈ [390,410]
    assert all(h["investigated"] for h in hyps)
    assert all(h["evidence"]["normal_ratio"] == 0.2 for h in hyps)  # pre-pass 이어받음
    # 내부는 CMP[A,B]·DEPO[C] 배치로 묶여 돌지만, 반환은 입력 순서 그대로 (kg rank 보존 = D1 전제)
    assert [h["cause"] for h in hyps] == ["A", "C", "B"]


def test_investigate_group_recursion_limit_fallback(monkeypatch):
    import asyncio
    from langgraph.errors import GraphRecursionError
    from backend.nodes import hypothesis as H

    candidates = [
        {"cause": "A", "tier": "자동", "step": "CMP", "evidence": "slurry_flow",
        "direction": "high", "sentence": "...", "citations": []},
        {"cause": "C", "tier": "자동", "step": "DEPO", "evidence": "susceptor_temp",
        "direction": None, "sentence": "...", "citations": []},
        {"cause": "B", "tier": "자동", "step": "CMP", "evidence": "down_force",
        "direction": "low", "sentence": "...", "citations": []},
    ]

    class FakeMCP:
        async def run_commonality_analysis(self, lot_ids, step=None):
            eq = {"CMP": "CMP-01", "DEPO": "DEPO-02"}[step]
            return {"data": {"n_lots": 2, "commonality": {"equipment_id": [
                {"value": eq, "lot_count": 2, "ratio": 1.0}]}}}
        async def get_normal_lot_ratio(self, equipment_id):
            return {"data": {"normal_ratio": 0.2}}

    class FakeAgent:
        async def ainvoke(self, inp, config=None):
            prompt = inp["messages"][0][1]
            if "CMP-01" in prompt:            # CMP 배치만 폭주 → 상한 초과
                raise GraphRecursionError("recursion limit reached")
            fake = {"data": {"series": [{"ts": "t1", "param": "susceptor_temp", "value": 400.0}],
                            "normal_ranges": {"susceptor_temp": [390, 410]}}}
            return {"messages": [
                ToolMessage(content=json.dumps(fake), name="query_telemetry", tool_call_id="t"),
                AIMessage(content="배치 서사"),
            ]}

    monkeypatch.setattr(H, "create_react_agent", lambda model, tools: FakeAgent())

    hyps = asyncio.run(H.investigate_group(
        candidates, ["LOT1", "LOT2"], FakeMCP(),
        ("2026-03-04 00:00:00", "2026-03-05 00:00:00"), tools=None, model=None,
    ))

    by_cause = {h["cause"]: h for h in hyps}
    # 폭주 배치(CMP): "조사됐다 거짓 표시" 없이 미조사 폴백 — telemetry 없음, pre-pass 값은 보존
    assert by_cause["A"]["investigated"] is False
    assert by_cause["B"]["investigated"] is False
    assert by_cause["A"]["evidence"]["drift_detected"] is None
    assert by_cause["A"]["evidence"]["normal_ratio"] == 0.2   # pre-pass 이어받음
    assert by_cause["A"]["equipment"] == "CMP-01"             # suspect 확정까지는 유효
    # 정상 배치(DEPO)는 영향 없음 — 폭주가 배치 단위로 격리됨
    assert by_cause["C"]["investigated"] is True
    assert by_cause["C"]["evidence"]["drift_detected"] is False
    # 폴백이 섞여도 반환 순서 = 입력 순서 계약 유지
    assert [h["cause"] for h in hyps] == ["A", "C", "B"]


def test_cluster_key_and_evidence_strength():
    from backend.nodes.hypothesis import _cluster_key, _evidence_strength

    fast = {"step": "CMP", "evidence_label": "Parameter", "evidence": "slurry_flow", "direction": "high"}
    slow = {"step": "CMP", "evidence_label": "Parameter", "evidence": "slurry_flow", "direction": "high"}
    low  = {"step": "CMP", "evidence_label": "Parameter", "evidence": "slurry_flow", "direction": "low"}
    assert _cluster_key(fast) == _cluster_key(slow)   # 같은 unit+direction → 병합 (스모크 실측: fast/slow)
    assert _cluster_key(fast) != _cluster_key(low)    # 방향 다름 → 경쟁 클러스터 (묶으면 안 됨)

    # 확실성 우선 서수: telemetry(지지>불명>반대>음성) > maintenance > 무신호
    assert _evidence_strength({"drift_detected": True, "direction_match": True}) == 5
    assert _evidence_strength({"drift_detected": True, "direction_match": None}) == 4
    assert _evidence_strength({"drift_detected": True, "direction_match": False}) == 3
    assert _evidence_strength({"drift_detected": False}) == 2
    assert _evidence_strength({"drift_detected": None, "maintenance_hit": True}) == 1
    assert _evidence_strength({"drift_detected": None, "maintenance_hit": None}) == 0


def test_annotate_clusters():
    from backend.nodes.hypothesis import _annotate_clusters

    # 후보 4개: fast/slow는 같은 unit+direction(병합), low는 방향 다름(분리),
    # frag는 파편화 cause — fast와 같은 cause가 Maintenance unit에도 걸침
    candidates = [
        {"step": "CMP", "evidence_label": "Parameter", "evidence": "slurry_flow", "direction": "high"},
        {"step": "CMP", "evidence_label": "Parameter", "evidence": "slurry_flow", "direction": "high"},
        {"step": "CMP", "evidence_label": "Parameter", "evidence": "slurry_flow", "direction": "low"},
        {"step": "CMP", "evidence_label": "Maintenance", "evidence": "pad_replace", "direction": None},
    ]
    hypotheses = [
        {"cause": "fast", "evidence": {"drift_detected": True, "direction_match": True}},
        {"cause": "slow", "evidence": {"drift_detected": True, "direction_match": True}},
        {"cause": "too_low", "evidence": {"drift_detected": True, "direction_match": False}},
        {"cause": "fast", "evidence": {"drift_detected": None, "maintenance_hit": True}},  # 파편화: fast의 2번째 unit
    ]
    _annotate_clusters(candidates, hypotheses)

    # 병합/분리
    assert hypotheses[0]["cluster_id"] == hypotheses[1]["cluster_id"]      # fast/slow 병합
    assert hypotheses[0]["cluster_id"] != hypotheses[2]["cluster_id"]      # 방향 다름 → 분리
    assert hypotheses[0]["cluster_id"] != hypotheses[3]["cluster_id"]      # 다른 unit → 분리
    # 파편화 대표: fast는 telemetry 행(세기 5)이 maintenance 행(세기 1)을 이김
    assert hypotheses[0]["is_primary"] is True
    assert hypotheses[3]["is_primary"] is False
    # 파편화 없는 cause는 자기 행이 대표
    assert hypotheses[1]["is_primary"] is True
    assert hypotheses[2]["is_primary"] is True


def test_annotate_clusters_tie_keeps_prior_order():
    from backend.nodes.hypothesis import _annotate_clusters

    # 같은 cause가 두 unit에 걸쳤는데 증거 세기가 동률(둘 다 무신호 0) → 먼저 온 행이 대표
    candidates = [
        {"step": "DEPO", "evidence_label": "Maintenance", "evidence": "clean_a", "direction": None},
        {"step": "DEPO", "evidence_label": "Maintenance", "evidence": "clean_b", "direction": None},
    ]
    hypotheses = [
        {"cause": "contam", "evidence": {}},
        {"cause": "contam", "evidence": {}},
    ]
    _annotate_clusters(candidates, hypotheses)
    assert hypotheses[0]["is_primary"] is True     # prior(먼저 온) 행 유지
    assert hypotheses[1]["is_primary"] is False


def test_rank_hypotheses_orders_clusters_by_evidence():
    from backend.nodes.hypothesis import _rank_hypotheses

    # kg rank 순 입력: 약한 클러스터(u1: A,C)가 앞, 강한 클러스터(u2: B)가 뒤
    hypotheses = [
        {"cause": "A", "cluster_id": "u1", "evidence": {"drift_detected": False, "normal_ratio": 0.2}},
        {"cause": "B", "cluster_id": "u2",
        "evidence": {"drift_detected": True, "direction_match": True, "normal_ratio": 0.2}},
        {"cause": "C", "cluster_id": "u1", "evidence": {"drift_detected": False, "normal_ratio": 0.2}},
    ]
    ranked = _rank_hypotheses(hypotheses)

    # 강한 클러스터(세기 5)가 앞으로, u1은 묶음째 이동 + 내부 prior(A→C) 유지
    assert [h["cause"] for h in ranked] == ["B", "A", "C"]
    assert ranked[0]["cause"] == "B"          # hypotheses[0] = 대표원인 (C4/D1)


def test_rank_hypotheses_normal_ratio_tiebreak():
    from backend.nodes.hypothesis import _rank_hypotheses

    # 증거 세기 동률(둘 다 5) → normal_ratio 낮은(반대증거 적은) 클러스터가 앞
    hypotheses = [
        {"cause": "high_counter", "cluster_id": "u1",
        "evidence": {"drift_detected": True, "direction_match": True, "normal_ratio": 0.9}},
        {"cause": "low_counter", "cluster_id": "u2",
        "evidence": {"drift_detected": True, "direction_match": True, "normal_ratio": 0.1}},
    ]
    assert [h["cause"] for h in _rank_hypotheses(hypotheses)] == ["low_counter", "high_counter"]


def test_rank_hypotheses_none_ratio_neutral_and_prior_tiebreak():
    from backend.nodes.hypothesis import _rank_hypotheses

    # 전부 세기 0 동률. None ratio는 중립 0.5 → 실측 0.2보다 뒤, 0.9보다 앞.
    # None끼리 완전 동률이면 prior(최초 등장 순) 유지.
    hypotheses = [
        {"cause": "unknown_a", "cluster_id": "u1", "evidence": {"normal_ratio": None}},
        {"cause": "unknown_b", "cluster_id": "u2", "evidence": {"normal_ratio": None}},
        {"cause": "low_counter", "cluster_id": "u3", "evidence": {"normal_ratio": 0.2}},
        {"cause": "high_counter", "cluster_id": "u4", "evidence": {"normal_ratio": 0.9}},
    ]
    assert [h["cause"] for h in _rank_hypotheses(hypotheses)] == \
        ["low_counter", "unknown_a", "unknown_b", "high_counter"]


def test_matched_cause_carried_to_hypothesis():
    from backend.nodes.hypothesis import _det_hypothesis, _to_hypotheses_batch

    candidate = {"cause": "A", "matched_cause": "clean_nozzle_clog", "tier": "자동",
                "step": "CLEAN", "evidence": "flow_rate", "direction": "low",
                "sentence": "...", "citations": []}

    # 결정론 경로
    det = _det_hypothesis(candidate, suspect=None, evidence={}, investigated=False)
    assert det["matched_cause"] == "clean_nozzle_clog"

    # 에이전트 배치 경로
    result = {"messages": [AIMessage(content="서사")]}
    batch = _to_hypotheses_batch([candidate], result, suspect="CLEAN-01", base_evidence={})
    assert batch[0]["matched_cause"] == "clean_nozzle_clog"

    # matched_cause 없는 후보(구버전 kg 출력 등)는 None으로 정직하게
    no_map = dict(candidate)
    no_map.pop("matched_cause")
    assert _det_hypothesis(no_map, None, {}, investigated=False)["matched_cause"] is None


def test_maintenance_range_extends_past_defect():
    from backend.nodes.hypothesis import _maintenance_range

    tr = ("2026-03-11 00:00:00", "2026-03-17 06:00:00")

    # ① defect_ts 없음 → 연장 기준점이 없어 원래 창 그대로 (무동작 안전)
    assert _maintenance_range(tr, None) == tr

    # ② 통상 케이스(SC-CENTER-01 모양): defect+14d > 공정 끝 → 끝만 연장, 시작 불변
    got = _maintenance_range(tr, "2026-03-17 00:41:59")
    assert got[0] == tr[0]
    assert got[1] == "2026-03-31 00:41:59"          # defect + MAINT_LOOKAHEAD_DAYS(14)

    # ③ 창은 절대 줄지 않는다: defect+14d < 공정 끝이면 공정 끝 유지 (max의 존재 이유)
    long_tr = ("2026-03-01 00:00:00", "2026-04-20 00:00:00")
    assert _maintenance_range(long_tr, "2026-03-05 00:00:00") == long_tr

def test_with_step_fallback():
    from backend.nodes.hypothesis import _with_step_fallback

    candidates = [
        {"cause": "a", "step": None, "mapped_process": "CLEAN"},   # 보충 대상
        {"cause": "b", "step": "DEPO", "mapped_process": "CLEAN"}, # step 정본 유지 (불가침)
        {"cause": "c", "step": None, "mapped_process": None},      # 보충 재료 없음 → 그대로
    ]
    out = _with_step_fallback(candidates)
    assert [c["step"] for c in out] == ["CLEAN", "DEPO", None]
    assert candidates[0]["step"] is None          # 원본 무변형(사본 생성 확인)


def test_group_time_range_union():
    import asyncio
    from backend.nodes.hypothesis import _group_time_range

    class FakeMCP:
        async def get_lot_history(self, lot_id):
            windows = {
                "L1": [{"ts_in": "2026-03-16 07:00:00", "ts_out": "2026-03-17 02:00:00"}],
                "L2": [{"ts_in": "2026-03-13 22:00:00", "ts_out": "2026-03-14 16:00:00"}],
                "L3": [],                                          # 이력 없는 로트는 건너뜀
                "L4": [{"ts_in": "2026-03-17 15:00:00", "ts_out": "2026-03-18 09:00:00"}],
            }
            return {"data": windows[lot_id]}

    tr = asyncio.run(_group_time_range(["L1", "L2", "L3", "L4"], FakeMCP()))
    assert tr == ("2026-03-13 22:00:00", "2026-03-18 09:00:00")   # 전체 합집합 (첫 로트 아님)


def test_rank_hypotheses_commonality_tiebreak():
    from backend.nodes.hypothesis import _rank_hypotheses

    # 세기 동률(둘 다 5) → 결함 로트 공통률 높은(전부 지나간) 클러스터가 앞 (처방4)
    hypotheses = [
        {"cause": "partial", "cluster_id": "u1",
        "evidence": {"drift_detected": True, "direction_match": True,
                    "commonality_ratio": 0.625, "normal_ratio": 0.89}},
        {"cause": "full", "cluster_id": "u2",
        "evidence": {"drift_detected": True, "direction_match": True,
                    "commonality_ratio": 1.0, "normal_ratio": 0.91}},
    ]
    # normal_ratio로는 partial(0.89)이 이기지만, commonality가 그보다 우선한다
    assert [h["cause"] for h in _rank_hypotheses(hypotheses)] == ["full", "partial"]