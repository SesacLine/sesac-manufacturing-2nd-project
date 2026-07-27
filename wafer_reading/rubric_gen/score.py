"""루브릭 기반 결정적 채점 — VLM 서술 vs 고정 루브릭

핵심 규칙 3가지:

1. **구(phrase) 단위 매칭**: must-hit/avoid는 단어가 아니라 구다. 토큰 단위로 보면
   avoid "radial"이 정상 서술 "radial dependency"를 환각으로 오탐한다.
2. **hit 우선 마스킹**: must-hit로 매칭된 구간을 지운 뒤 avoid를 찾는다. 위 예에서
   "radial dependency"가 hit로 먼저 잡히면 그 구간의 "radial"은 avoid로 세지 않는다.
3. **단어 경계**: "band"가 "bandwidth"에 걸리지 않도록 경계를 강제한다.
4. **fuzzy 2차 매칭**(논문 `fuzzy_threshold`): 정확 매칭이 실패한 구만 근접 윈도우로 다시 찾아
   어순·삽입어·굴절형을 흡수한다("diffuse halo" ↔ "diffuse surrounding halo"). 동의어
   ("rim" ↔ "periphery")는 **범위 밖** — 문자 유사도로는 못 넘고 임베딩이 필요하다.

점수식은 WaferSAGE 논문 따름:

    C(coverage)  = 매칭된 must-hit 수 / must-hit 총 수
    H(hit)       = min(1.0, HIT_SOFT_FACTOR × C)          소프트 리콜 — 2/3만 담아도 만점
    A(avoid)     = max(0.0, 1.0 − AVOID_PENALTY_PER_HIT × n_f)   위반 **개수당** 감점(비율 아님)
    D(dimension) = HIT_WEIGHT × H + AVOID_WEIGHT × A       가중합
    S(overall)   = Σ wᵢ Dᵢ  (spatial 0.4 / morphology 0.35 — 채점 가능한 축으로 재정규화)

논문의 root_cause 축(w=0.25)은 우리 범위 밖이라(원인 추론은 KG 몫) 제외하고 나머지 두 축의
가중치를 재정규화한다 → spatial 0.533 / morphology 0.467.

BLEU-4 / ROUGE-L은 기획안 지표의 **보조**(설계서 §6) — 외부 의존성 없이 여기 구현한다.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from difflib import SequenceMatcher

from .schema import DIMENSIONS, normalize_phrase, normalize_text, phrases_of

# fuzzy matching (논문 `fuzzy_threshold` 대응) — 정확 매칭 실패 시에만 2차로 시도한다.
#   구 매칭 = 근접 윈도우 안에서 구 토큰의 FUZZY_THRESHOLD 이상이 대응되면 매칭
#   토큰 대응 = 완전일치 또는 문자 유사도 ≥ FUZZY_TOKEN_RATIO
# 0.85는 실측으로 고른 경계다: 굴절형(rings 0.889 / edges 0.889 / linearly 0.857 / uniformly 0.875)은
# 흡수하고 다른 단어(core~corner 0.80 / central~center 0.769 / rim~ring 0.571)는 배제한다.
FUZZY_THRESHOLD = 0.8       # 구 토큰 커버리지 임계 (None이면 fuzzy 비활성 = 정확 매칭만)
FUZZY_TOKEN_RATIO = 0.85    # 토큰 문자 유사도 임계
FUZZY_WINDOW_SLACK = 3      # 구 토큰 수 + 이만큼까지 윈도우 확장(삽입어 허용: "diffuse (surrounding) halo")
FUZZY_MIN_CHARS = 5         # 이보다 짧은 구는 fuzzy 금지(arc/rim 같은 3글자는 오탐 위험)

# WaferSAGE 규약 상수 — 논문값 그대로. 메타 평가(judge 상관 최대화)로 튜닝하기 전까지 고정.
HIT_SOFT_FACTOR = 1.5        # H = min(1, 1.5·C) — 자연어 변동성 흡수(≈67% 커버리지면 만점)
AVOID_PENALTY_PER_HIT = 0.25  # A = max(0, 1 − 0.25·n_f) — 환각 1건당 0.25 감점
HIT_WEIGHT, AVOID_WEIGHT = 0.6, 0.4  # D = 0.6·H + 0.4·A
DIMENSION_WEIGHTS = {"spatial": 0.4, "morphology": 0.35}  # 논문 원값(root_cause 0.25는 제외)

# 부정 문맥 단서 — 이 뒤 절(clause) 안에서 걸린 구는 "언급"이 아니라 "부정"이므로 세지 않는다.
# 실측 근거(07-26 Center 5/5 오탐): "blob-like rather than linear or ring-shaped",
# "with no linear or ring-shaped structure", "without distinct linear or ring-like structures".
NEGATION_CUES = (
    "no", "not", "without", "rather than", "instead of", "free of", "devoid of",
    "lacks", "lacking", "absent", "never", "neither", "nor", "non", "excluding",
)
NEGATION_SCOPE_CHARS = 60  # 절 경계(,;.)를 못 만나면 여기까지만 부정 스코프로 본다

# 서술 필드 → 채점 dimension 매핑. total_description은 두 축 합집합으로 별도(보조) 채점한다.
DIMENSION_FIELD = {"spatial": "location_text", "morphology": "morphology_text"}


def _phrase_regex(phrase: str) -> re.Pattern | None:
    tokens = normalize_phrase(phrase).split()
    if not tokens:
        return None
    body = r"\s+".join(re.escape(t) for t in tokens)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


def negation_spans(text: str) -> list[tuple[int, int]]:
    """부정 단서 뒤 절의 문자 구간 — 이 안의 매칭은 "언급하지 않았다"로 본다.

    스코프는 단서 직후부터 절 경계(`,` `;` `.`)까지, 없으면 NEGATION_SCOPE_CHARS까지.
    정규화가 길이 보존이라 원문 구두점 위치를 그대로 경계로 쓸 수 있다.
    """
    norm = normalize_text(text)
    spans = []
    for cue in NEGATION_CUES:
        rx = _phrase_regex(cue)
        if rx is None:
            continue
        for m in rx.finditer(norm):
            stop = min(len(text), m.end() + NEGATION_SCOPE_CHARS)
            for i in range(m.end(), stop):
                if text[i] in ",;.":
                    stop = i
                    break
            spans.append((m.start(), stop))
    return spans


def _tokens_with_spans(norm: str) -> list[tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in re.finditer(r"\S+", norm)]


def _token_equal(a: str, b: str, ratio: float) -> bool:
    return a == b or SequenceMatcher(None, a, b).ratio() >= ratio


def _window_coverage(phrase_tokens: list[str], window: list[str], ratio: float) -> float:
    """구 토큰 중 윈도우 토큰에 (중복 없이) 대응되는 비율."""
    remaining = list(window)
    matched = 0
    for pt in phrase_tokens:
        for i, wt in enumerate(remaining):
            if _token_equal(pt, wt, ratio):
                remaining.pop(i)
                matched += 1
                break
    return matched / len(phrase_tokens)


def fuzzy_find(
    norm: str, phrase: str, threshold: float, token_ratio: float = FUZZY_TOKEN_RATIO
) -> list[tuple[int, int]]:
    """정확 매칭이 실패한 구를 근접 윈도우로 다시 찾는다 — 최선 윈도우 1개의 구간(없으면 빈 리스트).

    어순 변화·삽입어("diffuse **surrounding** halo")·굴절형(rings/edges)을 흡수하되,
    윈도우 폭을 구 길이+FUZZY_WINDOW_SLACK로 묶어 문서 전체 산재 매칭은 막는다.
    """
    ptokens = normalize_phrase(phrase).split()
    if not ptokens or len(normalize_phrase(phrase)) < FUZZY_MIN_CHARS:
        return []
    toks = _tokens_with_spans(norm)
    best, best_span = 0.0, None
    for size in range(len(ptokens), len(ptokens) + FUZZY_WINDOW_SLACK + 1):
        for i in range(0, max(0, len(toks) - size) + 1):
            window = toks[i : i + size]
            if not window:
                continue
            cov = _window_coverage(ptokens, [w[0] for w in window], token_ratio)
            if cov > best:
                best, best_span = cov, (window[0][1], window[-1][2])
    return [best_span] if best_span and best >= threshold else []


def find_matches(
    text: str,
    phrases: list[str],
    skip_spans: list[tuple[int, int]] = (),
    fuzzy_threshold: float | None = FUZZY_THRESHOLD,
) -> tuple[list[str], list[tuple[int, int]], list[str], list[str]]:
    """정규화 텍스트에서 매칭된 구·구간·부정 문맥 전용 구·fuzzy로 잡힌 구를 돌려준다.

    - 정확 매칭이 1순위, 실패한 구만 fuzzy로 2차 시도한다(`fuzzy_threshold=None`이면 생략).
    - 한 구가 부정 스코프 안팎에 모두 나오면 **매칭으로 친다**("no linear ... a linear scratch").
    """
    norm = normalize_text(text)
    matched, spans, negated, fuzzy_matched = [], [], [], []
    for phrase in phrases:
        key = normalize_phrase(phrase)
        rx = _phrase_regex(phrase)
        if rx is None:
            continue
        found = [(m.start(), m.end()) for m in rx.finditer(norm)]
        is_fuzzy = False
        if not found and fuzzy_threshold is not None:
            found = fuzzy_find(norm, phrase, fuzzy_threshold)
            is_fuzzy = bool(found)
        if not found:
            continue
        live = [f for f in found if not any(s <= f[0] < e for s, e in skip_spans)]
        if live:
            matched.append(key)
            spans.extend(live)
            if is_fuzzy:
                fuzzy_matched.append(key)
        else:
            negated.append(key)
    return matched, spans, negated, fuzzy_matched


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    """매칭 구간을 공백으로 덮는다 — 길이 보존 정규화(normalize_text) 덕에 오프셋이 원문과 일치."""
    chars = list(normalize_text(text))
    for start, end in spans:
        for i in range(start, end):
            chars[i] = " "
    return "".join(chars)


def score_dimension(
    text: str,
    must_hit: list[str],
    must_avoid: list[str],
    fuzzy_threshold: float | None = FUZZY_THRESHOLD,
) -> dict:
    """한 축(spatial | morphology) 채점 — hit 마스킹 후 avoid 탐색(검수 ② 해소).

    must-hit이 비어 있으면 **채점 불가(applicable=False, score=None)**로 낸다. 0점이 아니다 —
    "기준이 없다"와 "기준을 못 맞췄다"는 다르고, 0점으로 뭉개면 표본이 부족한 패턴
    (실측: Scratch spatial)이 영구적으로 반토막 점수를 받는다. avoid 위반 탐지는 계속 유효하다.
    """
    negations = negation_spans(text)
    hits, hit_spans, negated_hits, fuzzy_hits = find_matches(
        text, must_hit, negations, fuzzy_threshold
    )
    masked = _mask(text, hit_spans)
    violations, _, negated_violations, fuzzy_violations = find_matches(
        masked, must_avoid, negations, fuzzy_threshold
    )

    # A(avoid)는 must-hit 유무와 무관하게 계산한다 — 기준이 없는 축에서도 환각은 잡아야 한다.
    avoid_score = max(0.0, 1.0 - AVOID_PENALTY_PER_HIT * len(violations))
    applicable = bool(must_hit)
    hit_coverage = len(hits) / len(must_hit) if applicable else None
    hit_score = min(1.0, HIT_SOFT_FACTOR * hit_coverage) if applicable else None
    score = HIT_WEIGHT * hit_score + AVOID_WEIGHT * avoid_score if applicable else None
    return {
        "applicable": applicable,
        "score": round(score, 4) if score is not None else None,
        "hit_coverage": round(hit_coverage, 4) if hit_coverage is not None else None,
        "hit_score": round(hit_score, 4) if hit_score is not None else None,
        "avoid_score": round(avoid_score, 4),
        "n_violations": len(violations),
        "hits": hits,
        "missed": [p for p in map(normalize_phrase, must_hit) if p not in hits],
        "violations": violations,
        # 부정 문맥에서만 나온 구 — 점수에 반영하지 않되 추적용으로 남긴다
        "negated_hits": negated_hits,
        "negated_violations": negated_violations,
        # 정확 매칭이 아니라 fuzzy로 인정된 구 — 감사(오탐 점검)용
        "fuzzy_hits": fuzzy_hits,
        "fuzzy_violations": fuzzy_violations,
    }


def score_output(
    vlm_output: dict, fixed_rubric: dict, fuzzy_threshold: float | None = FUZZY_THRESHOLD
) -> dict:
    """VLM 서술 1건 채점.

    vlm_output: VLMReader.describe_group 반환(location_text/morphology_text/total_description).
    반환: dimension별 상세 + overall + hallucinated 플래그.
    """
    dims: dict[str, dict] = {}
    for name in DIMENSIONS:
        text = vlm_output.get(DIMENSION_FIELD[name]) or ""
        dims[name] = score_dimension(
            text,
            phrases_of(fixed_rubric, name, "must_hit"),
            phrases_of(fixed_rubric, name, "must_avoid"),
            fuzzy_threshold,
        )

    all_hit = [p for n in DIMENSIONS for p in phrases_of(fixed_rubric, n, "must_hit")]
    all_avoid = [p for n in DIMENSIONS for p in phrases_of(fixed_rubric, n, "must_avoid")]
    summary = score_dimension(
        vlm_output.get("total_description") or "", all_hit, all_avoid, fuzzy_threshold
    )

    # S = Σ wᵢDᵢ — 채점 가능한 축만 남기고 가중치를 재정규화(Scratch spatial 공백 같은 경우).
    scored = {n: d["score"] for n, d in dims.items() if d["applicable"]}
    w_sum = sum(DIMENSION_WEIGHTS[n] for n in scored)
    overall = (
        round(sum(DIMENSION_WEIGHTS[n] * s for n, s in scored.items()) / w_sum, 4) if w_sum else None
    )
    return {
        "pattern": fixed_rubric.get("pattern"),
        "vlm_track": vlm_output.get("vlm_track"),
        "image_mode": vlm_output.get("image_mode"),
        "dimensions": dims,
        "summary_aux": summary,  # total_description은 보조 지표(주 점수에 미포함)
        "overall": overall,  # 채점 가능한 축의 가중합 (전부 불가면 None)
        "scored_dimensions": list(scored),
        "hallucinated": any(d["violations"] for d in dims.values()),
    }


# ---------------------------------------------------------------- 보조 지표(BLEU-4 / ROUGE-L)

def _tokens(text: str) -> list[str]:
    return normalize_text(text).split()


def rouge_l(candidate: str, reference: str) -> dict:
    """ROUGE-L (LCS 기반 F1). 레퍼런스 세트가 있을 때만 쓰는 보조 지표."""
    c, r = _tokens(candidate), _tokens(reference)
    if not c or not r:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    # LCS 길이 (O(len(c)*len(r)) DP — 서술 길이가 짧아 충분)
    prev = [0] * (len(r) + 1)
    for ci in c:
        cur = [0]
        for j, rj in enumerate(r):
            cur.append(prev[j] + 1 if ci == rj else max(cur[j], prev[j + 1]))
        prev = cur
    lcs = prev[-1]
    p, rec = lcs / len(c), lcs / len(r)
    f1 = 0.0 if p + rec == 0 else 2 * p * rec / (p + rec)
    return {"precision": round(p, 4), "recall": round(rec, 4), "f1": round(f1, 4)}


def bleu(candidate: str, reference: str, max_n: int = 4) -> float:
    """BLEU-4 (add-1 스무딩, brevity penalty 포함) — 단일 레퍼런스."""
    c, r = _tokens(candidate), _tokens(reference)
    if not c or not r:
        return 0.0
    log_sum, used = 0.0, 0
    for n in range(1, max_n + 1):
        if len(c) < n:
            break
        cand_ng = Counter(tuple(c[i : i + n]) for i in range(len(c) - n + 1))
        ref_ng = Counter(tuple(r[i : i + n]) for i in range(len(r) - n + 1))
        overlap = sum(min(cnt, ref_ng[ng]) for ng, cnt in cand_ng.items())
        total = sum(cand_ng.values())
        smooth = 1.0 if n > 1 else 0.0  # 1-gram은 스무딩 없이(0이면 BLEU=0이 맞다)
        precision = (overlap + smooth) / (total + smooth)
        if precision == 0:
            return 0.0
        log_sum += math.log(precision)
        used += 1
    if not used:
        return 0.0
    bp = 1.0 if len(c) > len(r) else math.exp(1 - len(r) / len(c))
    return round(bp * math.exp(log_sum / used), 4)
