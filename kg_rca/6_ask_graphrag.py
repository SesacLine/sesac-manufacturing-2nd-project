"""관측된 불량 패턴 → 근본 원인 가설 목록 (outputs/hypotheses.json).

그래프 순회는 손으로 쓴 고정 Cypher로 결정적으로 한다 — LLM이 Cypher를 생성하지 않는다
(구 Text2Cypher 버전은 backup/6_ask_graphrag_backup.py). LLM은 순회로 뽑은 사실을 한국어
가설 문장으로 옮길 때만 쓴다.

가설 1건 = 그래프 경로 1개. 세 경로:
  공정 경유: DefectPattern -ARISES_IN-> ProcessStep <-OCCURS_IN- FailureMode -CAUSED_BY-> Cause -VERIFIED_BY-> Evidence
  형상 경유: DefectPattern -HAS_SIGNATURE-> SpatialSignature -FORMS_IN-> ProcessStep -> ...
  문헌 직결: DefectPattern -ATTRIBUTED_TO-> Cause
Evidence(Parameter/Maintenance/Recipe)에 닿지 않는 Cause도 [근거없음] 가설로 낸다(버리지 않는다).

스키마 정본: ../docs/KG_schema_v1.4.md · 출력 필드 명세: KG_output_명세.md
"""

import os
import re
import sys
import json
import difflib
import collections
from datetime import datetime
from pathlib import Path

import yaml

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Windows 콘솔(cp949)에서 em-dash 등 유니코드 출력 시 크래시 방지
sys.stdout.reconfigure(encoding="utf-8")

from langchain_openai import ChatOpenAI
from langchain_neo4j import Neo4jGraph

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
SEEDS_DIR = BASE_DIR / "data" / "seeds"

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")

# 기본값은 "탐색된 모든 가설을 다 낸다".
# 굳이 잘라 보고 싶으면 환경변수로: TOP_K=3 python 6_ask_graphrag.py
_top_k = os.getenv("TOP_K")
TOP_K = int(_top_k) if _top_k else None

# 문장 합성을 한 번에 다 넘기면 프롬프트가 터진다. 배치로 나눠 부른다.
SYNTHESIS_BATCH = 12


# =========================
# 1. 가설 경로 조회 (결정적 Cypher)
# =========================

# evidence 3종을 :Evidence 슈퍼라벨로 한 번에 잡는다.
# Parameter 만 telemetry 조인으로 자동 판정되고, Maintenance/Recipe 는 조회만 자동이다(반자동).
# VERIFIED_BY는 OPTIONAL — evidence가 없는 Cause도 [근거없음] 가설로 나와야 한다.
# (direct 경로만 evidence 없이 나오고 공정 경유는 통째로 사라지던 비대칭 제거)
HYPOTHESIS_QUERY = """
MATCH (p:DefectPattern {id: $pattern})-[a:ARISES_IN]->(s:ProcessStep)
MATCH (fm:FailureMode)-[:OCCURS_IN]->(s)
MATCH (fm)-[cb:CAUSED_BY]->(c:Cause)
OPTIONAL MATCH (c)-[vb:VERIFIED_BY]->(e:Evidence)
RETURN s.id            AS step,
       fm.id           AS failure_mode,
       fm.name         AS failure_mode_name,
       c.id            AS cause,
       c.name          AS cause_name,
       c.description   AS cause_description,
       c.unverifiable_signals AS unverifiable_signals,
       coalesce(e.id, '근거없음')    AS evidence,
       coalesce(e.name, '문헌 서술') AS evidence_name,
       CASE
         WHEN e:Parameter   THEN 'Parameter'
         WHEN e:Maintenance THEN 'Maintenance'
         WHEN e:Recipe      THEN 'Recipe'
         ELSE 'None'
       END             AS evidence_label,
       coalesce(e.fab_table, '-') AS fab_table,
       e.consumable    AS consumable,
       vb.direction    AS direction,
       a.occurrence_prior AS occurrence_prior,
       (coalesce(a.extraction_confidence, 3)
        + coalesce(cb.extraction_confidence, 3)
        + coalesce(vb.extraction_confidence, 3)) / 3.0 AS confidence,
       cb.quotes       AS quotes,
       (coalesce(a.chunk_ids, []) + coalesce(cb.chunk_ids, [])
        + coalesce(vb.chunk_ids, [])) AS chunk_ids
"""

# 형상 경유 경로 (문서 D). 패턴 -> 형상은 시드에서 결정적으로 깔리고(HAS_SIGNATURE),
# 형상 -> 공정은 문헌의 형상 수준 서술에서 추출된다(FORMS_IN).
# 미지 패턴 대응의 기반이기도 하다: VLM이 형상만 넘겨도 signature부터 순회 가능.
SIGNATURE_QUERY = """
MATCH (p:DefectPattern {id: $pattern})-[:HAS_SIGNATURE]->(g:SpatialSignature)
MATCH (g)-[f:FORMS_IN]->(s:ProcessStep)
MATCH (fm:FailureMode)-[:OCCURS_IN]->(s)
MATCH (fm)-[cb:CAUSED_BY]->(c:Cause)
OPTIONAL MATCH (c)-[vb:VERIFIED_BY]->(e:Evidence)
RETURN g.id            AS signature,
       s.id            AS step,
       fm.id           AS failure_mode,
       fm.name         AS failure_mode_name,
       c.id            AS cause,
       c.name          AS cause_name,
       c.description   AS cause_description,
       c.unverifiable_signals AS unverifiable_signals,
       coalesce(e.id, '근거없음')    AS evidence,
       coalesce(e.name, '문헌 서술') AS evidence_name,
       CASE
         WHEN e:Parameter   THEN 'Parameter'
         WHEN e:Maintenance THEN 'Maintenance'
         WHEN e:Recipe      THEN 'Recipe'
         ELSE 'None'
       END             AS evidence_label,
       coalesce(e.fab_table, '-') AS fab_table,
       e.consumable    AS consumable,
       vb.direction    AS direction,
       f.occurrence_prior AS occurrence_prior,
       f.density          AS density,
       f.continuity       AS continuity,
       f.angular_coverage AS angular_coverage,
       f.clock_positions  AS clock_positions,
       (coalesce(f.extraction_confidence, 3)
        + coalesce(cb.extraction_confidence, 3)
        + coalesce(vb.extraction_confidence, 3)) / 3.0 AS confidence,
       cb.quotes       AS quotes,
       (coalesce(f.chunk_ids, []) + coalesce(cb.chunk_ids, [])
        + coalesce(vb.chunk_ids, [])) AS chunk_ids
"""

# 형상 직접 진입 — pattern 없이 SpatialSignature(shape@zone)에서 순회를 시작한다.
# SIGNATURE_QUERY와 꼬리는 같지만 진입이 다르다: 패턴을 거치지 않으므로(HAS_SIGNATURE 없음)
# 미지 패턴(CNN=Unknown)에서도 형상만으로 조회 가능하고, ARISES_IN dedup에 형상 경로가 먹히지
# 않아 **모든 FORMS_IN 엣지의 morphology가 후보에 보존된다**(angular 판별자의 전제).
SIGNATURE_ENTRY_QUERY = """
MATCH (g:SpatialSignature {id: $signature})-[f:FORMS_IN]->(s:ProcessStep)
MATCH (fm:FailureMode)-[:OCCURS_IN]->(s)
MATCH (fm)-[cb:CAUSED_BY]->(c:Cause)
OPTIONAL MATCH (c)-[vb:VERIFIED_BY]->(e:Evidence)
RETURN g.id            AS signature,
       s.id            AS step,
       fm.id           AS failure_mode,
       fm.name         AS failure_mode_name,
       c.id            AS cause,
       c.name          AS cause_name,
       c.description   AS cause_description,
       c.unverifiable_signals AS unverifiable_signals,
       coalesce(e.id, '근거없음')    AS evidence,
       coalesce(e.name, '문헌 서술') AS evidence_name,
       CASE
         WHEN e:Parameter   THEN 'Parameter'
         WHEN e:Maintenance THEN 'Maintenance'
         WHEN e:Recipe      THEN 'Recipe'
         ELSE 'None'
       END             AS evidence_label,
       coalesce(e.fab_table, '-') AS fab_table,
       e.consumable    AS consumable,
       vb.direction    AS direction,
       f.occurrence_prior AS occurrence_prior,
       f.density          AS density,
       f.continuity       AS continuity,
       f.angular_coverage AS angular_coverage,
       f.clock_positions  AS clock_positions,
       (coalesce(f.extraction_confidence, 3)
        + coalesce(cb.extraction_confidence, 3)
        + coalesce(vb.extraction_confidence, 3)) / 3.0 AS confidence,
       cb.quotes       AS quotes,
       (coalesce(f.chunk_ids, []) + coalesce(cb.chunk_ids, [])
        + coalesce(vb.chunk_ids, [])) AS chunk_ids
"""

# 문헌이 공정을 거치지 않고 패턴 -> 원인을 바로 말한 경우(ref56 Table 1).
# 공정을 모르므로 Parameter 자동 검증에 닿지 못한다. evidence가 없을 수도 있다.
DIRECT_QUERY = """
MATCH (p:DefectPattern {id: $pattern})-[at:ATTRIBUTED_TO]->(c:Cause)
OPTIONAL MATCH (c)-[vb:VERIFIED_BY]->(e:Evidence)
RETURN 'direct'        AS route,
       NULL            AS step,
       NULL            AS failure_mode,
       '(문헌 직결)'    AS failure_mode_name,
       c.id            AS cause,
       c.name          AS cause_name,
       c.description   AS cause_description,
       c.unverifiable_signals AS unverifiable_signals,
       coalesce(e.id, '근거없음')    AS evidence,
       coalesce(e.name, '문헌 서술') AS evidence_name,
       CASE
         WHEN e:Parameter   THEN 'Parameter'
         WHEN e:Maintenance THEN 'Maintenance'
         WHEN e:Recipe      THEN 'Recipe'
         ELSE 'None'
       END             AS evidence_label,
       coalesce(e.fab_table, '-') AS fab_table,
       e.consumable    AS consumable,
       vb.direction    AS direction,
       NULL            AS occurrence_prior,
       coalesce(at.extraction_confidence, 3) AS confidence,
       at.quotes       AS quotes,
       at.chunk_ids    AS chunk_ids
"""

PRIOR_RANK = {"high": 3, "mid": 2, "low": 1}


# =========================
# 1.1 검증 등급 (verification tier)
# -------------------------
# 가르는 축은 "fab.db에 데이터가 있느냐"가 아니다. 셋 다 fab 테이블에 붙어 있다.
# 진짜 축은 **에이전트가 스스로 채택/기각을 판정할 수 있느냐**다.
#
#   자동   Parameter   : Parameter.id == telemetry.param 이라 결정적으로 조인된다.
#                        fab_model.yaml의 정상범위와 비교해 기계적으로 판정한다.
#                        -> hypothesis agent가 쿼리 작성부터 결론까지 끝낸다.
#
#   반자동 Maintenance : maintenance 테이블을 조회할 수는 있다. 그러나 Maintenance.id는
#                        조인 키가 아니라 필터 힌트이고(parts 컬럼이 자유 텍스트),
#                        어느 행이 그 정비인지·지연됐는지는 규칙으로 못 정한다.
#          Recipe      : lot_history.recipe_id로 실제 레시피는 읽는다.
#                        그러나 **기대값이 KG에 없어** 비교 대상이 없다.
#                        -> agent가 근거 데이터를 뽑아 오고, 판정은 사람이 한다.
#
#   근거없음           : evidence 노드 자체가 없다. ATTRIBUTED_TO로만 붙은 Cause가 여기다.
#                        (예: surface_damage_by_humans, RTP 관련 원인 — fab 6스텝 밖)
#                        -> fab 데이터로 손댈 수 없다. 문헌 서술로만 남는다.
#
# 순위에서 자동 > 반자동 > 근거없음 순으로 올린다.
# =========================

TIER_AUTO, TIER_SEMI, TIER_NONE = 2, 1, 0

TIER_OF_LABEL = {
    "Parameter": TIER_AUTO,
    "Maintenance": TIER_SEMI,
    "Recipe": TIER_SEMI,
}

TIER_TAG = {TIER_AUTO: "자동", TIER_SEMI: "반자동", TIER_NONE: "근거없음"}

# =========================
# 1.1b 시나리오 힌트 (MCP 문서 3.1의 검증 체인 라우팅)
# -------------------------
# evidence 종류가 검증 체인을 정한다: Parameter->A3, Recipe->A5,
# Maintenance는 소모품(A6)/일반 정비(A2)로 갈린다 — Maintenance.consumable이 그 사실.
# consumable은 추출 시 LLM이 문헌 문맥으로 판단해 노드에 저장된다.
# 속성이 없는 소급분(재추출 전 노드)은 아래 키워드 휴리스틱으로 임시 판정한다.
# =========================

CONSUMABLE_KEYWORDS = ("pad", "brush", "slurry", "filter", "conditioner", "conditioning")


def _consumable_heuristic(evidence_id: str, evidence_name: str) -> bool:
    text = f"{evidence_id} {evidence_name}".lower()
    return any(k in text for k in CONSUMABLE_KEYWORDS)


def scenario_hint(row: dict) -> str | None:
    """이 가설을 MCP 어느 검증 체인으로 보낼지. [근거없음]은 배정 체인 없음(None)."""
    label = row["evidence_label"]
    if label == "Parameter":
        return "A3"
    if label == "Recipe":
        return "A5"
    if label == "Maintenance":
        consumable = row.get("consumable")
        if consumable is None:   # 소급분 — 임시 휴리스틱 (재추출 시 노드 속성으로 대체됨)
            consumable = _consumable_heuristic(row["evidence"] or "", row["evidence_name"] or "")
        return "A6" if consumable else "A2"
    return None


LEGEND = """검증 등급 — 'fab.db에 있느냐'가 아니라 '에이전트가 스스로 판정할 수 있느냐'로 가릅니다.
  [자동]     Parameter. telemetry.param과 결정적으로 조인되고 정상범위로 판정 가능. 에이전트가 결론까지 냅니다.
  [반자동]   Maintenance / Recipe. fab 테이블 조회는 되지만 조인 키나 기대값이 없어 판정은 사람 몫입니다.
  [근거없음] 검증 신호가 없는 문헌 서술. fab 데이터로 확인할 수 없습니다."""


# =========================
# 1.2 매핑 테이블 오버레이 (mapping_table.yaml)
# -------------------------
# [근거없음] 가설의 Cause를 패턴별 큐레이션 표와 유사도 매칭해 검증 신호를 채운다.
# 그래프는 건드리지 않는다 — 문헌 추출(그래프)과 큐레이션 지식(오버레이)의 provenance를
# 섞지 않기 위해 출력 조립 시점에만 얹는다. 채워진 가설은 mapping 블록으로 출처가 드러난다.
#
# 승격 규칙: telemetry_signature.param이 fab 20종 안에 있을 때만 [자동]으로 올린다.
# 어휘 밖 param(pad_usage_hours 등)은 힌트로만 싣고 등급을 유지한다 (정합성검토 X1).
#
# mapping_table.yaml은 MCP/fab 쪽 소유라 KG 사정(매칭 키워드)을 넣지 않는다.
# 표의 cause id(cmp_pad_wear)와 추출된 Cause(pad_condition_degrades)는 어휘가 달라
# 순수 유사도로는 못 잇는다 — 그 간극을 메우는 매칭 키워드는 아래 상수로 KG 모듈이 소유한다.
# 표에 항목이 늘면 여기 키워드만 추가하면 된다 (키 = 표의 cause id).
# =========================

MAPPING_PATH = BASE_DIR / "mapping_table.yaml"

# 표의 cause id -> 추출된 Cause를 잇는 매칭 표현들 (소문자, 공백 구분)
MAPPING_MATCH_KEYWORDS: dict[str, list[str]] = {
    # Edge-Ring
    "etch_nonuniformity": [
        "etch nonuniformity", "etching non uniformities", "nonuniform etch",
        "etch non uniformity", "edge plasma", "plasma density",
    ],
    "cmp_edge_overpolish": [
        "edge overpolish", "edge over polish", "overpolish at edge",
        "excessive polishing at edge", "edge over polishing",
        # P1(대칭 보정): down_force 계열 — 물리적으로 맞는 자동 후보 excessive_down_force를
        # cmp_edge_overpolish에 잇는다. Center CMP(center_polishing_too_fast→cmp_center_overpolish)가
        # 이어지듯 Edge CMP도 대칭으로 이어지게(mapping_table의 param=down_force와도 정합).
        "excessive down force", "down force", "downforce", "high down force",
        "excessive polishing pressure",
    ],
    "clean_residue": [
        "clean residue", "cleaning residue", "chemical residue",
        "residue accumulation", "residual particles", "insufficient rinsing",
    ],
    # Center
    "deposition_center_thickness": [
        "deposition thickness", "thickness gradients", "film thickness inconsistencies",
        "thin film deposition non uniformities", "center thickness", "showerhead",
        "deposition variations",
    ],
    "cmp_center_overpolish": [
        "center overpolish", "center polished too fast", "inadequate or uneven cmp",
        "uneven cmp", "center over polish",
    ],
    "clean_nozzle_clog": [
        "nozzle clog", "clean nozzle", "spray nozzle", "central residue",
        "particle accumulations near the chuck center",
    ],
    # Scratch
    "cmp_pad_wear": [
        "pad wear", "pad condition", "worn pad", "pad degrade", "conditioning", "pad usage",
    ],
    "cmp_slurry_particle": [
        "slurry particle", "abrasive particles", "particle agglomeration",
        "large particle", "slurry contamination", "over pressure",
    ],
    "clean_brush_contact": [
        "brush contact", "brush", "particle shedding", "aging components",
    ],
}

DRIFT_TO_DIRECTION = {
    "step_up": "high", "linear_up": "high",
    "step_down": "low", "linear_down": "low",
}

MAPPING_MATCH_THRESHOLD = 0.55
# (P2-b) 비어있지 않은 path.step을 매핑 공정으로 '교정'하는 건 강한 매칭일 때만 한다.
# 느슨한 매칭이 추출된 정본 step을 덮어써 오히려 오연결을 만드는 걸 막는다
# (키워드 substring 포함은 _similarity가 1.0을 주므로 0.85면 앵커 매칭만 통과한다).
MAPPING_STEP_OVERRIDE_THRESHOLD = 0.85


def _norm_text(raw: str) -> str:
    return re.sub(r"[\s\-_]+", " ", str(raw).strip().lower())


def load_mapping_table() -> dict[str, list[dict]]:
    if not MAPPING_PATH.exists():
        return {}
    data = yaml.safe_load(MAPPING_PATH.read_text(encoding="utf-8")) or {}
    return {pattern: entries or [] for pattern, entries in data.items()}


def _load_fab_param_ids() -> set[str]:
    data = json.loads((SEEDS_DIR / "parameters.json").read_text(encoding="utf-8"))
    return {n["id"] for n in data["nodes"]}


MAPPING_TABLE = load_mapping_table()
FAB_PARAM_IDS = _load_fab_param_ids()


def _similarity(cause_text: str, surface: str) -> float:
    """부분일치(1.0) > 토큰 자카드 > difflib 순으로 가장 후한 점수."""
    if surface in cause_text or cause_text in surface:
        return 1.0
    a, b = set(cause_text.split()), set(surface.split())
    jaccard = len(a & b) / len(a | b) if a | b else 0.0
    ratio = difflib.SequenceMatcher(None, cause_text, surface).ratio()
    return max(jaccard, ratio)


def match_mapping(pattern: str, cause_id: str, cause_name: str) -> tuple[dict, float] | None:
    """
    이 패턴 섹션의 표 항목 중 Cause와 가장 유사한 것. 임계값 미달이면 None.
    매칭 표면 = 표의 cause id + KG 모듈이 소유한 MAPPING_MATCH_KEYWORDS (yaml은 손대지 않는다).
    """
    cause_text = _norm_text(f"{cause_id} {cause_name}")
    best, best_score = None, 0.0
    for entry in MAPPING_TABLE.get(pattern, []):
        table_cause = entry.get("cause", "")
        surfaces = [table_cause, *MAPPING_MATCH_KEYWORDS.get(table_cause, [])]
        score = max(_similarity(cause_text, _norm_text(s)) for s in surfaces if s)
        if score > best_score:
            best, best_score = entry, score
    if best is not None and best_score >= MAPPING_MATCH_THRESHOLD:
        return best, best_score
    return None


def apply_mapping_fill(pattern: str, rows: list[dict]) -> int:
    """매핑 표를 오버레이한다. 반환 = 매칭된 행 수. row["mapping"]에 근거를 남긴다.

    두 가지를 한다:
      (1) matched_cause 라벨링 — **tier 무관하게** 모든 매칭 행에 붙인다(P1, 비대칭 해소).
          E2E 평가가 KG cause를 시뮬레이터 어휘(ground truth)로 대조하려면 자동/반자동 후보에도
          matched_cause가 있어야 한다. 없으면 물리적으로 맞는 자동 후보(예: Edge-Ring
          excessive_down_force → cmp_edge_overpolish)가 채점에서 통째로 빠진다 — Center CMP는
          이어지는데 Edge CMP만 누락되던 비대칭이 여기서 생겼다.
      (2) 검증 신호 채움·[자동] 승격·step 교정 — **[근거없음] 행에만** 한다. 이미 검증된
          (자동/반자동) 행의 evidence/step/direction은 문헌 추출 정본이라 건드리지 않고 라벨만 얹는다.
          (kg_client는 mapping에서 matched_cause·process만 읽으므로 라벨 부착은 런타임 무해.)
    """
    matched = 0
    for row in rows:
        hit = match_mapping(pattern, row["cause"], row["cause_name"] or "")
        if hit is None:
            continue
        entry, score = hit
        sig = entry.get("telemetry_signature") or {}
        param, drift = sig.get("param"), sig.get("drift")

        # (1) matched_cause 라벨 — tier 무관(P1)
        row["mapping"] = {
            "matched_cause": entry.get("cause"),
            "score": round(score, 3),
            "process": entry.get("process"),
            "prob": entry.get("prob"),
            "param": param,
            "drift": drift,
            "citation": entry.get("citation"),
            "param_in_fab_vocab": param in FAB_PARAM_IDS,
        }
        matched += 1

        # (2) 검증 신호 채움·승격·step 교정은 [근거없음] 행에만.
        if row["tier"] != TIER_NONE:
            continue

        # step 보충·교정 (P2, eval_scenario_kg_proposal.md — path.step ↔ mapping.process 불일치).
        # (a) 문헌직결(direct) 행은 step=NULL(DIRECT_QUERY) — 매칭이 특정한 공정으로 보충한다.
        #     신호(param/drift)만 채우고 조사 장소를 비워두면 backend가 엉뚱한 장비에서 param을
        #     찾다 기각된다(0723 E2E 실측: 정답 가설 사망 경로).
        # (b) step이 채워졌더라도 매핑이 지목한 공정과 다르면(추출 오연결, 예: DEPO≠CLEAN)
        #     교정한다 — 단 강한 매칭일 때만(MAPPING_STEP_OVERRIDE_THRESHOLD). mapping_table은
        #     큐레이션된 fab 어휘 브리지라 키워드 앵커가 강하게 맞으면 추출 step보다 신뢰도가 높다.
        #     KG가 자기완결적으로 교정하면 backend의 step=None 폴백(D14)은 자연 무동작이 된다.
        #     조용히 덮지 않고 로그로 남긴다(무엇을 왜 바꿨는지 드러냄).
        mapped_process = entry.get("process")
        if mapped_process and row["step"] != mapped_process:
            if row["step"] is None:
                print(f"    · step 보충(P2-a): None → {mapped_process}  [{row['cause']}]")
                row["step"] = mapped_process
            elif score >= MAPPING_STEP_OVERRIDE_THRESHOLD:
                print(f"    · step 교정(P2-b): {row['step']} → {mapped_process}  "
                      f"[{row['cause']}] (매핑 {entry.get('cause')}, score={score:.2f})")
                row["step"] = mapped_process
            # 약한 매칭(score < 임계)에서 non-None step은 건드리지 않는다 — 추출 정본 보존.

        # fab 어휘에 있는 param일 때만 [자동] 승격. 아니면 힌트로만 남긴다.
        if param in FAB_PARAM_IDS:
            row["tier"] = TIER_AUTO
            row["evidence"] = param
            row["evidence_name"] = param
            row["evidence_label"] = "Parameter"
            row["fab_table"] = "telemetry"
            row["direction"] = DRIFT_TO_DIRECTION.get(drift)
    return matched


# 같은 (공정, 고장, 원인, 신호) 꼬리를 두 경로가 모두 찾으면 한 가설로 합치되,
# 패턴을 직접 지목한 문헌(step)이 형상 서술(signature)보다 강한 근거다.
ROUTE_RANK = {"step": 2, "signature": 1, "direct": 0}


def fetch_hypotheses(graph: Neo4jGraph, pattern: str) -> list[dict]:
    """패턴 진입(①): ARISES_IN(step) + HAS_SIGNATURE→FORMS_IN(signature) + ATTRIBUTED_TO(direct)."""
    rows = graph.query(HYPOTHESIS_QUERY, params={"pattern": pattern})
    for row in rows:
        row["route"] = "step"
    for row in graph.query(SIGNATURE_QUERY, params={"pattern": pattern}):
        row["route"] = "signature"
        rows.append(row)
    rows += graph.query(DIRECT_QUERY, params={"pattern": pattern})
    return _rank_and_sort(rows, pattern)


def fetch_hypotheses_by_signature(graph: Neo4jGraph, signature: str) -> list[dict]:
    """형상 직접 진입: shape@zone에서 pattern 없이 순회한다(미지 패턴 대응).

    FORMS_IN 경로만 나오므로 morphology가 모든 후보에 보존된다. mapping_table 오버레이는
    패턴 키가 없어 건너뛴다(pattern=None). backend 라이브 조회가 이 함수를 재사용한다.
    """
    rows = graph.query(SIGNATURE_ENTRY_QUERY, params={"signature": signature})
    for row in rows:
        row["route"] = "signature"
    return _rank_and_sort(rows, pattern=None)


def fetch_hypotheses_step_direct(graph: Neo4jGraph, pattern: str) -> list[dict]:
    """패턴 진입에서 **형상 경로만 뺀** 것: ARISES_IN(step) + ATTRIBUTED_TO(direct).

    backend의 자연어 진입용 — 기지 패턴에서 형상 경로는 VLM 자연어가 고른 시그니처의 순회로 대체하되,
    패턴 레벨 원인(공정 경유·문헌 직결)은 이 함수로 유지한다. signature 경로는 여기서 빼서
    NL-선정 시그니처의 morphology 보존 후보와 dedup 충돌하지 않게 한다.
    """
    rows = graph.query(HYPOTHESIS_QUERY, params={"pattern": pattern})
    for row in rows:
        row["route"] = "step"
    rows += graph.query(DIRECT_QUERY, params={"pattern": pattern})
    return _rank_and_sort(rows, pattern)


def _rank_and_sort(rows: list[dict], pattern: str | None) -> list[dict]:
    """진입 경로에서 나온 원시 행들을 dedup·점수화·정렬해 가설 목록으로 만든다.

    pattern 진입(fetch_hypotheses)과 형상 진입(fetch_hypotheses_by_signature)이 공유한다.
    pattern=None이면 mapping_table 오버레이를 건너뛴다.
    """
    # 완전히 같은 경로 꼬리만 합친다. (원인, 검증신호)로만 묶으면 서로 다른 공정·고장 모드를
    # 거친 별개의 가설이 하나로 뭉개진다. route는 키에서 뺀다 — step 경유와 signature 경유가
    # 같은 꼬리에 닿으면 같은 가설이고, 더 강한 경로(ROUTE_RANK)의 것을 대표로 남긴다.
    best: dict[tuple, dict] = {}
    for row in rows:
        row.setdefault("signature", None)
        # 모폴로지는 FORMS_IN(형상 경유) 엣지에만 있다. step/direct 경로엔 없으므로 기본값.
        row.setdefault("density", None)
        row.setdefault("continuity", None)
        row.setdefault("angular_coverage", None)
        row.setdefault("clock_positions", None)
        row["tier"] = TIER_OF_LABEL.get(row["evidence_label"], TIER_NONE)
        key = (row["step"], row["failure_mode"], row["cause"], row["evidence"])
        prior = PRIOR_RANK.get(row["occurrence_prior"], 1)
        row["_score"] = (row["tier"], prior, row["confidence"], ROUTE_RANK[row["route"]])
        if key not in best or row["_score"] > best[key]["_score"]:
            best[key] = row

    survivors = list(best.values())

    # 매핑 테이블 오버레이 — 모든 tier에 matched_cause 라벨(P1) + [근거없음]은 검증신호 채움/승격.
    matched = apply_mapping_fill(pattern, survivors)
    if matched:
        print(f"  (mapping_table: {matched}건 매칭 — matched_cause 라벨 + [근거없음] 검증신호 채움)")

    # =========================
    # 순위 — 검증 가능성(tier)이 아니라 문헌 근거로 매긴다.
    #   (occurrence_prior, 근거 문서 수, 근거 청크 수) 내림차순.
    #   tier는 "어떻게 확인하느냐"의 분류이지 그럴듯함이 아니므로 순위에서 뺀다.
    #   confidence(LLM 자기평가)도 순위·출력에서 제외 — 근거 빈도는 측정값이라 신뢰 가능.
    #   동점은 cause 이름순으로 고정해 실행마다 순서가 바뀌지 않게 한다.
    # =========================
    for row in survivors:
        chunks = set(row.get("chunk_ids") or [])
        row["evidence_chunks"] = len(chunks)
        row["evidence_docs"] = len({c.split("#")[0] for c in chunks})

    survivors.sort(key=lambda r: (r["cause"] or "", r["evidence"] or ""))   # 결정적 tiebreak
    survivors.sort(
        key=lambda r: (
            PRIOR_RANK.get(r["occurrence_prior"], 1),
            r["evidence_docs"],
            r["evidence_chunks"],
        ),
        reverse=True,
    )
    return survivors if TOP_K is None else survivors[:TOP_K]


# =========================
# 2. 가설 문장 생성 (LLM은 여기서만 쓴다)
# =========================

class Hypotheses(BaseModel):
    hypotheses: list[str] = Field(
        description="가설 문장 리스트. 입력으로 준 경로 순서를 그대로 유지한다. 번호는 붙이지 않는다."
    )


SYNTHESIS_PROMPT = """
반도체 웨이퍼 결함 근본원인 분석(RCA) 결과를 보고합니다.

관측된 불량 패턴: {pattern}

지식그래프에서 아래 {n}개의 인과 경로를 찾았습니다.
각 경로를 한국어 가설 문장 하나로 옮기세요.

경로:
{paths}

작성 규칙:
- 경로 하나당 문장 하나. 입력 순서를 그대로 유지하세요.
- 주어진 사실만 쓰고 새로운 원인이나 검증 신호를 지어내지 마세요.
- 각 문장에 공정, 고장 모드, 근본 원인, 검증 방법을 모두 담으세요.
- "{pattern} 패턴은 ... 로 보이며, ...를 확인해야 합니다" 같은 가설 어투로 쓰세요.
- 검증 신호가 [자동]이면 direction이 high일 때 "값이 높은지", low면 "값이 낮은지" 확인하라고 쓰세요.
- 검증 신호가 [반자동] Maintenance면 "정비 이력을 확인해야 합니다",
  [반자동] Recipe면 "사용된 레시피를 확인해야 합니다"로 쓰세요.
- 검증 신호가 [근거없음]이면 "fab 데이터로는 확인할 수 없어 문헌 근거로만 남습니다"라고 덧붙이세요.
- 경로가 "문헌 직결"이면 공정을 언급하지 말고, 문헌이 이 패턴의 원인으로 지목했다고 쓰세요.
- 경로가 "형상 경유"이면 "이 패턴의 형상(예: 가장자리 링)이 주로 X 공정에서 생긴다는 문헌 근거"임을 밝히세요.
- 문장 앞에 번호를 붙이지 마세요.
"""


def describe_path(row: dict) -> str:
    label = row["evidence_label"]
    tag = TIER_TAG[row["tier"]]
    if label == "Parameter":
        direction = {"high": "높음", "low": "낮음"}.get(row["direction"], "이상 여부")
        verify = f"[{tag}] 계측 변수 {row['evidence']} (예상 방향: {direction})"
    elif label == "Maintenance":
        verify = f"[{tag}] 정비 이력 조회: {row['evidence_name']} — 판정은 사람이"
    elif label == "Recipe":
        verify = f"[{tag}] 레시피 조회: {row['evidence_name']} — 기대값이 없어 판정은 사람이"
    else:
        verify = f"[{tag}] 문헌 서술만 있음. fab 데이터로 확인 불가"

    if row["route"] == "direct":
        head = "- 경로: 문헌이 패턴에서 원인을 바로 지목 (공정 미상)\n"
    elif row["route"] == "signature":
        head = (
            f"- 경로: 형상 경유 — 문헌이 형상({row['signature']})으로 공정을 지목\n"
            f"  공정: {row['step']}\n"
            f"  고장 모드: {row['failure_mode_name']} ({row['failure_mode']})\n"
        )
    else:
        head = (
            f"- 공정: {row['step']}\n"
            f"  고장 모드: {row['failure_mode_name']} ({row['failure_mode']})\n"
        )

    return (
        f"{head}"
        f"  근본 원인: {row['cause_name']} ({row['cause']})\n"
        f"  원인 설명: {row['cause_description']}\n"
        f"  검증 신호: [{label}] {verify}"
    )


def _fallback_sentence(pattern: str, row: dict) -> str:
    """LLM이 문장을 덜 돌려줬을 때. 가설을 조용히 버리느니 사실만 이어 붙인다."""
    where = "문헌이 직접 지목" if row["route"] == "direct" else f"{row['step']} 공정"
    return (
        f"{pattern} 패턴은 {where}의 {row['cause_name']}이(가) 원인으로 보입니다. "
        f"검증 신호: {row['evidence']} [{TIER_TAG[row['tier']]}]"
    )


def synthesize(llm, pattern: str, rows: list[dict]) -> list[str]:
    """
    경로가 수십 개일 수 있으므로 배치로 나눠 부른다.
    LLM이 배치 크기와 다른 개수를 돌려줘도 가설이 유실되지 않도록 길이를 맞춘다.
    """
    structured = llm.with_structured_output(Hypotheses, method="json_schema")
    sentences: list[str] = []

    for start in range(0, len(rows), SYNTHESIS_BATCH):
        batch = rows[start:start + SYNTHESIS_BATCH]
        paths = "\n".join(describe_path(r) for r in batch)
        prompt = SYNTHESIS_PROMPT.format(pattern=pattern, n=len(batch), paths=paths)

        try:
            got = structured.invoke(prompt).hypotheses
        except Exception as exc:                      # noqa: BLE001
            print(f"  (경고: 문장 합성 실패, 사실만 출력합니다 — {type(exc).__name__})")
            got = []

        if len(got) != len(batch):
            print(f"  (경고: 문장 {len(got)}개 / 경로 {len(batch)}개 — 부족분은 자동 생성)")
        got = got[:len(batch)]
        got += [_fallback_sentence(pattern, r) for r in batch[len(got):]]
        sentences.extend(got)

    return sentences


# =========================
# 3. 실행
# =========================

def load_pattern_ids() -> list[str]:
    data = json.loads((SEEDS_DIR / "defect_patterns.json").read_text(encoding="utf-8"))
    return [n["id"] for n in data["nodes"]]


def main() -> None:
    graph = Neo4jGraph(
        url=NEO4J_URI,
        username=NEO4J_USERNAME,
        password=NEO4J_PASSWORD,
        database=NEO4J_DATABASE,
    )
    llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0)

    print(LEGEND)
    print()

    report = {
        "meta": {
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "model": OPENAI_MODEL,
            "neo4j_database": NEO4J_DATABASE,
            "top_k": TOP_K,
            "tier_legend": {
                "자동": "Parameter. telemetry.param과 결정적 조인 + 정상범위 판정. agent가 결론까지.",
                "반자동": "Maintenance/Recipe. fab 테이블 조회는 되지만 판정은 사람 몫.",
                "근거없음": "evidence 없는 문헌 서술. fab 데이터로 확인 불가.",
            },
            "score_note": "순위 = (occurrence_prior, evidence_docs, evidence_chunks) 내림차순 — 전부 측정값. "
                          "검증 등급(tier)은 확인 방법의 분류일 뿐 그럴듯함이 아니므로 순위에 반영하지 않는다. "
                          "LLM 자기평가(confidence)는 출력에서 제외.",
        },
        "questions": [],
    }

    for pattern in load_pattern_ids():
        print("=" * 80)
        print(f"패턴: {pattern}")
        print()

        rows = fetch_hypotheses(graph, pattern)

        entry = {
            "pattern": pattern,
            "counts": {},
            "hypotheses": [],
        }
        report["questions"].append(entry)

        if not rows:
            print("가설 없음. 그래프에 이 패턴의 경로가 없습니다.")
            print("(공정 경유: DefectPattern→ProcessStep→FailureMode→Cause→Evidence)")
            print("(문헌 직결: DefectPattern→Cause)")
            print()
            continue

        by_tier = collections.Counter(TIER_TAG[r["tier"]] for r in rows)
        entry["counts"] = {
            "total": len(rows),
            "by_tier": dict(by_tier),
        }
        summary = ", ".join(f"{TIER_TAG[t]} {by_tier[TIER_TAG[t]]}건"
                            for t in (TIER_AUTO, TIER_SEMI, TIER_NONE) if by_tier[TIER_TAG[t]])
        print(f"가설 {len(rows)}건 — {summary}")
        if TOP_K is not None:
            print(f"  (TOP_K={TOP_K} 환경변수가 설정돼 상위 {TOP_K}건만 출력합니다)")
        print()

        for i, (sentence, row) in enumerate(zip(synthesize(llm, pattern, rows), rows), start=1):
            print(f"{i}. {sentence}")

            if row["route"] == "direct":
                trail = f"{pattern} -[ATTRIBUTED_TO]-> {row['cause']}"
                if row["evidence_label"] != "None":
                    trail += f" -[VERIFIED_BY]-> ({row['evidence_label']}) {row['evidence']}"
            elif row["route"] == "signature":
                trail = (
                    f"{pattern} -[HAS_SIGNATURE]-> {row['signature']}"
                    f" -[FORMS_IN]-> {row['step']}"
                    f" <-[OCCURS_IN]- {row['failure_mode']}"
                    f" -[CAUSED_BY]-> {row['cause']}"
                    f" -[VERIFIED_BY]-> ({row['evidence_label']}) {row['evidence']}"
                )
            else:
                trail = (
                    f"{pattern} -[ARISES_IN]-> {row['step']}"
                    f" <-[OCCURS_IN]- {row['failure_mode']}"
                    f" -[CAUSED_BY]-> {row['cause']}"
                    f" -[VERIFIED_BY]-> ({row['evidence_label']}) {row['evidence']}"
                )
            print(f"   근거: {trail}")

            mapping = row.get("mapping")
            if row["tier"] == TIER_AUTO:
                src = f" [mapping_table: {mapping['matched_cause']}, prob={mapping['prob']}]" if mapping else ""
                print(
                    f"   검증: [자동] agent가 판정. {row['fab_table']}.param = '{row['evidence']}'"
                    f" 를 정상범위와 비교 (예상 이탈 방향: {row['direction']}){src}"
                )
            elif row["tier"] == TIER_SEMI:
                hint = scenario_hint(row)
                print(
                    f"   검증: [반자동] agent가 {row['fab_table']} 테이블을 조회, 판정은 사람이"
                    f" — {row['evidence_name']}"
                    + (f" (체인 {hint})" if hint else "")
                )
            else:
                print("   검증: [근거없음] fab 데이터에 연결되지 않음. 문헌 서술로만 존재합니다")
                if row.get("unverifiable_signals"):
                    print(f"          문헌이 지목한 신호(fab 계측 없음): "
                          f"{', '.join(row['unverifiable_signals'])} — 부족한 데이터로 기록(C2)")
                if mapping:
                    hint = f"param={mapping['param']}" if mapping["param"] not in (None, "none") \
                        else f"process={mapping['process']} (이력 단서)"
                    warn = "" if mapping["param_in_fab_vocab"] or mapping["param"] in (None, "none") \
                        else " ⚠ fab 어휘 밖 param — 승격 불가(X1)"
                    print(f"          mapping_table 힌트: {mapping['matched_cause']}"
                          f" (prob={mapping['prob']}, {hint}){warn}")
            print()

            # 경로 종류(공정 경유/형상 경유/문헌 직결)는 별도 필드 없이
            # path의 null 패턴으로 판별한다: step만 있으면 공정 경유,
            # signature가 있으면 형상 경유, 둘 다 null이면 문헌 직결.
            entry["hypotheses"].append({
                "rank": i,
                "sentence": sentence,
                "tier": TIER_TAG[row["tier"]],
                # MCP 검증 체인 라우팅: A3(텔레메트리)/A5(레시피)/A2(일반 정비)/A6(소모품)/null(체인 없음)
                "scenario_hint": scenario_hint(row),
                "path": {
                    "signature": row["signature"],
                    # 형상 경유(FORMS_IN)일 때만 채워지는 모폴로지. VLM 관측과 소프트 매칭하는
                    # 랭킹 신호로 backend가 사용한다. 그 외 경로에서는 전부 null.
                    "morphology": None if row["signature"] is None else {
                        "density": row["density"],
                        "continuity": row["continuity"],
                        "angular_coverage": row["angular_coverage"],
                        "clock_positions": row.get("clock_positions") or [],
                    },
                    "step": row["step"],
                    "failure_mode": row["failure_mode"],
                    "cause": row["cause"],
                    "evidence": None if row["tier"] == TIER_NONE else row["evidence"],
                    "evidence_label": row["evidence_label"],
                },
                "verification": {
                    "fab_table": None if row["fab_table"] == "-" else row["fab_table"],
                    "direction": row["direction"],
                    # 문헌이 지목했지만 fab 어휘에 없어 붙이지 못한 신호 (C2 성격 —
                    # '지식 없음'이 아니라 '계측 없음'. agent는 부족한 데이터란에 기록 권장)
                    "unverifiable_signals": row.get("unverifiable_signals") or None,
                },
                # 순위 성분 — 전부 측정값. LLM 자기평가(confidence)와 검증 등급(tier)은
                # 그럴듯함의 근거가 아니므로 점수에 넣지 않는다.
                "score": {
                    "occurrence_prior": row["occurrence_prior"],
                    "evidence_docs": row["evidence_docs"],
                    "evidence_chunks": row["evidence_chunks"],
                },
                "provenance": {
                    # 경로 세 엣지의 chunk_ids를 이어붙인 것이라 중복 제거 (순서 유지)
                    "chunk_ids": list(dict.fromkeys(row.get("chunk_ids") or [])),
                    "quotes": row.get("quotes") or [],
                },
                # mapping_table.yaml 오버레이로 채워진 경우만 non-null.
                "mapping": row.get("mapping"),
            })

    out_path = BASE_DIR / "outputs" / "hypotheses.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    total = sum(len(q["hypotheses"]) for q in report["questions"])
    print("=" * 80)
    print(f"JSON 저장: {out_path}  (가설 {total}건)")


if __name__ == "__main__":
    main()
