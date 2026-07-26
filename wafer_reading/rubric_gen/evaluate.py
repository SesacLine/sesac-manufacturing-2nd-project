"""평가 하네스 — 고정 루브릭으로 VLM 서술을 채점하고 리포트를 낸다 (dev 전용)

듀얼 평가를 한 번에 돌린다:
    ① 결정적 루브릭 지표 (score.py — 항상)
    ② LLM-as-Judge (judge.py — `--judge` opt-in, plain/rubric 모드)

평가 표본은 sampling.py의 eval 풀(루브릭 표본과 불교차)에서 뽑는다.
`vlm_track` 분리 집계로 open vs pty 비교가 부산물로 나온다.

CLI:
    # 실호출 평가 (VLM 그룹 판독 → 채점)
    python -m wafer_reading.rubric_gen.evaluate --samples 4 --track pty --judge
    # 캐시된 VLM output 재채점 (API 호출 0회)
    python -m wafer_reading.rubric_gen.evaluate --from-outputs .../eval_vlm_outputs.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from ..vlm.adapter import VLMReader
from .generate import DEFAULT_GROUP_SIZE, RUBRICS_DIR
from .judge import JUDGE_MODES, LLMJudge
from .models import assert_distinct
from .sampling import DEFAULT_PKL, load_training_df, sample_groups
from .score import FUZZY_THRESHOLD, bleu, rouge_l, score_output
from .schema import PATTERNS

OUTPUTS_DIR = Path(__file__).parent / "outputs"
REPORTS_DIR = Path(__file__).parent / "reports"


def load_fixed_rubrics(rubrics_dir: Path, patterns: list[str]) -> dict[str, dict]:
    rubrics = {}
    for pattern in patterns:
        path = rubrics_dir / f"{pattern}.json"
        if path.exists():
            rubrics[pattern] = json.loads(path.read_text(encoding="utf-8"))
        else:
            print(f"[warn] 고정 루브릭 없음 — 건너뜀: {path} (먼저 generate → merge)")
    return rubrics


def produce_eval_outputs(patterns: list[str], samples: int, pkl: str, track: str | None) -> list[dict]:
    df = load_training_df(pkl)
    reader = VLMReader(track=track)
    outputs = []
    for pattern in patterns:
        for g in sample_groups(df, pattern, "eval", samples, DEFAULT_GROUP_SIZE.get(pattern, 9)):
            print(f"  [vlm] {g['group_id']} ({len(g['maps'])} wafers) ...")
            out = reader.describe_group(pattern, g["maps"], wafer_keys=g["wafer_keys"])
            outputs.append({**out, "group_id": g["group_id"], "pool": "eval"})
    return outputs


def evaluate_outputs(
    outputs: list[dict],
    rubrics: dict[str, dict],
    judge: LLMJudge | None = None,
    judge_modes: tuple[str, ...] = ("rubric",),
    references: dict[str, list[str]] | None = None,
    fuzzy_threshold: float | None = FUZZY_THRESHOLD,
) -> list[dict]:
    """VLM output 리스트 → 항목별 평가 레코드."""
    records = []
    for out in outputs:
        pattern = out.get("pattern_candidate", "")
        rubric = rubrics.get(pattern)
        if rubric is None:
            continue
        record = {"group_id": out.get("group_id"), **score_output(out, rubric, fuzzy_threshold)}

        refs = (references or {}).get(pattern) or []
        if refs:
            cand = out.get("total_description") or ""
            record["aux_metrics"] = {
                "rouge_l_f1": max(rouge_l(cand, r)["f1"] for r in refs),
                "bleu4": max(bleu(cand, r) for r in refs),
                "n_references": len(refs),
            }
        if judge is not None:
            record["judge"] = {m: judge.judge(out, rubric, mode=m) for m in judge_modes}
        records.append(record)
    return records


def aggregate(records: list[dict]) -> dict:
    """패턴별 · 트랙별 집계."""

    def _mean(values: list) -> float | None:
        """채점 불가(None)는 평균에서 제외 — 0으로 대체하면 기준 없는 축이 점수를 깎는다."""
        nums = [v for v in values if v is not None]
        return round(sum(nums) / len(nums), 4) if nums else None

    def _summarize(rows: list[dict]) -> dict:
        n = len(rows)
        if not n:
            return {}
        agg = {
            "n": n,
            "overall": _mean([r["overall"] for r in rows]),
            "hallucination_rate": round(sum(bool(r["hallucinated"]) for r in rows) / n, 4),
        }
        for dim in ("spatial", "morphology"):
            agg[f"{dim}_score"] = _mean([r["dimensions"][dim]["score"] for r in rows])
            agg[f"{dim}_hit_coverage"] = _mean([r["dimensions"][dim]["hit_coverage"] for r in rows])
            agg[f"{dim}_avoid_score"] = _mean([r["dimensions"][dim]["avoid_score"] for r in rows])
        judged = [r for r in rows if r.get("judge")]
        for mode in JUDGE_MODES:
            subset = [r["judge"][mode] for r in judged if mode in r.get("judge", {})]
            if subset:
                agg[f"judge_{mode}_mean"] = round(sum(j["judge_mean"] for j in subset) / len(subset), 4)
                agg[f"judge_{mode}_faithfulness"] = round(
                    sum(j["faithfulness"] for j in subset) / len(subset), 4
                )
        aux = [r["aux_metrics"] for r in rows if r.get("aux_metrics")]
        if aux:
            agg["rouge_l_f1"] = round(sum(a["rouge_l_f1"] for a in aux) / len(aux), 4)
            agg["bleu4"] = round(sum(a["bleu4"] for a in aux) / len(aux), 4)
        return agg

    by_pattern: dict[str, list[dict]] = defaultdict(list)
    by_track: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_pattern[str(r.get("pattern"))].append(r)
        by_track[str(r.get("vlm_track"))].append(r)
    return {
        "overall": _summarize(records),
        "by_pattern": {k: _summarize(v) for k, v in sorted(by_pattern.items())},
        "by_track": {k: _summarize(v) for k, v in sorted(by_track.items())},
    }


def render_markdown(report: dict) -> str:
    """리포트 dict → 사람이 읽는 표(팀 공유용)."""
    meta, agg = report["meta"], report["aggregate"]
    lines = [
        f"# VLM 루브릭 평가 리포트 ({meta['tag']})",
        "",
        f"- 표본: {meta['n_records']}건 · 출처 풀 {meta.get('pools', ['?'])}"
        + ("" if meta.get("pools") == ["eval"]
           else "  ⚠️ **루브릭 표본과 불교차가 아님 — 성능 수치로 인용 금지**"),
        f"- 트랙: {meta['tracks']} / 판정자: {meta['judge_modes'] or '미실행'}"
        f" / fuzzy 임계: {meta.get('fuzzy_threshold') or '끔(정확 매칭만)'}",
        f"- 루브릭: {meta['rubrics']}",
        f"- 모델(역할별): {meta.get('models', {})}",
        "",
        "## 종합",
        "",
        "| 지표 | 값 |",
        "|---|---|",
    ]
    for k, v in agg["overall"].items():
        lines.append(f"| {k} | {v} |")

    for title, block in (("패턴별", agg["by_pattern"]), ("트랙별", agg["by_track"])):
        if not block:
            continue
        keys = sorted({k for row in block.values() for k in row})
        lines += ["", f"## {title}", "", "| 구분 | " + " | ".join(keys) + " |",
                  "|---|" + "---|" * len(keys)]
        for name, row in block.items():
            lines.append(f"| {name} | " + " | ".join(str(row.get(k, "-")) for k in keys) + " |")

    lines += ["", "## 항목별", "",
              "> 점수 `n/a` = 그 축에 must-hit이 없어 **채점 불가**(0점 아님).", "",
              "| group_id | pattern | overall | spatial | morphology | 환각 | 위반 구 |",
              "|---|---|---|---|---|---|---|"]
    for r in report["records"]:
        viol = ", ".join(v for d in r["dimensions"].values() for v in d["violations"]) or "-"
        cells = [r["overall"], r["dimensions"]["spatial"]["score"], r["dimensions"]["morphology"]["score"]]
        s_overall, s_spatial, s_morph = ("n/a" if c is None else str(c) for c in cells)
        lines.append(
            f"| {r.get('group_id')} | {r.get('pattern')} | {s_overall} | {s_spatial} | {s_morph} | "
            f"{'⚠️' if r['hallucinated'] else '-'} | {viol} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="루브릭 기반 VLM 평가 (결정적 지표 + LLM-as-Judge)")
    ap.add_argument("--pkl", default=DEFAULT_PKL)
    ap.add_argument("--patterns", nargs="*", default=list(PATTERNS))
    ap.add_argument("--samples", type=int, default=4, help="패턴당 평가 그룹 수")
    ap.add_argument("--track", default=None, help="VLM 트랙 open|pty (기본: VLM_TRACK env)")
    ap.add_argument("--from-outputs", default=None, help="VLM 재호출 없이 캐시된 jsonl 채점")
    ap.add_argument("--rubrics-dir", default=str(RUBRICS_DIR))
    ap.add_argument("--references", default=None, help='{"Center": ["ref text", ...]} JSON — BLEU/ROUGE용')
    ap.add_argument("--judge", action="store_true", help="LLM-as-Judge 실행(API 호출 발생)")
    ap.add_argument("--judge-modes", nargs="*", default=["rubric"], choices=list(JUDGE_MODES))
    ap.add_argument("--fuzzy-threshold", type=float, default=FUZZY_THRESHOLD,
                    help="구 토큰 커버리지 임계 (0 이하를 주면 fuzzy 끄고 정확 매칭만)")
    ap.add_argument("--tag", default=None, help="리포트 파일 태그(기본: 오늘 날짜)")
    args = ap.parse_args()

    models = assert_distinct(args.track or "pty", judge_used=args.judge)  # 역할 분리 강제(#17)
    print(f"[모델] {models}")

    rubrics = load_fixed_rubrics(Path(args.rubrics_dir), args.patterns)
    if not rubrics:
        raise SystemExit("고정 루브릭이 하나도 없다 — generate → merge를 먼저 돌릴 것")

    if args.from_outputs:
        outputs = [json.loads(line) for line in Path(args.from_outputs).read_text(encoding="utf-8").splitlines() if line.strip()]
        outputs = [o for o in outputs if o.get("pattern_candidate") in args.patterns]
        print(f"[1/3] VLM output {len(outputs)}건 로드(재호출 없음)")
    else:
        print(f"[1/3] VLM 실호출 — {args.patterns} × {args.samples}그룹")
        outputs = produce_eval_outputs(args.patterns, args.samples, args.pkl, args.track)
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        path = OUTPUTS_DIR / "eval_vlm_outputs.jsonl"
        path.write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in outputs), encoding="utf-8")
        print(f"      캐시 저장: {path}")

    references = json.loads(Path(args.references).read_text(encoding="utf-8")) if args.references else None
    judge = LLMJudge() if args.judge else None
    print(f"[2/3] 채점 — 루브릭 {list(rubrics)} / judge={args.judge_modes if judge else '미실행'}")
    fuzzy = args.fuzzy_threshold if args.fuzzy_threshold and args.fuzzy_threshold > 0 else None
    records = evaluate_outputs(
        outputs, rubrics, judge, tuple(args.judge_modes), references, fuzzy
    )

    tag = args.tag or datetime.now().strftime("%m%d")
    report = {
        "meta": {
            "tag": tag,
            "n_records": len(records),
            "tracks": sorted({str(r.get("vlm_track")) for r in records}),
            "judge_modes": args.judge_modes if judge else [],
            # 채점한 표본이 어느 풀에서 왔는지 — rubric 풀이면 자기충족(성능 아님)
            "pools": sorted({str(o.get("pool", "unknown")) for o in outputs}),
            "models": models,
            "fuzzy_threshold": fuzzy,
            "rubrics": {p: f"{r['n_samples']}표본/min_support={r['min_support']}" for p, r in rubrics.items()},
        },
        "aggregate": aggregate(records),
        "records": records,
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / f"report_{tag}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (REPORTS_DIR / f"report_{tag}.md").write_text(render_markdown(report), encoding="utf-8")
    print(f"[3/3] 리포트: {REPORTS_DIR}/report_{tag}.{{json,md}}")
    print(json.dumps(report["aggregate"]["overall"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
