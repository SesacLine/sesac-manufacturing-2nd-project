"""데이터 생성 파이프라인

사용법:
  python -m simulator.generate --wm811k datasets/raw/WM811K.pkl --out datasets --seed 20260101

시드 고정 배치 생성: 같은 인자 -> byte-identical 산출물
산출물: <out>/fab.db, <out>/raw_secs_logs/, <out>/ground_truth/ (서버는 ground_truth 미접근)
"""
import argparse, io, json, pathlib, sqlite3
from datetime import datetime, timedelta

import numpy as np
import yaml

import secsgem.secs as secs
from server import _seed
from server._seed import rng
from preprocess.wm811k_loader import load_wm811k

EPOCH = datetime(2026, 1, 1) # 가상 타임라인 기점


def ts(days: float) -> str:
    return (EPOCH + timedelta(days=float(days))).strftime("%Y-%m-%d %H:%M:%S")


def emit_s6f11(equipment_id, ts_, param, value):
    """S6F11(이벤트/트레이스) 표준 SECS-II 메시지 — 원본 로그 보관용"""
    return secs.functions.SecsS06F11({
        "DATAID": 0, "CEID": 1,
        "RPT": [{"RPTID": 1, "V": [equipment_id, ts_, param, float(value)]}],
    })


def emit_s5f1(equipment_id, ts_, alarm_id, text):
    """S5F1(알람)"""
    return secs.functions.SecsS05F01(
        {"ALCD": 0b1000_0001, "ALID": alarm_id, "ALTX": text})


def inject_drift(base_range, model, t_days, t0_days, r, t_end_days=None):
    """드리프트 어휘 {step_up, step_down, linear_up, linear_down, none} 해석.
    t_end_days 이후는 정상 복귀 — 종결 이벤트(소모품 교체 등)가 있는 원인용."""
    lo, hi = base_range
    v = float(r.uniform(lo, hi))
    if model in (None, "none") or t0_days is None or t_days < t0_days:
        return v
    if t_end_days is not None and t_days >= t_end_days:
        return v
    span = hi - lo
    if model == "step_up":     return v + 0.15 * span
    if model == "step_down":   return v - 0.15 * span
    if model == "linear_up":   return v + 0.05 * span * (t_days - t0_days)
    if model == "linear_down": return v - 0.05 * span * (t_days - t0_days)
    return v


def _blob(arr) -> bytes:
    buf = io.BytesIO()
    np.save(buf, np.asarray(arr, dtype=np.uint8), allow_pickle=False)
    return buf.getvalue()


def build_db(path: pathlib.Path) -> sqlite3.Connection:
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript("""
    PRAGMA journal_mode=MEMORY;
    CREATE TABLE wafer(source TEXT, lot_id TEXT, wafer_id TEXT,
        die_map BLOB, die_size REAL, is_normal INT,
        PRIMARY KEY(lot_id, wafer_id));
    CREATE TABLE lot_history(lot_id TEXT, step TEXT, equipment_id TEXT,
        chamber TEXT, recipe_id TEXT, ts_in TEXT, ts_out TEXT);
    CREATE TABLE telemetry(equipment_id TEXT, ts TEXT, param TEXT, value REAL);
    CREATE TABLE alarm(equipment_id TEXT, lot_id TEXT, ts TEXT, alarm_id INT, text TEXT);
    CREATE TABLE maintenance(equipment_id TEXT, ts TEXT, type TEXT, parts TEXT);
    CREATE TABLE metric_series(metric TEXT, scope TEXT, ts TEXT, value REAL);
    CREATE TABLE event_log(scope TEXT, ts TEXT, kind TEXT, detail TEXT);
    CREATE INDEX ix_hist_lot ON lot_history(lot_id);
    CREATE INDEX ix_hist_eq ON lot_history(equipment_id, ts_in);
    CREATE INDEX ix_tel ON telemetry(equipment_id, ts);
    CREATE INDEX ix_alarm ON alarm(equipment_id, ts);
    """)
    return con


def equipment_instances(fab):
    """{step: [(equipment_id, [chamber...]), ...]}"""
    return {step: [(eq, [f"{eq}-CH{c + 1}" for c in range(spec["chambers_per_instance"])])
                   for eq in spec["instances"]]
            for step, spec in fab["equipment"].items()}


def schedule_lot(lot_id, start_day, fab, eqmap, override=None):
    """lot 1개의 route 통과 이력. override={step: (eq, chamber)} 로 시나리오 강제 배정"""
    r = rng("route", lot_id)
    rows, t = [], start_day
    for step in fab["route"]:
        eq, chambers = eqmap[step][int(r.integers(len(eqmap[step])))]
        ch = chambers[int(r.integers(len(chambers)))]
        if override and step in override:
            eq, ch = override[step]
        dur = float(r.uniform(1, 3)) / 24           # 1~3h
        rows.append((lot_id, step, eq, ch,
                     f"RCP-{step}-{int(r.integers(1, 4))}", ts(t), ts(t + dur)))
        t += dur + float(r.uniform(0.5, 2)) / 24    # 대기 0.5~2h
    return rows


def alarm_lot_resolver(hist):
    """장비별 lot 처리 구간 색인 → 알람 발생 시각이 포함되는 lot_id 반환.
    어느 구간에도 안 들면 None(장비 유휴 중 알람)."""
    windows = {}
    for lot_id, _step, eq, _ch, _rcp, ts_in, ts_out in hist:
        windows.setdefault(eq, []).append((ts_in, ts_out, lot_id))
    for w in windows.values():
        w.sort()

    def resolve(eq, t):
        hit = None
        for ts_in, ts_out, lot_id in windows.get(eq, ()):
            if ts_in > t:
                break
            if t <= ts_out:
                hit = lot_id                # 구간이 겹치면 가장 늦게 투입된 lot
        return hit
    return resolve


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wm811k", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=_seed.GLOBAL_SEED)
    ap.add_argument("--n-single", type=int, default=9)   # 3클래스 × 원인 3종 커버
    ap.add_argument("--n-unmatched", type=int, default=2)   # 전체의 10~20%
    ap.add_argument("--n-background", type=int, default=800)
    # 라벨 웨이퍼의 split 제한 — 기본 Test (CNN이 Training으로 학습되므로 누출 차단, 07-23 팀 결정)
    ap.add_argument("--labeled-split", default="Test", choices=["Test", "Training", "all"])
    args = ap.parse_args()
    _seed.GLOBAL_SEED = args.seed

    out = pathlib.Path(args.out)
    (out / "raw_secs_logs").mkdir(parents=True, exist_ok=True)
    (out / "ground_truth").mkdir(parents=True, exist_ok=True)
    for stale in (out / "ground_truth").glob("*.json"):
        stale.unlink()                               # 이전 빌드 정답 카드 잔류 방지

    fab = yaml.safe_load(pathlib.Path("simulator/fab_model.yaml").read_text(encoding="utf-8"))
    mapping = yaml.safe_load(pathlib.Path("simulator/mapping_table.yaml").read_text(encoding="utf-8"))
    eqmap = equipment_instances(fab)
    days = fab["timeline_days"]

    print(f"[1/5] WM-811K 로드 (labeled_split={args.labeled_split}) ...")
    wm = load_wm811k(
        args.wm811k,
        labeled_split=None if args.labeled_split == "all" else args.labeled_split,
    )
    wm = wm[wm.scope != "excluded"]                  # 제외된 6클래스 타임라인 미유입
    labeled = wm[wm.has_label]
    # 패턴별 lot 후보: 해당 라벨 wafer를 2장 이상 가진 lot (실제 lot 구조 활용)
    pat_lots = {p: (labeled[labeled.kg_label == p].groupby("lot_id").size()
                    .loc[lambda s: s >= 2].index.tolist()) for p in mapping}
    normal_lots_all = sorted(labeled.groupby("lot_id")
                             .filter(lambda g: g.is_normal.all())["lot_id"].unique())
    r = rng("sample", "background")
    idx = r.choice(len(normal_lots_all),
                   size=min(args.n_background, len(normal_lots_all)), replace=False)
    bg_lots = [normal_lots_all[i] for i in idx]
    print(f"      패턴별 lot 후보 { {p: len(v) for p, v in pat_lots.items()} }, "
          f"배경 정상 lot {len(bg_lots)}")

    # ---------- 시나리오 구성 ----------
    print("[2/5] 시나리오 구성 ...")
    scenarios, used = [], set()
    patterns = sorted(mapping)
    r = rng("scenario", "plan")

    def pick_lots(pattern, n=8):
        cand = [l for l in pat_lots[pattern] if l not in used]
        sel = [cand[i] for i in r.choice(len(cand), size=min(n, len(cand)), replace=False)]
        used.update(sel)
        return sel

    used_sites = set()                              # (equipment_id, param) — 드리프트 덮어쓰기 방지

    def has_free_site(c):
        param = c["telemetry_signature"]["param"]
        return param in (None, "none") or any(
            (e, param) not in used_sites
            for e in fab["equipment"][c["equipment_group"]]["instances"])

    def pick_cause(pattern):
        """확률 가중 원인 추첨. 주입 지점이 소진된 원인은 제외하고 재추첨 —
        모든 원인이 소진됐을 때만 충돌을 허용한다(주입부 안전망이 카드에 기록)."""
        causes = list(mapping[pattern])
        while causes:
            probs = np.array([c["prob"] for c in causes])
            c = causes[int(r.choice(len(causes), p=probs / probs.sum()))]
            if has_free_site(c):
                return c
            causes.remove(c)
        causes = mapping[pattern]
        probs = np.array([c["prob"] for c in causes])
        return causes[int(r.choice(len(causes), p=probs / probs.sum()))]

    def pick_cause_eq(c):
        """원인 장비 선택. 이미 드리프트가 심긴 (장비, 파라미터)는 피한다.
        모든 인스턴스가 사용 중이면 그대로 허용 — 주입부 안전망이 카드에 기록."""
        grp = fab["equipment"][c["equipment_group"]]
        param = c["telemetry_signature"]["param"]
        if param in (None, "none"):                 # 드리프트 없음 → 충돌 개념 없음
            return grp["instances"][int(r.integers(len(grp["instances"])))], grp
        pool = [e for e in grp["instances"] if (e, param) not in used_sites] \
            or grp["instances"]
        eq = pool[int(r.integers(len(pool)))]
        used_sites.add((eq, param))
        return eq, grp

    seq = {}                                        # 패턴 슬러그별 일련번호 — 의미 기반 시나리오 ID
    def scenario_id(slug):
        seq[slug] = seq.get(slug, 0) + 1
        return f"SC-{slug}-{seq[slug]:02d}"

    for i in range(args.n_single):                  # 단일 원인 (WM-811K)
        p = patterns[i % len(patterns)]
        c = pick_cause(p)
        eq, grp = pick_cause_eq(c)
        ch = f"{eq}-CH{int(r.integers(grp['chambers_per_instance'])) + 1}"
        trap_step = next(s for s in fab["route"]
                         if s != c["equipment_group"] and s != "EDS")
        trap_eq = fab["equipment"][trap_step]["instances"][0]
        t0_lo = 26 if c.get("shape") == "consumable_wear" else 10   # 아크: 수명 누적 구간(~23일) 선행 확보
        scenarios.append(dict(
            scenario_id=scenario_id(p.upper()), patterns=[p], causes=[c], lots=pick_lots(p),
            cause_sites=[(eq, ch)], t0=float(r.uniform(t0_lo, days - 20)),
            trap_eq=trap_eq, trap_step=trap_step, unmatched=False, source="wm811k"))
    for i in range(args.n_unmatched):               # 매칭불가: 원인 미주입
        p = patterns[i % len(patterns)]
        scenarios.append(dict(
            scenario_id=scenario_id("UNMATCHED"), patterns=[p], causes=[], lots=pick_lots(p, 6),
            cause_sites=[], t0=None, trap_eq=None, trap_step=None,
            unmatched=True, source="wm811k"))

    # ---------- DB 기록 ----------
    print("[3/5] lot 이력·wafer 기록 ...")
    con = build_db(out / "fab.db")
    r = rng("timeline")
    hist, wrows = [], []

    for lot in bg_lots:                             # 배경 물량 (negative evidence 모수)
        hist += schedule_lot(lot, float(r.uniform(0, days - 2)), fab, eqmap)
        for _, w in wm[wm.lot_id == lot].iterrows():
            wrows.append(("wm811k", lot, w.wafer_id, None, w.dieSize, 1))

    drifts = {}                                     # (equipment_id, param) -> (model, t0, t_end)
    arcs = {}                                       # equipment_id -> (직전 교체, 종결 교체) — 소모품 수명 아크
    gaps = {}                                       # equipment_id -> (시작, 끝) — 텔레메트리 결측 창 (C2)
    drift_owner, clue_lost = {}, set()              # 충돌 시 앞 시나리오의 단서가 소실됨
    for sc in scenarios:
        for lot in sc["lots"]:
            override = {}
            if not sc["unmatched"]:
                for c, (eq, ch) in zip(sc["causes"], sc["cause_sites"]):
                    override[c["equipment_group"]] = (eq, ch)      # 지지: commonality
                override[sc["trap_step"]] = (sc["trap_eq"],
                                             f"{sc['trap_eq']}-CH1")  # 함정: 공유하지만 무죄인 장비
                start = sc["t0"] + float(r.uniform(0.2, 7))        # 지지: 원인 이벤트 직후 (선후관계)
            else:
                start = float(r.uniform(0, days - 2))
            hist += schedule_lot(lot, start, fab, eqmap, override)
            for _, w in wm[wm.lot_id == lot].iterrows():
                wrows.append(("wm811k", lot, w.wafer_id,
                              _blob(w.waferMap), w.dieSize, int(w.is_normal)))
        for c, (eq, _) in zip(sc["causes"], sc["cause_sites"]):
            sig = c["telemetry_signature"]
            if sig["param"] in (None, "none"):
                continue
            key = (eq, sig["param"])
            if key in drift_owner:
                clue_lost.add(drift_owner[key])
                print(f"      경고: 드리프트 충돌 {key} — "
                      f"{drift_owner[key]}의 단서가 {sc['scenario_id']}에 덮임")
            drift_owner[key] = sc["scenario_id"]
            if c.get("shape") == "consumable_wear":
                # 수명 아크: inject_drift 대신 카운터 리셋 억제로 실현.
                # t0 = 수명 초과 시점, 직전 교체는 (상한/일일누적률)일 전, 종결 교체는 t0+9d.
                ps = fab["equipment"][c["equipment_group"]]["params"][sig["param"]]
                life = ps["normal"][1] / ps["counter_rate_per_day"]
                arc = (sc["t0"] - life, sc["t0"] + 9.0)
                sc.setdefault("arcs", {})[eq] = arc  # 시나리오 소유 스냅숏 — 카드·정비 이력의 원천
                arcs[eq] = arc                       # 텔레메트리는 최종 아크만 실현 (덮인 쪽은 clue_overwritten)
            else:
                drifts[key] = (sig["drift"], sc["t0"], None)
        for c, (eq, _) in zip(sc["causes"], sc["cause_sites"]):
            if c["telemetry_signature"]["param"] not in (None, "none"):
                if eq not in gaps:                  # 결측 창(C2): 원인 장비 텔레메트리 1~2일 결손
                    g0 = sc["t0"] + float(r.uniform(2.5, 6.0))
                    gaps[eq] = (g0, g0 + float(r.uniform(1.0, 2.0)))
                    sc["gap"] = (eq, *gaps[eq])
                break
    con.executemany("INSERT OR IGNORE INTO wafer VALUES(?,?,?,?,?,?)", wrows)
    con.executemany("INSERT INTO lot_history VALUES(?,?,?,?,?,?,?)", hist)

    print("[4/5] 텔레메트리·알람·정비·지표 ...")
    tel, alarms, maint, events = [], [], [], []
    for step, spec in fab["equipment"].items():
        for eq in spec["instances"]:
            re_ = rng("tel", eq)
            arc = arcs.get(eq)                      # 소모품 수명 아크 (직전 교체, 종결 교체)
            gap = gaps.get(eq)                      # 결측 창 (C2)
            mspec = spec["maintenance"]
            pm_times = []
            for k in range(int(days // mspec["pm_interval_days"])):   # 정기 PM
                t = (k + 1) * mspec["pm_interval_days"] + float(re_.uniform(-1, 1))
                if arc and arc[0] < t < arc[1]:
                    continue                        # 아크 구간: 정기 교체 누락 — 수명 초과 상황 연출
                pm_times.append(t)
                maint.append((eq, ts(t), "PM", "정기 소모품 교체"))
                events.append((eq, ts(t), "PM", "정기 PM"))
            resets = sorted(pm_times + (list(arc) if arc else []))    # 카운터 리셋 시점
            for param, ps in spec["params"].items():
                model, t0, t_end = drifts.get((eq, param), (None, None, None))
                rate = ps.get("counter_rate_per_day")
                lo, hi = ps["normal"]
                was_out, n_alarm = False, 0
                for k in range(days * 12):          # 2시간 간격
                    t = k / 12
                    if gap and gap[0] <= t < gap[1]:
                        continue                    # 결측 창 — 포인트 미기록 (coverage.missing 근거)
                    if rate is not None:            # 소모품 카운터: 마지막 교체 이후 누적
                        last = max((x for x in resets if x <= t), default=0.0)
                        v = max(0.0, rate * (t - last) + float(re_.uniform(-2, 2)))
                    else:
                        v = inject_drift(ps["normal"], model, t, t0, re_, t_end)
                    tel.append((eq, ts(t), param, v))
                    oob = not (lo <= v <= hi)
                    if oob and not was_out and n_alarm < 6:   # 임계 교차(상승 에지) 알람 — 드리프트에 후행
                        alarms.append((eq, None, ts(t), 3000 + n_alarm,
                                       f"{param} out of range"))
                        n_alarm += 1
                    was_out = oob
            for d in range(days):                   # 교란: 무작위 BM/알람
                if re_.uniform() < mspec["bm_rate_per_day"]:
                    maint.append((eq, ts(d + 0.3), "BM", "돌발 수리"))
                    events.append((eq, ts(d + 0.3), "BM", "돌발 BM"))
                if re_.uniform() < 0.08:
                    alarms.append((eq, None, ts(d + float(re_.uniform(0, 1))),
                                   int(1000 + re_.integers(50)), "minor interlock warning"))
    for sc in scenarios:                            # 시나리오 신호 주입 (알람은 임계 교차로 위에서 생성)
        if sc["unmatched"]:
            continue
        for c, (eq, ch) in zip(sc["causes"], sc["cause_sites"]):
            # parts 텍스트는 T7이 그대로 반환 — 원인 ID 대신 부품명만 기록 (정답 누출 방지)
            if c.get("shape") == "consumable_wear":  # 수명 아크: 직전 교체·종결 교체 이력
                t_prev, t_repl = sc["arcs"][eq]      # 전역 arcs는 뒤 시나리오에 덮일 수 있음
                maint.append((eq, ts(t_prev), "BM", f"소모품 교체: {c['part']}"))
                maint.append((eq, ts(t_repl), "BM", f"소모품 교체: {c['part']}"))
                events.append((eq, ts(t_prev), "BM", "소모품 교체"))
                events.append((eq, ts(t_repl), "BM", "소모품 교체(불량 종결)"))
            elif c.get("maint_event", True):        # 이벤트형 원인: t0 정비 기록
                maint.append((eq, ts(sc["t0"]), "BM", f"부품 교체: {c['part']}"))
                events.append((eq, ts(sc["t0"]), "BM", "부품 교체 후 재가동"))
            # maint_event: false → 무이벤트 누적형: 단서는 T5 드리프트 + T8 변화점뿐
        maint.append((sc["trap_eq"], ts(sc["t0"] + 12), "PM",
                      "정기 소모품 교체"))          # 함정: 불량 이후 PM (선후 뒤집힘)
        events.append((sc["trap_eq"], ts(sc["t0"] + 12), "PM", "정기 PM"))
    resolve_lot = alarm_lot_resolver(hist)          # 알람 ↔ lot 처리 구간 연결
    alarms = [(eq, resolve_lot(eq, t), t, aid, txt)
              for eq, _, t, aid, txt in alarms]
    con.executemany("INSERT INTO telemetry VALUES(?,?,?,?)", tel)
    con.executemany("INSERT INTO alarm VALUES(?,?,?,?,?)", alarms)
    con.executemany("INSERT INTO maintenance VALUES(?,?,?,?)", maint)
    con.executemany("INSERT INTO event_log VALUES(?,?,?,?)", events)

    # 일별 수율 지표 (detect_change_points 대상): 장비별 defect lot 비율에서 산출
    defect_lots = {l for sc in scenarios for l in sc["lots"]}
    agg = {}
    for h in hist:
        key = (h[2], h[5][:10])                     # (equipment_id, 날짜)
        nt, nd = agg.get(key, (0, 0))
        agg[key] = (nt + 1, nd + (h[0] in defect_lots))
    con.executemany("INSERT INTO metric_series VALUES(?,?,?,?)",
                    [("yield", eq, day, 1.0 - nd / nt)
                     for (eq, day), (nt, nd) in sorted(agg.items())])
    con.commit()

    print("[5/5] SECS 원본 로그·ground truth ...")
    fallback = 0
    with open(out / "raw_secs_logs" / "alarm_s5f1.log", "w", encoding="utf-8") as f:
        for eq, _lot, t, aid, txt in alarms:
            try:
                body = str(emit_s5f1(eq, t, aid, txt)).replace("\n", " ")
            except Exception:
                fallback += 1
                body = f"S5F1 ALID={aid} ALTX={txt}"
            f.write(f"{t} {eq} {body}\n")
    with open(out / "raw_secs_logs" / "trace_s6f11.log", "w", encoding="utf-8") as f:
        for (eq, param), (model, t0, t_end) in sorted(drifts.items()):
            re_ = rng("log", eq, param)
            for k in range(60):                     # 드리프트 구간 표본
                t = t0 + k / 12
                v = inject_drift((0, 1), model, t, t0, re_, t_end)
                try:
                    body = str(emit_s6f11(eq, ts(t), param, v)).replace("\n", " ")
                except Exception:
                    fallback += 1
                    body = f"S6F11 {param}={v:.4f}"
                f.write(f"{ts(t)} {eq} {body}\n")
    if fallback:
        print(f"      경고: secsgem 인코딩 실패 {fallback}건 → 텍스트 라인으로 대체 기록")

    def _evidence(c):
        p, d = c["telemetry_signature"]["param"], c["telemetry_signature"]["drift"]
        if c.get("shape") == "consumable_wear":
            return f"수명 초과 @ t0 → {p} 정상 상한 초과, t0+9d 교체로 종결 (교체≠원인)"
        if not c.get("maint_event", True):
            return f"무이벤트 누적형 → telemetry {p} {d} (시작점 근거는 T8 변화점)"
        return f"maintenance BM @ t0 → telemetry {p} {d}"

    for sc in scenarios:                            # 정답 카드 — 서버 미접근
        card = {
            "scenario_id": sc["scenario_id"],
            "defect_patterns": sc["patterns"],
            "lot_ids": sc["lots"],
            "source": sc["source"],
            "is_unmatched": sc["unmatched"],
            "true_root_causes": [c["cause"] for c in sc["causes"]],
            "cause_sites": sc["cause_sites"],
            "t0": ts(sc["t0"]) if sc["t0"] is not None else None,
            "key_evidence_path": [] if sc["unmatched"] else
                [f"commonality → {eq}/{ch}" for eq, ch in sc["cause_sites"]] +
                [_evidence(c) for c in sc["causes"]],
            "coverage_gap": None if "gap" not in sc else {
                "equipment": sc["gap"][0],
                "from": ts(sc["gap"][1]), "to": ts(sc["gap"][2])},
            "lifecycle": [
                {"equipment": eq, "prev_replacement": ts(sc["arcs"][eq][0]),
                 "life_exceeded": ts(sc["t0"]), "replacement": ts(sc["arcs"][eq][1])}
                for c, (eq, _) in zip(sc["causes"], sc["cause_sites"])
                if c.get("shape") == "consumable_wear"],
            "telemetry_clues": [] if sc["unmatched"] else
                [{"equipment": eq, "param": c["telemetry_signature"]["param"],
                  "drift": c["telemetry_signature"]["drift"]}
                 for c, (eq, _) in zip(sc["causes"], sc["cause_sites"])
                 if c["telemetry_signature"]["param"] not in (None, "none")],
            "clue_overwritten": sc["scenario_id"] in clue_lost,  # true면 채점 제외 대상
            "traps_to_reject": [] if sc["unmatched"] else
                [f"{sc['trap_eq']}: 정상 lot 다수 통과, t0+12d PM은 불량 이후(선후 뒤집힘)"] +
                [f"{eq}: 종결 교체(t0+9d)를 원인으로 오독 금지 — 불량은 교체 '직전' 집중"
                 for c, (eq, _) in zip(sc["causes"], sc["cause_sites"])
                 if c.get("shape") == "consumable_wear"],
        }
        (out / "ground_truth" / f"{sc['scenario_id']}.json").write_text(
            json.dumps(card, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")

    con.close()
    print(f"완료: 배경 lot {len(bg_lots)} + 시나리오 lot {len(defect_lots)}, "
          f"시나리오 {len(scenarios)}개(매칭불가 {args.n_unmatched}), "
          f"telemetry {len(tel)}행, alarm {len(alarms)}건 → {out}/fab.db")


if __name__ == "__main__":
    main()


# 실행 스크립트
# python -m simulator.generate \
#   --wm811k datasets/raw/WM811K.pkl \
#   --out    datasets --seed 20260101