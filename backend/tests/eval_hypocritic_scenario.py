"""S3-2 평가 체인 (실LLM + 실MCP) — ground truth 시나리오로 ③→④→⑤→⑥ 관통.

레포 루트에서 실행 (실LLM+MCP 수동 하네스 — pytest 자동수집 대상 아님, test_ 접두 없음 유지):
    python "backend/tests/eval_hypocritic_scenario.py"              # 기본 SC-CENTER-01
    python "backend/tests/eval_hypocritic_scenario.py" SC-CENTER-02 # 다른 시나리오

이 프로젝트 **최초의 정답 대조 실행**이다. 지금까지 스모크는 lot101(시나리오 밖)로
"기계가 도는가"만 봤다 — 여기서 처음으로 ground truth의 실제 lot_ids를 파이프라인에
태우고 true_root_causes / traps_to_reject와 대조한다.

통과/실패 단정이 목적이 아니라 **진단**이 목적이다(평가 주도 개발):
  ① 정답 원인(true_root_causes)이 matched_cause 기준으로 최종 랭킹 몇 위인가
  ② 함정(traps_to_reject 장비)이 ⑤에서 어떤 토큰으로 기각됐나 — 살아남았으면 그게 다음 과제
  ③ UC 상태(reviewed/insufficient/unmapped)
  ④ ⑤ firewall — Critic 구간 MCP 재조회 0회
결과가 기대와 다르면 그 갭 자체가 S3-3 이후의 작업을 정의한다.

정답 대조 키 = matched_cause(kg cause→mapping_table 어휘 번역, S3-1에서 관통). cause
문자열 직접 비교(skeleton_kickoff §8.5-3의 0% 이슈)를 우회한다.
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))                                 # 레포 루트 → backend import
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")                  # Windows cp949 콘솔 대비

from backend.deps import kg_client, mcp_client                # dotenv 로드 포함
from backend.nodes import hypothesis as H
from backend.nodes.graphrag import fetch_graphrag_candidates
from backend.nodes.critic import review_hypotheses
from backend.nodes.response import generate_response, respond_without_llm, _JUDGE_UNKNOWN_TOKENS

GT_DIR = REPO / "secsgem-mcp" / "datasets" / "ground_truth"
GROUP_ID = "g_eval"


def load_gt(scenario_id: str) -> dict:
    return json.loads((GT_DIR / f"{scenario_id}.json").read_text(encoding="utf-8"))


def verdict_of(h: dict) -> str:
    if h.get("verdict"):                                      # ⑥ 통과분은 이미 verdict 부여됨
        return h["verdict"]
    if "reject_token" not in h:
        return "accepted"
    return "judge_unknown" if h["reject_token"] in _JUDGE_UNKNOWN_TOKENS else "rejected"


def trap_equipments(gt: dict) -> list[str]:
    """traps_to_reject 문자열에서 장비 토큰(':' 앞)을 뽑는다. 예: 'LITHO-01: ...' → 'LITHO-01'."""
    return [t.split(":", 1)[0].strip() for t in gt.get("traps_to_reject", [])]


def install_firewall_spy(mcp) -> dict:
    """④/⑤ 단계별 MCP 콜 계측 — ⑤ 재조회 0(firewall) 검증용."""
    counts: dict = {"phase": "④", "hypothesis": {}, "critic": {}}
    orig = mcp._call
    async def spy(name, **kw):
        bucket = counts["critic"] if counts["phase"] == "⑤" else counts["hypothesis"]
        bucket[name] = bucket.get(name, 0) + 1
        return await orig(name, **kw)
    mcp._call = spy
    return counts


async def main() -> None:
    scenario_id = sys.argv[1] if len(sys.argv) > 1 else "SC-CENTER-01"
    gt = load_gt(scenario_id)
    pattern = (gt.get("defect_patterns") or ["Center"])[0]
    lot_ids = gt["lot_ids"]
    true_causes = set(gt.get("true_root_causes") or [])
    traps = trap_equipments(gt)

    print(f"=== 시나리오 {scenario_id} ===")
    print(f"  pattern={pattern}  lot_ids={len(lot_ids)}개  is_unmatched={gt.get('is_unmatched')}")
    print(f"  정답(true_root_causes): {sorted(true_causes) or '없음(unmatched)'}")
    print(f"  함정(traps_to_reject): {traps or '없음'}")
    print(f"  기대 증거경로: {gt.get('key_evidence_path')}")

    mcp = mcp_client()
    counts = install_firewall_spy(mcp)
    # #33 평탄화: 노드가 GroupState(납작)를 직접 받는다 — groups 래핑·group_id 인자·group_id 중첩 반환 없음.
    state: dict = {"group_id": GROUP_ID, "pattern": pattern, "lot_ids": lot_ids, "observation": None}

    try:
        # ④ GraphRAG 조회 (kg_client, mcp 불요)
        state.update(fetch_graphrag_candidates(state, kg_client()))
        n_cand = len(state["candidates"])
        print(f"\n④ 후보 조회: {n_cand}건")

        # ⑤ Hypothesis (재랭킹까지)
        state.update(await H.build_hypotheses(state, mcp))

        # ⑥ Critic (firewall — 이 구간 MCP 콜 0이어야). phase="⑤"는 스파이의 critic 버킷 마커.
        counts["phase"] = "⑤"
        state.update(await review_hypotheses(state, mcp))
        counts["phase"] = "⑥"

        # ⑦ 응답생성 — 그래프 라우팅 모사: 후보 0 or 채택 0이면 ⑦'(respond_without_llm)
        if state["candidates"] and state["critic_result"].get("accepted"):
            state.update(generate_response(state))
        else:
            state.update(respond_without_llm(state))
    finally:
        await mcp.aclose()

    final = state["final_response"]
    ordered = final["hypotheses"]          # 정렬·verdict·hypothesis_id 포함 (대표 = index 0)

    print(f"\n=== ⑥ 최종 (status={final['status']}) — 상위 12건 ===")
    print(f"  {'#':>3} {'verdict':13} {'matched_cause':38} {'stage':6} {'equip':10} token")
    for i, h in enumerate(ordered[:12]):
        mc = h.get("matched_cause")
        star = " ★정답" if mc in true_causes else ""
        trap = " ⚠함정" if any(t == h.get("equipment") for t in traps) else ""
        print(f"  {i:>3} {verdict_of(h):13} {str(mc):38.38} {str(h.get('stage')):6.6} "
              f"{str(h.get('equipment')):10.10} {h.get('reject_token','')}{star}{trap}")

    # --- 상위 12건 정렬 신호 덤프 (B1/B2 설계용, 파이프라인 실측 evidence) ---
    # 손으로 fab.db 재구성 대신 파이프라인이 실제 창으로 저장한 telemetry_series로 지속성·최대초과폭 계산.
    # comm=결함로트 공통률, norm=정상로트비율(반대증거), 지속%=이탈 포인트 비율, 최대초과=범위 밖 최대폭.
    def _fnum(x):
        return "-" if x is None else f"{x:.2f}"
    print("\n=== 상위 12건 정렬 신호 (파이프라인 실측) ===")
    print(f"  {'#':>2} {'comm':>5} {'norm':>5} {'지속%':>5} {'최대초과':>8} {'특이성':>6}  cluster / matched_cause")
    for i, h in enumerate(ordered[:12]):
        ev = h.get("evidence", {}) or {}
        series = ev.get("telemetry_series") or []
        nr = ev.get("telemetry_normal_range")
        if series and nr:
            lo, hi = nr
            outs = [max(p.get("value", 0) - hi, lo - p.get("value", 0), 0) for p in series]
            nout = sum(1 for d in outs if d > 0)
            persist = str(round(100 * nout / len(series)))
            maxdev = f"{max(outs):.1f}" if outs else "0"
        else:
            persist = maxdev = "-"
        print(f"  {i:>2} {_fnum(ev.get('commonality_ratio')):>5} {_fnum(ev.get('normal_ratio')):>5} "
              f"{persist:>5} {maxdev:>8} {_fnum(ev.get('specificity')):>6}  "
              f"{h.get('cluster_id')} / {h.get('matched_cause')}")

    # --- 진단 지표 (S3-3a 보강: 정답 덤프·시간재료·집계) ---
    print("\n=== 진단 ===")

    # ⓪ verdict 총계 + accepted 장비 분포 — 과채택 규모(발견 3)
    v_total = Counter(verdict_of(h) for h in ordered)
    acc_by_equip = Counter(h.get("equipment") for h in ordered if verdict_of(h) == "accepted")
    print(f"⓪ verdict 총계: {dict(v_total)}")
    print(f"   accepted 장비 분포: {dict(acc_by_equip)}")

    # ⓪ 그룹 공통 defect_ts — None이면 ⑤ P2 시간역전이 구조적으로 무발화(발견 2 선결 확인)
    defect_ts = next((h["evidence"].get("defect_ts") for h in ordered), None)
    print(f"⓪ defect_ts(그룹 공통): {defect_ts}"
          + ("  ⚠ None → _check_time_consistency 전부 통과(P2 무발화 원인)" if defect_ts is None else ""))

    # ① 정답 행 전체 덤프 + 갈래 판별 (데이터 / ⑤critic로직 / ④조사 / ④랭킹)
    if true_causes:
        hits = [(i, h) for i, h in enumerate(ordered) if h.get("matched_cause") in true_causes]
        if not hits:
            print("① 정답 원인: matched_cause로는 후보에 없음 — kg 유사도매칭/조회 갭 의심")
            # 매핑갭(사실은 발견) vs 진짜 미탐 판별: 상위 3개 클러스터의 실제 cause를 덤프한다.
            # 기대 장비(cause_sites)가 상위 클러스터에 있으면 "파이프라인은 찾았는데 matched_cause 미연결".
            exp_eq = [s[0] for s in (gt.get("cause_sites") or [])]
            print(f"   기대 장비(cause_sites)={exp_eq} — 아래 상위 클러스터에 이 장비 있으면 '매핑갭(사실 발견)':")
            seen_cl: list = []
            for i, h in enumerate(ordered):
                cid = h.get("cluster_id")
                if cid in seen_cl:
                    continue
                seen_cl.append(cid)
                eq = h.get("equipment")
                mark = " ←기대장비 ★매핑갭 의심" if eq in exp_eq else ""
                print(f"   [{i}위] cluster={cid} equip={eq}{mark}")
                print(f"        cause={h.get('cause')}  matched_cause={h.get('matched_cause')}  "
                      f"verdict={verdict_of(h)}")
                if len(seen_cl) >= 3:
                    break
        else:
            print(f"① 정답 행 {len(hits)}건 (matched_cause ∈ {sorted(true_causes)}):")
            for i, h in hits:
                ev = h["evidence"]
                print(f"   [{i}위] cause={h['cause']}")
                print(f"        tier={h['tier']} investigated={h.get('investigated')} "
                      f"equip={h.get('equipment')} cluster={h.get('cluster_id')}")
                print(f"        drift={ev.get('drift_detected')} dir={ev.get('drift_direction')} "
                      f"match={ev.get('direction_match')} normal_ratio={ev.get('normal_ratio')}")
                print(f"        maintenance_ts={ev.get('maintenance_ts')} "
                      f"verdict={verdict_of(h)} token={h.get('reject_token','-')}")
                if not h.get("investigated"):
                    print("        → 갈래: ④ 조사 경로(미조사) — hypothesis.py")
                elif ev.get("drift_detected") in (False, None):
                    print("        → 갈래: 데이터(drift 안 잡힘 — fab.db 신호 또는 suspect 오지정)")
                elif verdict_of(h) != "accepted":
                    print(f"        → 갈래: ⑤ critic 로직({h.get('reject_token')})")
                else:
                    print("        → 채택됨 — 순위 문제(④ 랭킹)")
            # top-1을 두 축으로 본다. 클러스터(unit+direction)는 fab로 구분 불가한 형제
            # 묶음(S2-3)이라, 0위 헤드라인 cause가 정답과 안 맞아도 정답이 #1 클러스터
            # 안에 있으면 근본원인 그룹은 맞힌 것이다. 두 지표를 분리해 기록한다.
            top_cluster = ordered[0].get("cluster_id")
            exact_top1 = ordered[0].get("matched_cause") in true_causes
            cluster_top1 = any(h.get("cluster_id") == top_cluster for _, h in hits)
            print(f"   top-1 적중(exact   = 0위 cause가 정답):        {exact_top1}")
            print(f"   top-1 적중(cluster = 정답이 0위와 같은 클러스터): {cluster_top1}")
            if cluster_top1 and not exact_top1:
                head = ordered[0].get("matched_cause") or ordered[0].get("cause")
                print(f"        → 0위 헤드라인='{head}'(형제), 정답은 같은 클러스터 "
                      f"[{top_cluster}] 안 — fab 구분불가로 순위만 형제에 밀림")
            # 기대 suspect 대조 — cause_sites의 장비와 정답 행의 equipment가 같은가
            exp_eq = [s[0] for s in (gt.get("cause_sites") or [])]
            got_eq = sorted({str(h.get("equipment")) for _, h in hits})
            mismatch = set(got_eq) - set(exp_eq)
            print(f"   기대 장비(cause_sites)={exp_eq} vs 정답 행 장비={got_eq}"
                  + ("  ⚠ 불일치 → commonality가 다른 장비 지목(pre-pass 갭)" if mismatch else "  ✅ 일치"))
    else:
        print(f"① unmatched 시나리오 — 기대 status=unmapped/insufficient, 실제={final['status']}")

    # ② 함정 — (verdict, token)별 집계 + maintenance_ts 보유 현황(P2 재료 유무)
    if traps:
        for t in traps:
            trap_rows = [h for h in ordered if h.get("equipment") == t]
            if not trap_rows:
                print(f"② 함정 {t}: 최종 리스트에 없음(suspect로 지목 안 됨)")
                continue
            agg = Counter((verdict_of(h), h.get("reject_token", "-")) for h in trap_rows)
            print(f"② 함정 {t}: 총 {len(trap_rows)}건")
            for (v, tok), n in agg.most_common():
                ok = "✅" if v in ("rejected", "judge_unknown") else "❌ 살아남음(채택)"
                print(f"     {n:>4}건  {v:13} {str(tok):22} {ok}")
            with_mts = [h["evidence"].get("maintenance_ts") for h in trap_rows
                        if h["evidence"].get("maintenance_ts")]
            print(f"     maintenance_ts 보유: {len(with_mts)}/{len(trap_rows)}건"
                  + (f" (예: {with_mts[0]})" if with_mts else "  ⚠ PM 미수집 → P2 비교 재료 부재"))
    else:
        print("② 함정 없음(이 시나리오)")

    # ③ suspect 확정 여부 (전부 None이면 데이터 정합 문제)
    with_equip = [h for h in ordered if h.get("equipment")]
    print(f"③ suspect 확정: {len(with_equip)}/{len(ordered)}건 "
          f"(0이면 ground truth lot_ids가 fab.db commonality를 안 냄 = 데이터 정합 문제)")

    # ④ firewall
    print(f"   Hypothesis 단계 MCP 콜: {counts['hypothesis']}")
    print(f"   Critic 단계 MCP 콜(firewall — 0이어야): {counts['critic'] or '{} ✅ 재조회 0'}")


if __name__ == "__main__":
    asyncio.run(main())
