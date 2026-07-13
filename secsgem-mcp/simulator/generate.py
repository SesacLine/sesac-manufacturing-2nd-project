"""데이터 생성 파이프라인 (§4.5)

사용법:
  python -m simulator.generate --wm811k datasets/raw/WM811K.pkl \
      --mw38 datasets/raw/Wafer_Map_Datasets.npz --out datasets --seed 20260101

시드 고정 배치 생성: 같은 인자 → byte-identical 산출물.
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
from preprocess.mw38_loader import load_mw38

EPOCH = datetime(2026, 1, 1)          # 가상 타임라인 기점 (§4.2 단일 타임라인)


def ts(days: float) -> str:
    return (EPOCH + timedelta(days=float(days))).strftime("%Y-%m-%d %H:%M:%S")


def emit_s6f11(equipment_id, ts_, param, value):
    """S6F11(이벤트/트레이스) 표준 SECS-II 메시지 — 원본 로그 보관용."""
    return secs.functions.SecsS06F11({
        "DATAID": 0, "CEID": 1,
        "RPT": [{"RPTID": 1, "V": [equipment_id, ts_, param, float(value)]}],
    })


def emit_s5f1(equipment_id, ts_, alarm_id, text):
    """S5F1(알람)."""
    return secs.functions.SecsS05F01(
        {"ALCD": 0b1000_0001, "ALID": alarm_id, "ALTX": text})


def inject_drift(base_range, model, t_days, t0_days, r):
    """드리프트 어휘 {step_up, step_down, linear_up, linear_down, none} 해석 (§4.3)."""
    lo, hi = base_range
    v = float(r.uniform(lo, hi))
    if model in (None, "none") or t0_days is None or t_days < t0_days:
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
    """lot 1개의 route 통과 이력. override={step: (eq, chamber)} 로 시나리오 강제 배정."""
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
    ap.add_argument("--mw38", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=_seed.GLOBAL_SEED)
    ap.add_argument("--n-single", type=int, default=8)
    ap.add_argument("--n-mixed", type=int, default=2)
    ap.add_argument("--n-unmatched", type=int, default=2)   # §4.4-5: 전체의 10~20%
    ap.add_argument("--n-background", type=int, default=800)
    args = ap.parse_args()
    _seed.GLOBAL_SEED = args.seed                    # CLI 시드가 rng 전체를 지배

    out = pathlib.Path(args.out)
    (out / "raw_secs_logs").mkdir(parents=True, exist_ok=True)
    (out / "ground_truth").mkdir(parents=True, exist_ok=True)

    fab = yaml.safe_load(pathlib.Path("simulator/fab_model.yaml").read_text())
    mapping = yaml.safe_load(pathlib.Path("simulator/mapping_table.yaml").read_text())
    eqmap = equipment_instances(fab)
    days = fab["timeline_days"]

    print("[1/6] WM-811K 로드 ...")
    wm = load_wm811k(args.wm811k)
    labeled = wm[wm.has_label]
    # 패턴별 lot 후보: 해당 라벨 wafer를 2장 이상 가진 lot (§4.2 실제 lot 구조 활용)
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

    print("[2/6] MixedWM38 로드 ...")
    mw = load_mw38(args.mw38)
    pairs = {}                                       # 혼합 조합 → wafer 레코드
    for rec in mw:
        key = tuple(sorted(rec["kg_labels"]))
        if len(key) == 2 and all(k in mapping for k in key):
            pairs.setdefault(key, []).append(rec)
    mix_combos = [k for k, v in sorted(pairs.items()) if len(v) >= 20]
    print(f"      사용 가능 혼합 조합: {mix_combos}")
    if args.n_mixed and not mix_combos:
        raise SystemExit("혼합 조합 부족 — mapping_table 패턴과 MW38 조합이 겹치지 않음")

    # ---------- 시나리오 구성 (§4.4) ----------
    print("[3/6] 시나리오 구성 ...")
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

    sid = 0
    for i in range(args.n_single):                  # 단일 원인 (WM-811K)
        sid += 1
        p = patterns[i % len(patterns)]
        c = pick_cause(p)
        eq, grp = pick_cause_eq(c)
        ch = f"{eq}-CH{int(r.integers(grp['chambers_per_instance'])) + 1}"
        trap_step = next(s for s in fab["route"]
                         if s != c["equipment_group"] and s != "EDS")
        trap_eq = fab["equipment"][trap_step]["instances"][0]
        scenarios.append(dict(
            scenario_id=f"SC-{sid:03d}", patterns=[p], causes=[c], lots=pick_lots(p),
            cause_sites=[(eq, ch)], t0=float(r.uniform(10, days - 20)),
            trap_eq=trap_eq, trap_step=trap_step, unmatched=False, source="wm811k"))
    for i in range(args.n_mixed):                   # 복합 원인 (MixedWM38, §4.4-6)
        sid += 1
        combo = mix_combos[i % len(mix_combos)]
        recs = pairs[combo][:25]
        vlot = f"SVLOT-{sid:03d}"
        for rec in recs:
            rec["lot_id"] = vlot                    # 시나리오 전용 가상 lot
        cs, sites = [], []
        for p in combo:                             # 원인을 서로 다른 장비·시점에 독립 주입
            c = pick_cause(p)
            eq, _ = pick_cause_eq(c)
            cs.append(c)
            sites.append((eq, f"{eq}-CH1"))
        scenarios.append(dict(
            scenario_id=f"SC-{sid:03d}", patterns=list(combo), causes=cs, lots=[vlot],
            cause_sites=sites, t0=float(r.uniform(10, days - 20)),
            trap_eq=fab["equipment"]["LITHO"]["instances"][0], trap_step="LITHO",
            unmatched=False, source="mw38", mw_records=recs))
    for i in range(args.n_unmatched):               # 매칭불가 (P7): 원인 미주입
        sid += 1
        p = patterns[i % len(patterns)]
        scenarios.append(dict(
            scenario_id=f"SC-{sid:03d}", patterns=[p], causes=[], lots=pick_lots(p, 6),
            cause_sites=[], t0=None, trap_eq=None, trap_step=None,
            unmatched=True, source="wm811k"))

    # ---------- DB 기록 ----------
    print("[4/6] lot 이력·wafer 기록 ...")
    con = build_db(out / "fab.db")
    r = rng("timeline")
    hist, wrows = [], []

    for lot in bg_lots:                             # 배경 물량 (P3 negative evidence 모수)
        hist += schedule_lot(lot, float(r.uniform(0, days - 2)), fab, eqmap)
        for _, w in wm[wm.lot_id == lot].iterrows():
            wrows.append(("wm811k", lot, w.wafer_id, None, w.dieSize, 1))

    drifts = {}                                     # (equipment_id, param) -> (model, t0)
    drift_owner, clue_lost = {}, set()              # 충돌 시 앞 시나리오의 단서가 소실됨
    for sc in scenarios:
        for lot in sc["lots"]:
            override = {}
            if not sc["unmatched"]:
                for c, (eq, ch) in zip(sc["causes"], sc["cause_sites"]):
                    override[c["equipment_group"]] = (eq, ch)      # 지지: commonality (§4.4-1)
                override[sc["trap_step"]] = (sc["trap_eq"],
                                             f"{sc['trap_eq']}-CH1")  # 함정: 공유하지만 무죄인 장비
                start = sc["t0"] + float(r.uniform(0.2, 7))        # 지지: 원인 이벤트 직후 (선후관계)
            else:
                start = float(r.uniform(0, days - 2))
            hist += schedule_lot(lot, start, fab, eqmap, override)
            if sc["source"] == "wm811k":
                for _, w in wm[wm.lot_id == lot].iterrows():
                    wrows.append(("wm811k", lot, w.wafer_id,
                                  _blob(w.waferMap), w.dieSize, int(w.is_normal)))
        if sc["source"] == "mw38":
            for rec in sc["mw_records"]:
                wrows.append(("mw38", rec["lot_id"], rec["wafer_id"],
                              _blob(rec["waferMap"]), None, int(rec["is_normal"])))
        for c, (eq, _) in zip(sc["causes"], sc["cause_sites"]):
            sig = c["telemetry_signature"]
            if sig["param"] not in (None, "none"):
                key = (eq, sig["param"])
                if key in drifts:
                    clue_lost.add(drift_owner[key])
                    print(f"      경고: 드리프트 충돌 {key} — "
                          f"{drift_owner[key]}의 단서가 {sc['scenario_id']}에 덮임")
                drifts[key] = (sig["drift"], sc["t0"])
                drift_owner[key] = sc["scenario_id"]
    con.executemany("INSERT OR IGNORE INTO wafer VALUES(?,?,?,?,?,?)", wrows)
    con.executemany("INSERT INTO lot_history VALUES(?,?,?,?,?,?,?)", hist)

    print("[5/6] 텔레메트리·알람·정비·지표 ...")
    tel, alarms, maint, events = [], [], [], []
    for step, spec in fab["equipment"].items():
        for eq in spec["instances"]:
            re_ = rng("tel", eq)
            for param, ps in spec["params"].items():
                model, t0 = drifts.get((eq, param), (None, None))
                for k in range(days * 12):          # 2시간 간격
                    t = k / 12
                    tel.append((eq, ts(t), param,
                                inject_drift(ps["normal"], model, t, t0, re_)))
            mspec = spec["maintenance"]
            for k in range(int(days // mspec["pm_interval_days"])):   # 정기 PM
                t = (k + 1) * mspec["pm_interval_days"] + float(re_.uniform(-1, 1))
                maint.append((eq, ts(t), "PM", "정기 소모품 교체"))
                events.append((eq, ts(t), "PM", "정기 PM"))
            for d in range(days):                   # 교란: 무작위 BM·알람 (§4.4-3)
                if re_.uniform() < mspec["bm_rate_per_day"]:
                    maint.append((eq, ts(d + 0.3), "BM", "돌발 수리"))
                    events.append((eq, ts(d + 0.3), "BM", "돌발 BM"))
                if re_.uniform() < 0.08:
                    alarms.append((eq, None, ts(d + float(re_.uniform(0, 1))),
                                   int(1000 + re_.integers(50)), "minor interlock warning"))
    for sc in scenarios:                            # 시나리오 신호 주입
        if sc["unmatched"]:
            continue
        for c, (eq, ch) in zip(sc["causes"], sc["cause_sites"]):
            maint.append((eq, ts(sc["t0"]), "BM", f"{c['cause']} 관련 부품 교체"))
            events.append((eq, ts(sc["t0"]), "BM", "부품 교체 후 재가동"))
            for j in range(3):                      # 지지: 원인 시점 알람 (§4.4-1)
                alarms.append((eq, None, ts(sc["t0"] + 0.5 + j), 3000 + j,
                               f"{c['telemetry_signature']['param']} out of range"))
        maint.append((sc["trap_eq"], ts(sc["t0"] + 12), "PM",
                      "정기 소모품 교체"))          # 함정: 불량 이후 PM (§4.4-2 선후 뒤집힘)
        events.append((sc["trap_eq"], ts(sc["t0"] + 12), "PM", "정기 PM"))
    resolve_lot = alarm_lot_resolver(hist)          # 알람 ↔ lot 처리 구간 연결 (§4.4-1)
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

    print("[6/6] SECS 원본 로그·ground truth ...")
    fallback = 0
    with open(out / "raw_secs_logs" / "alarm_s5f1.log", "w") as f:
        for eq, _lot, t, aid, txt in alarms:
            try:
                body = str(emit_s5f1(eq, t, aid, txt)).replace("\n", " ")
            except Exception:
                fallback += 1
                body = f"S5F1 ALID={aid} ALTX={txt}"
            f.write(f"{t} {eq} {body}\n")
    with open(out / "raw_secs_logs" / "trace_s6f11.log", "w") as f:
        for (eq, param), (model, t0) in sorted(drifts.items()):
            re_ = rng("log", eq, param)
            for k in range(60):                     # 드리프트 구간 표본
                t = t0 + k / 12
                v = inject_drift((0, 1), model, t, t0, re_)
                try:
                    body = str(emit_s6f11(eq, ts(t), param, v)).replace("\n", " ")
                except Exception:
                    fallback += 1
                    body = f"S6F11 {param}={v:.4f}"
                f.write(f"{ts(t)} {eq} {body}\n")
    if fallback:
        print(f"      경고: secsgem 인코딩 실패 {fallback}건 → 텍스트 라인으로 대체 기록")

    for sc in scenarios:                            # 정답 카드 — 서버 미접근 (§4.5)
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
                [f"maintenance BM @ t0 → telemetry {c['telemetry_signature']['param']} "
                 f"{c['telemetry_signature']['drift']}" for c in sc["causes"]],
            "telemetry_clues": [] if sc["unmatched"] else
                [{"equipment": eq, "param": c["telemetry_signature"]["param"],
                  "drift": c["telemetry_signature"]["drift"]}
                 for c, (eq, _) in zip(sc["causes"], sc["cause_sites"])
                 if c["telemetry_signature"]["param"] not in (None, "none")],
            "clue_overwritten": sc["scenario_id"] in clue_lost,  # true면 채점 제외 대상
            "traps_to_reject": [] if sc["unmatched"] else
                [f"{sc['trap_eq']}: 정상 lot 다수 통과(P3), t0+12d PM은 불량 이후(선후 뒤집힘)"],
        }
        (out / "ground_truth" / f"{sc['scenario_id']}.json").write_text(
            json.dumps(card, ensure_ascii=False, sort_keys=True, indent=2))

    con.close()
    print(f"완료: 배경 lot {len(bg_lots)} + 시나리오 lot {len(defect_lots)}, "
          f"시나리오 {len(scenarios)}개(매칭불가 {args.n_unmatched}), "
          f"telemetry {len(tel)}행, alarm {len(alarms)}건 → {out}/fab.db")


if __name__ == "__main__":
    main()
