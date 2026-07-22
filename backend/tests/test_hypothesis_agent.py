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