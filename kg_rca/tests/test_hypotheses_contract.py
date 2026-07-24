"""outputs/hypotheses.json 산출물 계약 테스트.

kg_rca는 LLM 추출 파이프라인이라 **출력값 동등성**을 테스트하면 재생성마다 깨진다.
그래서 여기서는 값이 아니라 **산출물이 지켜야 할 불변식(invariant)** 만 검사한다:

  1. 스키마/enum      — tier·scenario_hint·fab_table이 정해진 값 집합 안에 있나
  2. 어휘 폐쇄성      — pattern·step·Parameter가 고정 vocabulary 밖으로 새지 않나
  3. 라우팅 진리표    — evidence_label → (tier, scenario_hint, fab_table)이 명세대로인가
  4. 인용 무결성      — 인용 청크가 실존하고, 인용문이 지어낸 게 아닌가 (Critic D3의 전제)
  5. 랭킹 계약        — rank 순서가 (occurrence_prior, evidence_docs, evidence_chunks) 내림차순인가

가설 **건수·내용**은 절대 assert하지 않는다(재생성마다 바뀜). 하한(>0)과 구조만 본다.
fab.db 불필요 — 커밋된 산출물 파일만 읽으므로 CI(-m "not data")에서 그대로 돈다.

정본: docs/KG_schema_v1.4.md · kg_rca/KG_output_명세.md
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_KG_ROOT = Path(__file__).resolve().parents[1]
_HYPOTHESES = _KG_ROOT / "outputs" / "hypotheses.json"
_CHUNKS = _KG_ROOT / "outputs" / "chunks.jsonl"
_SEEDS = _KG_ROOT / "data" / "seeds"

# --- 고정 vocabulary (정본: docs/KG_schema_v1.4.md "고정 vocabulary") ---
PATTERNS = {"Center", "Scratch", "Edge-Ring"}
PROCESS_STEPS = {"LITHO", "ETCH", "DEPO", "CMP", "CLEAN", "EDS"}
TIERS = {"자동", "반자동", "근거없음"}
# JSON null(Python None)로 나오는 것과 문자열 "None"으로 나오는 것을 구분해 둔다.
SCENARIO_HINTS = {"A2", "A3", "A5", "A6", None}
FAB_TABLES = {"telemetry", "maintenance", "lot_history", None}
EVIDENCE_LABELS = {"Parameter", "Maintenance", "Recipe", "None"}
OCCURRENCE_PRIOR = {"high", "mid", "low", None}

# occurrence_prior를 순위 비교용 정수로. None은 최하위.
_PRIOR_ORD = {"high": 3, "mid": 2, "low": 1, None: 0}

# verbatim(원문 그대로) 인용 비율의 회귀 하한 — 실측 93%(762/819, 07-23 산출물).
# LLM이 인용을 더 많이 의역/재구성하기 시작하면 이 선이 잡는다.
_VERBATIM_FLOOR = 0.85


# ============================================================
# fixtures — 무거운 파일은 세션당 1회만 로드
# ============================================================

def _require(path: Path):
    if not path.exists():
        pytest.skip(f"산출물 없음({path.name}) — kg_rca 재빌드(6_ask_graphrag.py) 후 활성화")


@pytest.fixture(scope="session")
def doc() -> dict:
    _require(_HYPOTHESES)
    return json.loads(_HYPOTHESES.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def hyps(doc) -> list[dict]:
    """모든 pattern의 가설을 한 리스트로 편다(스키마/라우팅/인용 테스트용)."""
    return [h for q in doc["questions"] for h in q["hypotheses"]]


@pytest.fixture(scope="session")
def chunk_text() -> dict[str, str]:
    """chunk_id -> 원문(page_content). 인용 무결성 대조용."""
    _require(_CHUNKS)
    out: dict[str, str] = {}
    for line in _CHUNKS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = json.loads(line)
            out[c["chunk_id"]] = c["page_content"]
    return out


def _seed_ids(filename: str) -> set[str]:
    data = json.loads((_SEEDS / filename).read_text(encoding="utf-8"))
    nodes = data["nodes"] if isinstance(data, dict) else data
    return {n["id"] if isinstance(n, dict) else n for n in nodes}


# ============================================================
# 0. 산출물이 비지 않았나 (하한만 — 건수는 안 본다)
# ============================================================

def test_has_all_three_patterns(doc):
    patterns = {q["pattern"] for q in doc["questions"]}
    assert patterns == PATTERNS, f"pattern 집합이 3종과 다름: {patterns}"


def test_every_pattern_nonempty(doc):
    for q in doc["questions"]:
        assert q["hypotheses"], f"{q['pattern']}에 가설이 0건 — 재빌드 실패 의심"


def test_meta_freshness_declared(doc):
    """낡은 산출물을 조용히 쓰는 사고 방지 — 생성 시각이 최소한 기록돼 있어야 한다."""
    assert doc.get("meta", {}).get("generated_at"), "meta.generated_at 누락"


# ============================================================
# 1. 스키마 / enum — 오타가 조용한 분기 오류로 새지 않게
#    (secsgem-mcp test_mapping_table_consistency::test_field_values_valid와 같은 패턴)
# ============================================================

def test_tier_in_enum(hyps):
    bad = {h["tier"] for h in hyps} - TIERS
    assert not bad, f"tier에 정의 밖 값: {bad}"


def test_scenario_hint_in_enum(hyps):
    bad = {h["scenario_hint"] for h in hyps} - SCENARIO_HINTS
    assert not bad, f"scenario_hint에 정의 밖 값: {bad}"


def test_fab_table_in_enum(hyps):
    bad = {h["verification"]["fab_table"] for h in hyps} - FAB_TABLES
    assert not bad, f"verification.fab_table에 정의 밖 값: {bad}"


def test_evidence_label_in_enum(hyps):
    bad = {h["path"]["evidence_label"] for h in hyps} - EVIDENCE_LABELS
    assert not bad, f"path.evidence_label에 정의 밖 값: {bad}"


def test_occurrence_prior_in_enum(hyps):
    bad = {h["score"]["occurrence_prior"] for h in hyps} - OCCURRENCE_PRIOR
    assert not bad, f"score.occurrence_prior에 정의 밖 값: {bad}"


# ============================================================
# 2. 어휘 폐쇄성 — CLAUDE.md가 "고정 vocabulary"라 선언한 것을 코드로 강제
# ============================================================

def test_pattern_vocabulary_closed(doc):
    for q in doc["questions"]:
        assert q["pattern"] in PATTERNS, f"미정의 pattern: {q['pattern']}"


def test_step_vocabulary_closed(hyps):
    """path.step은 ProcessStep 6종 또는 null(문헌 직결)."""
    steps = {h["path"]["step"] for h in hyps}
    bad = {s for s in steps if s is not None} - PROCESS_STEPS
    assert not bad, f"path.step에 ProcessStep 밖 값: {bad}"


def test_parameter_evidence_in_seed_vocab(hyps):
    """evidence_label=Parameter인 후보의 evidence는 Parameter 21종(시드) 안에 있어야 한다.

    이 id는 telemetry.param과의 조인 키다 — 시드 밖 값이면 ⑤가 fab을 조회해도 빈손이다.
    (secsgem-mcp의 X1E pad_usage_hours 유형 사고 방지 — 어휘 정합성.)
    """
    param_ids = _seed_ids("parameters.json")
    offenders = [
        (h["path"]["cause"], h["path"]["evidence"])
        for h in hyps
        if h["path"]["evidence_label"] == "Parameter"
        and h["path"]["evidence"] not in param_ids
    ]
    assert not offenders, f"Parameter 시드 밖 evidence: {offenders[:10]}"


# ============================================================
# 3. 라우팅 진리표 — KG_output_명세.md "tier별 검증 시나리오"를 그대로 assert
#    evidence_label이 곧 검증 체인 배정을 결정하므로, 파생 필드가 어긋나면 ⑤가 잘못 라우팅된다.
# ============================================================

def _route_violation(h: dict) -> str | None:
    label = h["path"]["evidence_label"]
    tier = h["tier"]
    hint = h["scenario_hint"]
    fab = h["verification"]["fab_table"]

    if label == "Parameter":
        if not (tier == "자동" and hint == "A3" and fab == "telemetry"):
            return f"Parameter여야 자동/A3/telemetry: got {tier}/{hint}/{fab}"
    elif label == "Recipe":
        if not (tier == "반자동" and hint == "A5" and fab == "lot_history"):
            return f"Recipe여야 반자동/A5/lot_history: got {tier}/{hint}/{fab}"
    elif label == "Maintenance":
        # consumable 여부로 A6/A2가 갈리므로 hint는 둘 중 하나면 된다.
        if not (tier == "반자동" and hint in ("A2", "A6") and fab == "maintenance"):
            return f"Maintenance여야 반자동/A2|A6/maintenance: got {tier}/{hint}/{fab}"
    elif label == "None":
        if not (tier == "근거없음" and hint is None and fab is None):
            return f"None이면 근거없음/None/None: got {tier}/{hint}/{fab}"
    return None


def test_routing_truth_table(hyps):
    violations = [
        (h["path"]["cause"], msg)
        for h in hyps
        if (msg := _route_violation(h)) is not None
    ]
    assert not violations, "라우팅 진리표 위반:\n" + "\n".join(
        f"  {cause}: {msg}" for cause, msg in violations[:15]
    )


def test_verified_by_implies_evidence_present(hyps):
    """근거없음이 아니면 evidence(조인 키)가 실제로 채워져 있어야 한다(빈 검증 방지)."""
    for h in hyps:
        if h["tier"] != "근거없음":
            assert h["path"]["evidence"], f"{h['path']['cause']}: 검증 tier인데 evidence 없음"


# ============================================================
# 4. 인용 무결성 — LLM이 지어낸 인용 자동 탐지 (Critic D3 전제를 빌드타임에 보장)
# ============================================================

def _norm(s: str) -> str:
    return " ".join(s.split())


def _tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[0-9A-Za-z가-힣]+", s.lower()) if len(t) >= 2]


def _quote_grounding(quote: str, texts: list[str]) -> str:
    """인용문이 인용 청크들에 근거하는 방식을 3단계로 판정.

    verbatim  — 원문에 그대로 있음(가장 강함)
    ellipsis  — '...'로 두 조각을 이은 생략 인용, 각 조각이 원문에 있음
    tokens    — 머리말+항목을 이어 붙였지만(예: "Variables affecting thickness are: D. ..."),
                모든 content 토큰이 인용 청크 안에 있음 — 재구성이지 조작은 아님
    fabricated — 위 어디에도 안 걸림. 원문에 없는 말을 지어냄 = 진짜 문제
    """
    normed = [_norm(t) for t in texts]
    if any(_norm(quote) in t for t in normed):
        return "verbatim"

    parts = [p for p in re.split(r"\.\.\.|…", quote) if len(p.strip()) >= 4]
    if parts and all(any(_norm(p) in t for t in normed) for p in parts):
        return "ellipsis"

    joined = _norm(" ".join(texts)).lower()
    toks = _tokens(quote)
    if toks and all(t in joined for t in toks):
        return "tokens"

    return "fabricated"


def test_all_cited_chunks_exist(hyps, chunk_text):
    """provenance.chunk_ids가 전부 chunks.jsonl에 실존하는가(끊긴 근거 링크 탐지)."""
    dangling = sorted({
        cid
        for h in hyps
        for cid in h["provenance"]["chunk_ids"]
        if cid not in chunk_text
    })
    assert not dangling, f"chunks.jsonl에 없는 chunk_id {len(dangling)}건: {dangling[:10]}"


def test_no_fabricated_quotes(hyps, chunk_text):
    """어떤 인용문도 인용 청크 밖의 말을 지어내지 않았는가 — 인용 무결성의 핵심.

    생략('...')·머리말 재구성은 허용하되(원문 토큰으로 환원되므로), 원문에 없는 토큰이
    섞인 인용은 조작으로 보고 실패시킨다.
    """
    fabricated = []
    for h in hyps:
        texts = [chunk_text[cid] for cid in h["provenance"]["chunk_ids"] if cid in chunk_text]
        for quote in h["provenance"].get("quotes") or []:
            if _quote_grounding(quote, texts) == "fabricated":
                fabricated.append((h["path"]["cause"], quote))
    assert not fabricated, "인용 청크에 근거 없는(지어낸) 인용:\n" + "\n".join(
        f"  {cause}: {quote!r}" for cause, quote in fabricated[:15]
    )


def test_verbatim_quote_rate_above_floor(hyps, chunk_text):
    """원문 그대로인 인용 비율이 하한 이상인가(회귀 가드).

    조작(위 테스트)이 0이어도, 의역·재구성이 늘면 인용의 증거력이 약해진다.
    실측 ~93%. 이 선이 무너지면 추출 프롬프트가 인용을 느슨하게 다루기 시작했다는 신호.
    """
    verbatim = total = 0
    for h in hyps:
        texts = [chunk_text[cid] for cid in h["provenance"]["chunk_ids"] if cid in chunk_text]
        for quote in h["provenance"].get("quotes") or []:
            total += 1
            if _quote_grounding(quote, texts) == "verbatim":
                verbatim += 1
    if total == 0:
        pytest.skip("인용이 하나도 없음")
    rate = verbatim / total
    assert rate >= _VERBATIM_FLOOR, (
        f"verbatim 인용 비율 {rate:.1%} < 하한 {_VERBATIM_FLOOR:.0%} "
        f"({verbatim}/{total}) — 인용 의역/재구성이 늘었다"
    )


# ============================================================
# 5. 랭킹 계약 — "실행마다 순서가 바뀌지 않게"(KG_output_명세.md)를 검증
#    순위 = (occurrence_prior, evidence_docs, evidence_chunks) 내림차순, 동점은 cause 이름 오름차순
# ============================================================

def _rank_key(h: dict) -> tuple[int, int, int]:
    s = h["score"]
    return (_PRIOR_ORD[s["occurrence_prior"]], s["evidence_docs"], s["evidence_chunks"])


def test_hypotheses_sorted_by_rank_key(doc):
    """각 pattern 안에서 배열 순서가 순위 규칙을 실제로 만족하는가."""
    violations = []
    for q in doc["questions"]:
        prev = None
        for h in q["hypotheses"]:
            key, cause = _rank_key(h), h["path"]["cause"]
            if prev is not None:
                pkey, pcause = prev
                if key > pkey:
                    violations.append(f"{q['pattern']}: {pcause}{pkey} 뒤에 더 높은 {cause}{key}")
                elif key == pkey and cause < pcause:
                    violations.append(f"{q['pattern']}: 동점인데 cause 역순 {pcause}→{cause}")
            prev = (key, cause)
    assert not violations, "랭킹 계약 위반:\n" + "\n".join(f"  {v}" for v in violations[:15])


def test_rank_field_is_sequential(doc):
    """rank 필드가 배열 위치와 일치하는 1..n 연번인가(rank를 조사 순서로 쓰는 하위 노드 전제)."""
    for q in doc["questions"]:
        ranks = [h["rank"] for h in q["hypotheses"]]
        assert ranks == list(range(1, len(ranks) + 1)), (
            f"{q['pattern']}: rank가 1..n 연번이 아님 — 앞 5개 {ranks[:5]}"
        )
