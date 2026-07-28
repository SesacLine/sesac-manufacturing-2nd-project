"""의미 진입 코사인 하한(`KG_SEMANTIC_MIN_SCORE`) 보정 — 임베딩 모델을 바꿀 때 쓴다.

왜 필요한가
-----------
`semantic_entry.MIN_MATCH_SCORE`는 "이보다 덜 닮으면 진입 시그니처로 인정하지 않는" 문턱이다.
**코사인 점수 분포는 모델마다 다르다.** 그대로 물려받으면 오답이 문턱을 넘거나(환각 억제 실패)
정답이 통째로 잘린다(의미 진입 무력화). 그래서 `MIN_MATCH_SCORE_BY_MODEL`은 실측한 모델만
싣고, 표에 없으면 "미보정" 경고를 띄운다. 이 스크립트가 그 실측을 만든다.

무엇을 재는가
-------------
시그니처마다 VLM이 낼 법한 관측 문장(프로브)을 여러 개 두고, 각 프로브에 대해
  - **정답 점수** = 그 프로브가 가리키는 시그니처와의 코사인
  - **오답 상위** = 나머지 시그니처 중 가장 높은 코사인
을 잰다. 문턱은 이 둘 사이에 있어야 한다. 두 분포가 겹치면(정답 최소 < 오답 최대)
어떤 문턱을 골라도 완벽히 못 가르므로, 그 사실 자체를 출력한다.

`--negatives`로 **아무 시그니처와도 무관해야 하는** 문장도 함께 재서, 문턱이 "무관 관측을
걸러내는" 역할을 실제로 하는지 본다(하한의 원래 목적).

인덱스 재빌드가 필요 없는 이유
------------------------------
시그니처의 매칭용 **텍스트**는 모델과 무관하다(그래프에서 모은 서술). 이 스크립트는
기존 인덱스 파일에서 그 텍스트만 꺼내 **대상 모델로 다시 임베딩**한다. 그래서 모델을
바꿔가며 비교해도 `7_build_signature_index.py`를 매번 돌릴 필요가 없다.

사용
----
    python kg_rca/tools/calibrate_semantic_threshold.py
    python kg_rca/tools/calibrate_semantic_threshold.py --models text-embedding-3-small,text-embedding-3-large
    python kg_rca/tools/calibrate_semantic_threshold.py --json   # 기계 판독용

결과의 `제안 문턱`을 `semantic_entry.MIN_MATCH_SCORE_BY_MODEL`에 실측 주석과 함께 넣는다.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

INDEX_PATH = REPO_ROOT / "kg_rca" / "outputs" / "signature_index.json"

from langchain_openai import OpenAIEmbeddings                       # noqa: E402
from backend.graph_client.semantic_entry import _cosine, load_index  # noqa: E402

# ── 프로브: 시그니처별로 VLM이 낼 법한 관측 문장 ───────────────────────────────
# VLM 자연어(location_text + morphology_text)가 합쳐진 형태를 흉내낸다
# (live_kg_client._query_text 참조). 문헌 문장을 그대로 베끼지 않고 **다르게 표현**해야
# 의미가 아니라 표면 일치를 재는 함정을 피한다.
PROBES: dict[str, list[str]] = {
    "blob@center": [
        "The failing dies are packed into one solid lump right at the middle of the wafer.",
        "Defects concentrate in a single dense patch at the wafer's midpoint, like a bullseye.",
    ],
    "cluster@center": [
        "A tight group of bad dies sits near the centre, densely packed and unbroken.",
        "Failures gather into a compact clump around the middle of the disc.",
    ],
    "global@any": [
        "Bad dies are spread evenly over the whole wafer with no particular hot spot.",
        "The defect covers the entire surface uniformly, edge to edge.",
    ],
    "line@any": [
        "A narrow streak of failures runs straight across the wafer surface.",
        "Defective dies form a thin scratch-like stripe cutting through the disc.",
    ],
    "random@any": [
        "Failures are scattered here and there with no shape or order.",
        "Sparse isolated bad dies appear at random positions across the wafer.",
    ],
    "ring@edge": [
        "A band of failures forms a circle hugging the outer rim of the wafer.",
        "Bad dies trace a continuous loop along the wafer's outer boundary.",
    ],
    "ring@mid": [
        "The failures form a circular band partway out from the centre, not at the rim.",
        "A donut-shaped belt of defects sits at mid-radius of the wafer.",
    ],
    "ring@any": [
        "The bad dies form a ring shape somewhere on the wafer.",
        "A circular annular pattern of failures is visible.",
    ],
}

# 어떤 시그니처와도 매칭되면 안 되는 관측 — 하한이 실제로 걸러내는지 확인용.
# 문턱은 이들의 최고 점수보다 확실히 위에 있어야 한다.
NEGATIVE_PROBES: list[str] = [
    "The lot finished processing on schedule and every die passed electrical test.",
    "Chamber pressure logs show a steady value with no deviation during the run.",
    "The maintenance team replaced the transfer robot belt last Tuesday.",
    "Operator notes mention the recipe was reviewed and approved without changes.",
]


def load_signature_texts(path: Path) -> dict[str, str]:
    """인덱스 파일에서 시그니처별 매칭 텍스트만 꺼낸다(벡터는 버린다 — 모델별로 다시 만든다)."""
    index = load_index(path)
    if not index:
        sys.exit(
            f"인덱스가 비어 있거나 없습니다: {path}\n"
            f"먼저 `python kg_rca/7_build_signature_index.py` 로 만드세요."
        )
    texts = {sig: entry.get("text", "") for sig, entry in index.items()}
    missing = [s for s, t in texts.items() if not t.strip()]
    if missing:
        print(f"⚠️ 텍스트가 빈 시그니처: {missing} — 이 항목은 매칭이 무의미합니다.")
    return texts


def measure(model: str, sig_texts: dict[str, str], probes: dict[str, list[str]],
            negatives: list[str]) -> dict:
    embedder = OpenAIEmbeddings(model=model)

    sigs = sorted(sig_texts)
    sig_vecs = dict(zip(sigs, embedder.embed_documents([sig_texts[s] for s in sigs])))

    flat = [(sig, text) for sig, texts in probes.items() for text in texts]
    probe_vecs = embedder.embed_documents([t for _, t in flat])

    rows = []
    for (truth, text), qv in zip(flat, probe_vecs):
        scored = sorted(
            ((s, _cosine(qv, v)) for s, v in sig_vecs.items()),
            key=lambda kv: kv[1], reverse=True,
        )
        correct = next(sc for s, sc in scored if s == truth)
        best_wrong_sig, best_wrong = next((s, sc) for s, sc in scored if s != truth)
        rows.append({
            "truth": truth, "text": text,
            "correct": correct,
            "best_wrong_sig": best_wrong_sig, "best_wrong": best_wrong,
            "top1": scored[0][0],
            "top1_correct": scored[0][0] == truth,
        })

    neg_rows = []
    for text, qv in zip(negatives, embedder.embed_documents(negatives)):
        best_sig, best = max(((s, _cosine(qv, v)) for s, v in sig_vecs.items()),
                             key=lambda kv: kv[1])
        neg_rows.append({"text": text, "best_sig": best_sig, "best": best})

    corrects = [r["correct"] for r in rows]
    wrongs = [r["best_wrong"] for r in rows]
    negs = [r["best"] for r in neg_rows]

    lo_correct, hi_wrong = min(corrects), max(wrongs)
    hi_neg = max(negs) if negs else 0.0

    # ⚠️ 문턱의 임무는 **"어떤 형상과도 무관한 관측을 걸러내는 것"**이다
    # (semantic_entry.py:30-34). 형제 시그니처끼리의 혼동(ring@edge↔ring@mid,
    # blob@center↔cluster@center)을 가르는 건 문턱이 아니라 top-k 랭킹과
    # morphology_rank의 몫이다 — 형제가 함께 후보로 올라오는 건 설계상 정상이다.
    # 그래서 문턱 판정 기준은 **정답 최소 vs 무관 최대**로 잡는다.
    # 형제 혼동은 top1_accuracy / wrong_max로 따로 보고만 한다(랭킹 품질 지표).
    separable = lo_correct > hi_neg
    suggested = round((lo_correct + hi_neg) / 2, 2) if separable else None

    return {
        "model": model,
        "dim": len(next(iter(sig_vecs.values()))),
        "n_probes": len(rows),
        "top1_accuracy": sum(r["top1_correct"] for r in rows) / len(rows),
        "correct_min": lo_correct, "correct_max": max(corrects),
        "correct_mean": sum(corrects) / len(corrects),
        "wrong_max": hi_wrong, "wrong_mean": sum(wrongs) / len(wrongs),
        "neg_max": hi_neg,
        "margin": lo_correct - hi_neg,
        "separable": separable,
        "suggested_threshold": suggested,
        "rows": rows, "neg_rows": neg_rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="의미 진입 코사인 하한 보정")
    ap.add_argument("--models", default="text-embedding-3-small,text-embedding-3-large",
                    help="쉼표구분 임베딩 모델")
    ap.add_argument("--index", default=str(INDEX_PATH), help="시그니처 인덱스 경로")
    ap.add_argument("--json", action="store_true", help="JSON으로만 출력")
    ap.add_argument("--verbose", action="store_true", help="프로브별 점수까지 출력")
    args = ap.parse_args()

    sig_texts = load_signature_texts(Path(args.index))
    models = [m.strip() for m in args.models.split(",") if m.strip()]

    if not args.json:
        print(f"시그니처 {len(sig_texts)}종 · 프로브 {sum(len(v) for v in PROBES.values())}개 "
              f"· 무관 프로브 {len(NEGATIVE_PROBES)}개")
        print(f"인덱스: {args.index}\n")

    results = []
    for model in models:
        try:
            res = measure(model, sig_texts, PROBES, NEGATIVE_PROBES)
        except Exception as exc:                                   # noqa: BLE001
            print(f"{model}: 실패 — {type(exc).__name__}: {str(exc)[:160]}")
            continue
        results.append(res)

        if args.json:
            continue

        print("=" * 76)
        print(f"■ {model}  (차원 {res['dim']})")
        print("-" * 76)
        print(f"  [문턱 판정] 정답 최소 vs 무관 최대 — 무관 관측을 걸러내는 게 문턱의 임무")
        print(f"    정답 코사인   : {res['correct_min']:.3f} ~ {res['correct_max']:.3f}"
              f"  (평균 {res['correct_mean']:.3f})")
        print(f"    무관 최대     : {res['neg_max']:.3f}")
        print(f"    분리 여유     : {res['margin']:+.3f}")
        if res["separable"]:
            print(f"    ✅ 제안 문턱  : {res['suggested_threshold']}")
        else:
            print(f"    ❌ 겹침 — 정답 최소({res['correct_min']:.3f}) ≤ "
                  f"무관 최대({res['neg_max']:.3f}). 안전한 문턱이 없다.")
        print(f"  [랭킹 품질] 문턱과 무관 — top-k·morphology_rank 몫")
        print(f"    top-1 정답률  : {res['top1_accuracy']:.0%}  ({res['n_probes']}개 프로브)")
        print(f"    형제 최대     : {res['wrong_max']:.3f}  (평균 {res['wrong_mean']:.3f})")
        if args.verbose:
            print("  프로브별:")
            for r in sorted(res["rows"], key=lambda r: r["correct"]):
                mark = "○" if r["top1_correct"] else "✗"
                print(f"    {mark} {r['truth']:15} 정답 {r['correct']:.3f} / "
                      f"오답상위 {r['best_wrong']:.3f}({r['best_wrong_sig']})")
            for r in sorted(res["neg_rows"], key=lambda r: -r["best"]):
                print(f"    · 무관 {r['best']:.3f}({r['best_sig']}) ← {r['text'][:52]}")
        print()

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    if len(results) >= 2:
        print("=" * 76)
        print("모델 비교 — margin이 클수록 문턱을 정하기 안전하다")
        print("-" * 76)
        print(f"{'모델':30} {'top1':>6} {'정답최소':>9} {'무관최대':>9} {'margin':>8} {'제안문턱':>9}")
        for r in results:
            sug = r["suggested_threshold"] if r["separable"] else "겹침"
            print(f"{r['model']:30} {r['top1_accuracy']:>5.0%} {r['correct_min']:>9.3f} "
                  f"{r['neg_max']:>9.3f} {r['margin']:>+8.3f} {str(sug):>9}")
        print()
        print("※ 프로브는 문헌 문장을 그대로 베끼지 않고 바꿔 쓴 것이라, 실제 VLM 서술과")
        print("  분포가 다를 수 있다. VLM 실출력이 쌓이면 PROBES를 그걸로 교체해 다시 잴 것.")


if __name__ == "__main__":
    main()
