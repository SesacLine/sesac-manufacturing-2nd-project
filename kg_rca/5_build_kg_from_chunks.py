import os
import re
import sys
import json
from pathlib import Path
from typing import Literal, Optional, get_args

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Windows 콘솔(cp949)에서 em-dash 등 유니코드 출력 시 크래시 방지
sys.stdout.reconfigure(encoding="utf-8")

from langchain_openai import ChatOpenAI
from langchain_neo4j import Neo4jGraph


# =========================
# 1. 환경 변수 / 경로 설정
# =========================

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

CHUNKS_PATH = BASE_DIR / "outputs" / "chunks.jsonl"
OUTPUT_PATH = BASE_DIR / "outputs" / "extracted_kg.jsonl"
SEEDS_DIR = BASE_DIR / "data" / "seeds"

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE")

# KG 추출 모델 — 모델지정_규약_설계서 v2.0 §1·§6-S1.
# ⚠️ 구 코드는 `os.getenv("OPENAI_MODEL", "gpt-5.5")`였다. 두 가지 문제가 있었다:
#   ① 코드 폴백(gpt-5.5)이 .env_example(gpt-5.4-mini)과 달라, .env 없는 환경에서 조용히
#      상위 모델로 올라갔다. 게다가 gpt-5.5는 temperature=0을 거부해 아래 호출이 400으로 죽는다.
#   ② 공통 변수 OPENAI_MODEL을 읽어, 런타임 역할을 티어업하면 KG 재빌드까지 따라 올라갔다.
# KG 산출물(hypotheses.json)은 **고정 대상**이므로 전용 변수 + 리터럴 기본값으로 못박는다.
# 재빌드 모델을 정말 바꿀 때만 KG_EXTRACT_MODEL을 명시할 것(산출물이 통째로 바뀐다).
OPENAI_MODEL = os.getenv("KG_EXTRACT_MODEL", "gpt-5.4-mini")


# =========================
# 2. KG 스키마 정의 (../docs/KG_schema_v1.4.md)
# -------------------------
# 문헌에서 자유롭게 만드는 노드는 FailureMode / Cause / Maintenance / Recipe.
# DefectPattern / ProcessStep / Parameter 는 고정 vocabulary(앵커)이며
# 4번에서 시드로 미리 적재된다. 여기서는 새로 만들지 않고 연결만 한다.
#
#   DefectPattern -[ARISES_IN]->  ProcessStep      (문서 A)
#   FailureMode   -[OCCURS_IN]->  ProcessStep      (문서 B)
#   FailureMode   -[CAUSED_BY]->  Cause            (문서 B)
#   Cause         -[VERIFIED_BY]-> Parameter | Maintenance | Recipe   (문서 B)
#
#   DefectPattern -[ATTRIBUTED_TO]-> Cause         (문서 C: ref56 Table 1)
#   문헌이 공정을 거치지 않고 패턴 -> 원인을 바로 말할 때 쓴다.
#   이 Cause는 공정을 모르므로 Parameter(자동 검증)에 닿지 못한다. 수동 확인 대상이다.
#
#   SpatialSignature -[FORMS_IN]-> ProcessStep     (문서 D: 형상 수준 서술)
#   "ring-shaped pattern at the outer edge reflects issues in cleaning steps"처럼
#   문헌이 패턴 클래스명 없이 형상으로 말할 때 쓴다.
#   DefectPattern -[HAS_SIGNATURE]-> SpatialSignature 는 시드에서 결정적으로 깔리므로(4번),
#   FORMS_IN만 이어지면 패턴 -> 형상 -> 공정 경로가 열린다.
#   미지 패턴(3클래스 외)도 VLM이 형상만 넘기면 이 경로로 가설을 얻는다.
#
# 세 evidence 라벨은 공통 슈퍼라벨 :Evidence 를 함께 갖는다.
# Parameter 만 fab SQL로 자동 검증되고(telemetry.param 조인),
# Maintenance/Recipe 는 조회 힌트라 수동 확인 대상이다.
# =========================

ProcessStepId = Literal["LITHO", "ETCH", "DEPO", "CMP", "CLEAN", "EDS"]

# seeds/defect_patterns.json 과 반드시 동일. id == VLM 출력 클래스
DefectPatternId = Literal["Center", "Scratch", "Edge-Ring"]

# 형상/구역 어휘 — 시드가 아니라 코드 enum으로만 닫는다.
# SpatialSignature 노드는 시딩하지 않고 문서에서 LLM이 추출한다.
# id는 코드가 "{shape}@{zone}"으로 조합하므로 표현이 달라도 id 파편화가 불가능하다.
# VLM의 자유 서술 형상 관측도 (미래의 입력 모듈에서) 같은 enum으로 분류해 진입한다.
ShapeId = Literal["ring", "cluster", "line", "blob", "global", "random"]
ZoneId = Literal["center", "mid", "edge", "any"]

# FORMS_IN 관계의 모폴로지 속성 — 노드가 아니라 엣지에 두는 이유는 아래 주석 참조.
# 노드 정체성은 여전히 shape@zone 하나뿐이고(파편화·clobber 방지), 아래 세 축은
# SpatialSignature 노드가 아니라 FORMS_IN "엣지"에 실린다. VLM 관측(vlm-output-KG 연결)과
# 문헌 목업이 공유하는 어휘 — 조회 시 shape@zone은 하드 매칭, 이 축들은 랭킹 가점(소프트)이라
# 관측과 어긋나도 후보를 버리지 않는다. clock_positions는 angular_coverage=partial일 때만 채운다.
Density = Literal["high", "medium", "low", "unknown"]
Continuity = Literal["continuous", "intermittent", "discontinuous", "not_applicable", "unknown"]
AngularCoverage = Literal["full", "partial", "unknown"]

# grounding용: 이 형상을 말한다고 볼 수 있는 원문 표현들
SHAPE_SURFACES = {
    "ring": ["ring", "annular", "donut", "circular"],
    "cluster": ["cluster", "clustered", "concentrated", "blob", "localized"],
    "line": ["line", "linear", "scratch", "streak", "elongated", "directional"],
    "blob": ["blob", "spot", "concentrated"],
    "global": ["entire", "whole", "global", "full", "wafer-wide"],
    "random": ["random", "sporadic", "scattered"],
}

# seeds/parameters.json 과 반드시 동일. id == fab telemetry.param
ParameterId = Literal[
    "exposure_dose", "focus_offset", "stage_temp", "alignment_offset",
    "rf_power", "chamber_pressure", "he_flow", "temperature", "etch_rate",
    "gas_flow", "susceptor_temp", "deposition_rate",
    "down_force", "slurry_flow", "pad_usage_hours",
    "flow_rate", "megasonic_power", "chemical_temp", "rinse_time",
    "chuck_temp", "contact_resistance",
]

RelationshipKind = Literal[
    "ARISES_IN",       # DefectPattern    -> ProcessStep
    "HAS_SIGNATURE",   # DefectPattern    -> SpatialSignature (문서의 형상 서술에서 추출)
    "FORMS_IN",        # SpatialSignature -> ProcessStep  (형상 수준 서술)
    "ATTRIBUTED_TO",   # DefectPattern    -> Cause   (공정을 거치지 않는 직결 서술)
    "OCCURS_IN",       # FailureMode      -> ProcessStep
    "CAUSED_BY",       # FailureMode      -> Cause
    "VERIFIED_BY",     # Cause            -> Parameter | Maintenance | Recipe
]

# VERIFIED_BY의 대상 라벨. 다형 관계라 LLM이 라벨을 함께 지목해야 한다.
EvidenceLabel = Literal["Parameter", "Maintenance", "Recipe"]

# evidence 라벨 -> 검증에 쓸 fab 테이블
FAB_TABLE = {
    "Parameter": "telemetry",
    "Maintenance": "maintenance",
    "Recipe": "lot_history",
}

PROCESS_STEP_IDS: set[str] = set(get_args(ProcessStepId))
DEFECT_PATTERN_IDS: set[str] = set(get_args(DefectPatternId))
SHAPE_IDS: set[str] = set(get_args(ShapeId))
ZONE_IDS: set[str] = set(get_args(ZoneId))
PARAMETER_IDS: set[str] = set(get_args(ParameterId))


def assert_enums_match_seeds() -> None:
    """
    위 Literal은 LLM에게 넘길 JSON schema를 정적으로 만들어야 해서 하드코딩돼 있다.
    시드 파일만 고치고 여기를 안 고치면, 문서의 해당 엔티티가 enum에 없어서
    validate_kg가 관계를 **조용히 버린다**. 시작하자마자 터뜨린다.
    """
    pairs = [
        ("defect_patterns.json", DEFECT_PATTERN_IDS),
        ("process_steps.json", PROCESS_STEP_IDS),
        ("parameters.json", PARAMETER_IDS),
    ]
    for file_name, enum_ids in pairs:
        data = json.loads((SEEDS_DIR / file_name).read_text(encoding="utf-8"))
        seed_ids = {n["id"] for n in data["nodes"]}
        if seed_ids != enum_ids:
            raise ValueError(
                f"{file_name} 과 이 파일의 Literal이 어긋납니다.\n"
                f"  시드에만 있음: {sorted(seed_ids - enum_ids)}\n"
                f"  코드에만 있음: {sorted(enum_ids - seed_ids)}\n"
                f"둘 중 하나를 고쳐 맞추세요. (프롬프트의 고정 목록도 함께)"
            )


# =========================
# 2.1 앵커 표기 정규화 (canonicalization)
# -------------------------
# LLM은 프롬프트에 canonical id 목록을 받고도 'edge-ring', 'etch' 처럼 표기를 흔든다.
# 시드의 aliases를 역인덱스로 만들어, 버리기 전에 한 번 canonical id로 갈아끼운다.
#
# aliases만 쓰고 spatial_keywords는 쓰지 않는다.
# 후자는 여러 패턴에 동시에 걸려(예: 'ring'이 Edge-Ring/Donut 양쪽) 매칭에 못 쓴다.
# =========================

def _normalize_key(raw: str) -> str:
    """대소문자·하이픈·밑줄·연속 공백 차이를 흡수한다. 'Edge-Ring' == 'edge_ring' == 'edge ring'"""
    return re.sub(r"[\s\-_]+", " ", raw.strip().lower())


def _build_alias_index(file_name: str) -> dict[str, str]:
    data = json.loads((SEEDS_DIR / file_name).read_text(encoding="utf-8"))
    index: dict[str, str] = {}
    for node in data["nodes"]:
        canonical = node["id"]
        for surface in [canonical, node.get("name", canonical), *node.get("aliases", [])]:
            index[_normalize_key(surface)] = canonical
    return index


DEFECT_PATTERN_INDEX = _build_alias_index("defect_patterns.json")
PROCESS_STEP_INDEX = _build_alias_index("process_steps.json")


def resolve_anchor(raw: str, index: dict[str, str]) -> Optional[str]:
    """앵커 표기 하나를 canonical id로. 못 붙이면 None(호출부가 사유를 남기고 버린다)."""
    return index.get(_normalize_key(raw))


# =========================
# 2.2 Parameter 해석은 ProcessStep 조건부다
# -------------------------
# 'temperature' 하나가 공정마다 다른 변수를 가리킨다.
#   LITHO -> stage_temp,  ETCH -> temperature,  DEPO -> susceptor_temp,
#   CLEAN -> chemical_temp,  EDS -> chuck_temp
# 전역 사전 하나로는 항상 한쪽으로만 붙어 조용히 틀린다.
# 그래서 공정별 사전을 따로 만들고, Cause가 속한 공정으로 해석한다.
#
# 같은 공정 안에서 한 표현이 두 파라미터를 가리키면 해석이 불가능하다.
# 그건 시드의 버그이므로 import 시점에 터뜨린다.
# =========================

def _build_parameter_indexes() -> tuple[dict[str, dict[str, str]], dict[str, set[str]]]:
    data = json.loads((SEEDS_DIR / "parameters.json").read_text(encoding="utf-8"))

    by_step: dict[str, dict[str, str]] = {step: {} for step in PROCESS_STEP_IDS}
    steps_of: dict[str, set[str]] = {}

    for node in data["nodes"]:
        canonical = node["id"]
        steps_of[canonical] = set(node["steps"])
        surfaces = {
            _normalize_key(s)
            for s in [canonical, node.get("name", canonical), *node.get("aliases", [])]
        }
        for step in node["steps"]:
            for surface in surfaces:
                clash = by_step[step].get(surface)
                if clash and clash != canonical:
                    raise ValueError(
                        f"parameters.json: 공정 '{step}' 안에서 표현 '{surface}'가 "
                        f"'{clash}'와 '{canonical}' 둘을 가리킵니다. 별칭을 정리하세요."
                    )
                by_step[step][surface] = canonical

    return by_step, steps_of


PARAMETER_INDEX_BY_STEP, PARAMETER_STEPS = _build_parameter_indexes()


def resolve_parameter(raw: str, steps: set[str]) -> tuple[Optional[str], str]:
    """
    Parameter 표기를 canonical id로. steps는 이 Cause가 속한 공정 집합.

    returns (id, reason). 실패하면 id가 None이고 reason에 사유가 담긴다.
    """
    key = _normalize_key(raw)

    if not steps:
        return None, "Cause의 공정을 알 수 없어 Parameter를 해석할 수 없음"

    hits = {
        PARAMETER_INDEX_BY_STEP[step][key]
        for step in steps
        if step in PARAMETER_INDEX_BY_STEP and key in PARAMETER_INDEX_BY_STEP[step]
    }

    if len(hits) == 1:
        return hits.pop(), ""
    if len(hits) > 1:
        return None, f"공정 {sorted(steps)}에서 '{raw}'가 {sorted(hits)} 여럿을 가리켜 모호함"
    return None, f"'{raw}'는 공정 {sorted(steps)}에서 계측되지 않는 변수"


# =========================
# 2.3 앵커 보강 패스 (추출 비결정성 완화)
# -------------------------
# ARISES_IN / FORMS_IN / ATTRIBUTED_TO 는 그래프의 진입점인데, 같은 청크라도
# 실행마다 LLM이 뽑았다 안 뽑았다 한다(temperature=0으로도 안 잡힘).
# 패턴/형상을 언급하는 청크만 골라 K회 재추출해 합집합을 취한다.
# 저장이 MERGE라 중복은 안 생기고, 빠졌던 엣지만 채워진다.
# 검증 규칙(grounding 등)은 매 패스 동일하게 적용되므로 환각이 늘지는 않는다.
# =========================

ANCHOR_PASSES = int(os.getenv("ANCHOR_PASSES", "3"))

_ANCHOR_RE = re.compile(
    r"\b(" + "|".join(
        re.escape(s) for s in
        sorted(set(_build_alias_index("defect_patterns.json"))
               | {w for words in SHAPE_SURFACES.values() for w in words},
               key=len, reverse=True)
    ) + r")\b"
)


def mentions_pattern_or_signature(text: str) -> bool:
    return bool(_ANCHOR_RE.search(_normalize_key(text)))


# canonical ProcessStep id -> 그 공정을 가리키는 모든 표기 (근거 확인용 역방향 맵)
STEP_SURFACES: dict[str, list[str]] = {}
for _surface, _canonical in PROCESS_STEP_INDEX.items():
    STEP_SURFACES.setdefault(_canonical, []).append(_surface)


def step_is_grounded_in(step_id: str, chunk_text: str) -> bool:
    """
    이 청크 원문이 해당 공정을 실제로 언급하는가.

    LLM은 공정 이름이 하나도 없는 서론 문단에서도 ARISES_IN을 지어낸다(목록 첫 항목인
    LITHO를 자리채움으로 고름). 프롬프트로는 안 막혀서 여기서 결정적으로 거른다.
    """
    haystack = _normalize_key(chunk_text)
    return any(
        re.search(rf"\b{re.escape(surface)}\b", haystack)
        for surface in STEP_SURFACES.get(step_id, [])
    )


## 언어 규약(0728): 아래 스키마 문자열은 Pydantic이 JSON schema로 만들어 **LLM에 그대로
## 전달**되므로 프롬프트의 일부다 — 클래스 docstring도 모델 description으로 실린다.
## KG 산출물은 전부 영어로 뽑고 한국어 전환은 6번 번역 패스에서 한 번만 한다.
## (⑦ VLM description과 같은 경계 규약 — 생성과 번역을 한 LLM에 섞지 않는다.)


class FailureModeNode(BaseModel):
    """A failure mode occurring inside a process step. e.g. post-etch residue, metal corrosion."""
    id: str = Field(description="Unique key. lowercase snake_case. e.g. post_etch_residue")
    name: str = Field(description="Failure mode name exactly as written in the source document. e.g. excessive post-etch residue")
    description: str = Field(description="One complete sentence in English.")
    aliases: list[str] = Field(default_factory=list, description="Alternative names used in the source document")


class CauseNode(BaseModel):
    """A root cause behind a failure mode. e.g. high etch rate, nonuniform etch process."""
    id: str = Field(description="Unique key. lowercase snake_case. e.g. high_etch_rate")
    name: str = Field(description="Cause name exactly as written in the source document. e.g. incorrect process parameter (high etch rate)")
    description: str = Field(description="One complete sentence in English. It is later reused as a building block of the hypothesis sentence.")
    aliases: list[str] = Field(default_factory=list, description="Alternative names used in the source document")


class MaintenanceNode(BaseModel):
    """
    A maintenance action, taken from the 'Corrective Action' column of the source document.
    The cause column only carries a vague expression such as 'Improper maintenance',
    while the concrete action (e.g. chamber wet clean) is written in the action column.
    """
    id: str = Field(description="Unique key. lowercase snake_case. e.g. chamber_wet_clean")
    name: str = Field(description="Exactly as written in the source document. e.g. chamber wet clean")
    description: str = Field(description="One complete sentence in English.")
    consumable: bool = Field(
        description="true if this is about replacement/wear/lifetime of a consumable "
                    "(pad, brush, slurry, filter, conditioner, ...); "
                    "false for general maintenance, cleaning, inspection or calibration. "
                    "e.g. replace polishing pad -> true, chamber wet clean -> false"
    )


class RecipeNode(BaseModel):
    """A recipe to be checked as a verification signal. e.g. process recipe."""
    id: str = Field(description="Unique key. lowercase snake_case. e.g. process_recipe")
    name: str = Field(description="Exactly as written in the source document. e.g. process recipe")
    description: str = Field(description="One complete sentence in English.")


class SignatureNode(BaseModel):
    """
    A wafer-map spatial signature = (shape, zone) pair, extracted from morphology
    descriptions in the document. The code composes the id as "{shape}@{zone}",
    so the model only has to pick the two enums.
    """
    shape: ShapeId = Field(description="Shape. e.g. ring-shaped -> ring, linear streaks -> line")
    zone: ZoneId = Field(description="Zone. e.g. outer edge -> edge, geometric center -> center, whole wafer/unspecified -> any")
    description: str = Field(default="", description="Short summary of the morphology description in the source text")

    @property
    def id(self) -> str:
        return f"{self.shape}@{self.zone}"


class Relationship(BaseModel):
    """
    kind 별 (source, target) 규약:
      - ARISES_IN   : DefectPattern id -> ProcessStep id
      - OCCURS_IN   : FailureMode id   -> ProcessStep id
      - CAUSED_BY   : FailureMode id   -> Cause id
      - VERIFIED_BY : Cause id         -> Parameter | Maintenance | Recipe id
                      (target_label 로 어느 라벨인지 반드시 지목)
    """
    kind: RelationshipKind
    source: str = Field(description="id of the source node")
    target: str = Field(description="id of the target node")

    target_label: Optional[EvidenceLabel] = Field(
        default=None,
        description="VERIFIED_BY only: label of the target node. Leave empty for every other kind.",
    )
    direction: Optional[Literal["high", "low"]] = Field(
        default=None,
        description="VERIFIED_BY + target_label=Parameter only: direction of the parameter deviation",
    )
    occurrence_prior: Optional[Literal["high", "mid", "low"]] = Field(
        default=None, description="ARISES_IN/FORMS_IN only: how common the source document says this is (commonly/rare)"
    )
    density: Optional[Density] = Field(
        default=None,
        description="FORMS_IN only: defect density. dense->high, moderate->medium, sparse->low. null if not mentioned.",
    )
    continuity: Optional[Continuity] = Field(
        default=None,
        description="FORMS_IN only: continuity of the shape. continuous->continuous, broken/intermittent->intermittent, "
                    "fragmented->discontinuous. Use not_applicable when continuity does not apply to the shape "
                    "(e.g. a blob at the center). null if not mentioned.",
    )
    angular_coverage: Optional[AngularCoverage] = Field(
        default=None,
        description="FORMS_IN only: angular coverage. all around/full circumference->full, "
                    "one side/partial/arc->partial. null if not mentioned.",
    )
    clock_positions: list[int] = Field(
        default_factory=list,
        description="FORMS_IN only: clock positions 1-12 (duplicates allowed). Fill only when "
                    "angular_coverage=partial; leave the list empty when it is full.",
    )
    extraction_confidence: float = Field(description="Extraction confidence 1-5. Score low when uncertain.")
    description: str = Field(description="One complete sentence in English supporting this relationship")
    quotes: list[str] = Field(default_factory=list, description="Short verbatim snippets from the source text as evidence")


class RcaGraph(BaseModel):
    failure_modes: list[FailureModeNode]
    causes: list[CauseNode]
    maintenance: list[MaintenanceNode]
    recipes: list[RecipeNode]
    signatures: list[SignatureNode]
    relationships: list[Relationship]


# =========================
# 3. 프롬프트
# =========================

def build_prompt(chunk: dict) -> str:
    return f"""
The following is an excerpt from the literature on root cause analysis (RCA) of
semiconductor wafer defects.
Extract failure modes (FailureMode), causes (Cause), verification signals (Evidence)
and the relationships between them from this excerpt as a knowledge graph.

Chunk metadata:
- chunk_id: {chunk['chunk_id']}
- doc_id: {chunk.get('doc_id')}

Extraction rules:
- Extract only what is explicitly stated in the source text. Do not speculate.
- If there is nothing meaningful, return every list empty.
- Node ids are lowercase snake_case. e.g. post_etch_residue, high_etch_rate
- Write every description as one complete sentence in English.
- Do not turn a process parameter itself (rf_power, etch_rate, ...) into a Cause.
  Parameters are used only as the target of VERIFIED_BY.
  Only a statement carrying a deviation direction, such as "etch rate too high", is a Cause.
- Do not mix up FailureMode (the symptom) and Cause (the reason behind it).
  e.g. "excessive post-etch residue" is a FailureMode, "nonuniform etch process" is a Cause.
- A corrective action or prescription ("correct the ...", "inspect the ...") is NOT a Cause.
  A maintenance action appearing in an action sentence becomes a Maintenance node only.

If this chunk is one row of a troubleshooting table, the labels below are attached.
The columns play different roles.

  Process: <ProcessStep>     <- the OCCURS_IN target of this row. Use this process as given.
  Table type: troubleshooting
  [failure mode]  -> exactly one FailureMode
  [cause]         -> Cause candidates. If the entries are split as "A." "B.", make **one Cause per entry**
  [action]        -> the corrective action sentence. **Never turn this into a Cause.**
                     Only the concrete maintenance actions here (chamber wet clean,
                     replace thermocouple, ...) become Maintenance nodes, connected from the
                     corresponding Cause with VERIFIED_BY.

  Table type: quality
  [quality item]  -> a measured item. Do not make a node out of it.
  [defect type]   -> FailureMode
  [remarks]       -> a Cause if a cause is described. Exclude action-like sentences ("check the ...").

  Table type: pattern_cause  (wafer-map pattern -> cause directly; there is no process row)
  [defect pattern] -> DefectPattern. If it is not one of the fixed 3, skip this row entirely.
  [pattern description] -> Do not make a node out of it.
  [cause]         -> Cause. If several causes are separated by commas or "or", make
                     **a separate Cause for each** and link them from the DefectPattern with
                     ATTRIBUTED_TO. Do not create a FailureMode.
                     If the cause sentence names a process (e.g. "during chemical-mechanical
                     polishing (CMP)"), also create ARISES_IN.

Handle vague expressions in the cause column like this:
  "Improper maintenance"      -> make it a Cause, VERIFIED_BY -> Maintenance (the concrete action in the action column)
  "Incorrect process recipe"  -> make it a Cause, VERIFIED_BY -> Recipe ("process recipe")

The three lists below are fixed. Do not invent new entries; choose only from the lists.
If no entry applies, do not extract that relationship at all.

Process steps (ProcessStep), 6 of them:
  LITHO, ETCH, DEPO, CMP, CLEAN, EDS

Defect patterns (DefectPattern), 3 of them:
  Center, Scratch, Edge-Ring
  (only spatial patterns on the wafer map. "circular ring"->Edge-Ring, "bulls eye"->Center,
   "linear defect"/"scuff mark"->Scratch)

Spatial signature (SpatialSignature) — a node extracted from morphology descriptions:
  Put the shape and zone enums into the signatures list.
    shape, 6 of them: ring, cluster, line, blob, global, random
    zone, 4 of them: center, mid, edge, any (use any when unspecified)
  When a relationship points at this node, use an id of the form "{{shape}}@{{zone}}".
    "ring-shaped pattern at the outer edge" -> shape=ring, zone=edge -> id "ring@edge"
    "concentrated cluster near the geometric center" -> cluster@center
    "linear streaks across the wafer" / "directional scratches" -> line@any
  Create these only when the document actually describes a morphology. Do not create any
  in a chunk that never mentions a shape.

Process parameters (Parameter), 20 of them:
  exposure_dose, focus_offset, stage_temp, alignment_offset,
  rf_power, chamber_pressure, he_flow, temperature, etch_rate,
  gas_flow, susceptor_temp, deposition_rate,
  down_force, slurry_flow,
  flow_rate, megasonic_power, chemical_temp, rinse_time,
  chuck_temp, contact_resistance

There are three kinds of verification signal (Evidence); only Parameter is chosen from the
fixed list above. Maintenance and Recipe are created freely from the wording of the document.
- Parameter   : a measured variable. One of the 20 above. (e.g. rf_power)
                **If you are not sure which variable it is, write the generic wording of the
                document as it stands** (temperature, pressure, gas flow, focus, overlay, ...).
                It is mapped automatically to the variable belonging to the process.
                e.g. for "Incorrect temperature" in ETCH, write 'temperature'. If you pick a
                variable belonging to another process, such as 'chuck_temp', it is discarded.
- Maintenance : a maintenance action, taken from the action sentence.
                (e.g. chamber wet clean, replace defective thermocouple)
                Fill the consumable field: true for replacement/wear/lifetime of a consumable
                (pad/brush/slurry/filter/conditioner), false for general maintenance,
                cleaning, inspection or calibration.
- Recipe      : a recipe to be checked. (e.g. process recipe)

Relationships (kind), 7 of them:
- ARISES_IN:     (DefectPattern) -> (ProcessStep)  "this defect pattern points at this process" (fill occurrence_prior)
- HAS_SIGNATURE: (DefectPattern) -> (SpatialSignature)  "this pattern appears with this shape"
                 Use it when the document describes what the pattern looks like.
                 The target is a "{{shape}}@{{zone}}" id.
                 e.g. "The Edge-Ring defect appears as a ring-shaped pattern near the outer edge"
                     -> add (ring, edge) to signatures + HAS_SIGNATURE: Edge-Ring -> ring@edge
- FORMS_IN:      (SpatialSignature) -> (ProcessStep)  "this shape mostly forms in this process" (fill occurrence_prior)
                 Use it when the document points at a process through a **morphology
                 description** without naming the pattern class.
                 e.g. "This ring-shaped failure pattern at the outer edge reflects issues in cleaning steps"
                     -> FORMS_IN: ring@edge -> CLEAN
                 If the document also describes the **morphology** of the shape, fill the
                 attributes below as well (FORMS_IN only):
                   density: dense->high, moderate->medium, sparse/faint/thin->low
                   continuity: continuous/unbroken->continuous, intermittent->intermittent,
                               broken/fragmented->discontinuous; use not_applicable when
                               continuity does not apply, as for a blob at the center
                   angular_coverage: full circumference/all around/closed all the way around->full,
                                     arc/one side/partial/broken arc->partial
                   clock_positions: when angular_coverage=partial and clock positions are stated,
                                    those numbers (e.g. "5 to 7 o'clock"->[5,6,7]).
                                    Empty list when it is full.
                 Leave them empty when the description does not say
                 (density/continuity/angular_coverage=null, clock_positions=[]).
                 If the same sentence also names a pattern class (Center/Scratch/Edge-Ring),
                 prefer ARISES_IN and do not create FORMS_IN (avoids duplication).
- ATTRIBUTED_TO: (DefectPattern) -> (Cause)        "the cause of this defect pattern is that"
                 Use it when the document jumps straight from the pattern to the cause
                 **without naming a process**.
- OCCURS_IN:   (FailureMode)   -> (ProcessStep)  "this failure mode happens in this process" (exactly one per failure mode)
- CAUSED_BY:   (FailureMode)   -> (Cause)        "the cause of this failure mode is that"
- VERIFIED_BY: (Cause)         -> (Parameter | Maintenance | Recipe)
               "this cause is verified with this signal"
               You must write one of 'Parameter' / 'Maintenance' / 'Recipe' in target_label.
               Fill direction (high/low) only when target_label is 'Parameter'.

How to choose the VERIFIED_BY target:
- If the cause is a deviation of a measured variable -> Parameter (e.g. "RF power drift" -> rf_power)
  A cause stating an excess or a shortfall belongs here too. Record the direction in `direction`.
    "insufficient rinsing"        -> Parameter rinse_time (direction=low)
    "excessive down force"        -> Parameter down_force (direction=high)
    "localized over-pressure"     -> Parameter down_force (direction=high, in a CMP context)
- If the cause is poor maintenance or part degradation -> Maintenance (e.g. "improper maintenance" -> chamber wet clean)
- If the cause is a wrong recipe                       -> Recipe     (e.g. "incorrect process recipe" -> process recipe)

Important:
- Always write node ids in source/target.
  Copy values from the fixed lists **exactly as written above**, including capitalisation.
  e.g. 'Edge-Ring' (O) / 'edge-ring' (X), 'ETCH' (O) / 'etching' (X)
- Create ARISES_IN **only when the process name actually appears in the source text**.
  Do not guess an ARISES_IN in an introductory or summary paragraph that never mentions a process.
- A heading at the top of the chunk such as "## Center pattern" or "## Scratch pattern — Cleaning"
  means **the whole paragraph is about that DefectPattern**.
  When the heading carries a pattern name and the body points at a process, you must create
  the ARISES_IN of that pattern as well, **separately from** the failure mode extraction.
  e.g. "## Scratch pattern — Cleaning" + cleaning described in the body
      -> ARISES_IN: Scratch -> CLEAN (+ extract FailureMode/Cause from the body as usual)
- **A "retaining ring" is a CMP carrier part, not a defect pattern.**
  Do not create an Edge-Ring pattern or a ring shape just because a retaining ring is mentioned.
  Patterns and shapes apply only to descriptions of the defect distribution on the wafer map.
- If a [Metadata] block at the top of the document states a related defect such as
  "Related Defect: Edge Ring" and also names a Process, that is a curated pattern-process
  link, so extract it as ARISES_IN.
- Defect patterns (Center/Scratch/Edge-Ring) are DefectPattern nodes, not FailureMode nodes.
  Do not create a FailureMode such as 'scratch_pattern'. Patterns are used only as the source
  of ARISES_IN. A FailureMode is a failure inside a process (post-etch residue,
  overlay misregistration, ...).
- If the chunk describes "which shape on the wafer map is caused by which process",
  that is an ARISES_IN. Do not turn the shape into a FailureMode; map it to a DefectPattern
  and create ARISES_IN.
    "a center often arises due to problems in the thin film deposition"
        -> ARISES_IN: Center -> DEPO          (O)
        -> FailureMode 'thin_film_deposition_problem'   (X)
    "a ring is due to problems in the etching step"      -> ARISES_IN: Edge-Ring -> ETCH
    "a linear scratch is a result of machine handling"   -> no process is named, so no ARISES_IN
- Every FailureMode must have exactly one OCCURS_IN relationship.
- Do not extract equipment instances (ETCH-03, ...). Those belong to the fab data domain.
- Fill extraction_confidence (1-5) and the supporting quotes for every relationship.

Source text:
{chunk['text']}
"""


# =========================
# 4. 추출 + 검증
# =========================

def extract_kg_from_chunk(structured_llm, chunk: dict) -> RcaGraph:
    return structured_llm.invoke(build_prompt(chunk))


def normalize_id(raw: str) -> str:
    """LLM이 흘린 표기 흔들림 흡수: 소문자 + 공백/하이픈 → 밑줄."""
    return re.sub(r"[^a-z0-9_]+", "_", raw.strip().lower()).strip("_")


def validate_kg(
    kg: RcaGraph,
    dropped: Optional[list[str]] = None,
    chunk_text: str = "",
    unverifiable: Optional[dict[str, set[str]]] = None,
) -> RcaGraph:
    """
    [Graph Pruning]
    - FailureMode/Cause id를 정규화한 뒤 관계의 source/target을 같은 규칙으로 맞춘다.
    - 앵커(DefectPattern/ProcessStep) 표기는 시드 aliases로 canonical id에 갈아끼운다.
      LLM이 'edge-ring', 'etching' 처럼 흔들어도 살린다. 못 붙이면 사유를 남기고 버린다.
    - Parameter는 Cause가 속한 ProcessStep 안에서 해석한다('temperature'가 공정마다 다르므로).
      그래서 두 패스로 나눈다: 먼저 Cause→공정을 알아낸 뒤에 VERIFIED_BY를 본다.
    - 이번 청크에서 추출되지 않은 FailureMode/Cause를 가리키는 관계는 버린다.
      (없는 노드를 가리키면 Cypher MATCH가 실패해 조용히 유실되므로 미리 자른다)
    - extraction_confidence 2 미만은 폐기.

    dropped 리스트를 넘기면 버린 관계의 사유가 쌓인다(조용한 유실 방지).
    """
    log = dropped if dropped is not None else []

    for node in [*kg.failure_modes, *kg.causes, *kg.maintenance, *kg.recipes]:
        node.id = normalize_id(node.id)

    fm_ids = {fm.id for fm in kg.failure_modes}
    cause_ids = {c.id for c in kg.causes}
    evidence_ids = {
        "Maintenance": {m.id for m in kg.maintenance},
        "Recipe": {r.id for r in kg.recipes},
    }
    # 시그니처 id는 enum 조합이라 정규화 불필요. 단, 형상이 원문에 실제로 서술됐는지 검사한다.
    sig_ids: set[str] = set()
    for sig in kg.signatures:
        surfaces = SHAPE_SURFACES.get(sig.shape, [])
        if chunk_text and not any(
            re.search(rf"\b{re.escape(w)}\b", _normalize_key(chunk_text)) for w in surfaces
        ):
            log.append(f"Signature {sig.id!r}: 청크 원문에 형상 서술 없음 (환각)")
            continue
        sig_ids.add(sig.id)

    valid: list[Relationship] = []
    deferred: list[Relationship] = []

    # --- 패스 1: 앵커 관계. Cause가 어느 공정에 속하는지도 여기서 알아낸다. ---
    for rel in kg.relationships:
        raw = f"{rel.kind} {rel.source!r} -> {rel.target!r}"

        if rel.extraction_confidence < 2:
            log.append(f"{raw}: 신뢰도 {rel.extraction_confidence} < 2")
            continue

        src, tgt = rel.source.strip(), rel.target.strip()

        if rel.kind == "ARISES_IN":
            src = resolve_anchor(src, DEFECT_PATTERN_INDEX)
            tgt = resolve_anchor(tgt, PROCESS_STEP_INDEX)
            if src is None or tgt is None:
                log.append(f"{raw}: 앵커 매핑 실패 (DefectPattern/ProcessStep)")
                continue
            if chunk_text and not step_is_grounded_in(tgt, chunk_text):
                log.append(f"{raw}: 청크 원문에 공정 '{tgt}' 언급 없음 (환각)")
                continue
        elif rel.kind == "HAS_SIGNATURE":
            src = resolve_anchor(src, DEFECT_PATTERN_INDEX)
            tgt = tgt.lower()
            if src is None:
                log.append(f"{raw}: DefectPattern 매핑 실패 (고정 3종에 없음)")
                continue
            if tgt not in sig_ids:
                log.append(f"{raw}: Signature가 이 청크에서 추출되지 않음")
                continue
        elif rel.kind == "FORMS_IN":
            src = src.lower()
            tgt = resolve_anchor(tgt, PROCESS_STEP_INDEX)
            if src not in sig_ids or tgt is None:
                log.append(f"{raw}: Signature 미추출 또는 ProcessStep 매핑 실패")
                continue
            if chunk_text and not step_is_grounded_in(tgt, chunk_text):
                log.append(f"{raw}: 청크 원문에 공정 '{tgt}' 언급 없음 (환각)")
                continue
        elif rel.kind == "ATTRIBUTED_TO":
            src = resolve_anchor(src, DEFECT_PATTERN_INDEX)
            tgt = normalize_id(tgt)
            if src is None:
                log.append(f"{raw}: DefectPattern 매핑 실패 (고정 3종에 없음)")
                continue
            if tgt not in cause_ids:
                log.append(f"{raw}: Cause가 이 청크에서 추출되지 않음")
                continue
        elif rel.kind == "OCCURS_IN":
            src = normalize_id(src)
            tgt = resolve_anchor(tgt, PROCESS_STEP_INDEX)
            if src not in fm_ids or tgt is None:
                log.append(f"{raw}: FailureMode 미추출 또는 ProcessStep 매핑 실패")
                continue
            # ARISES_IN과 같은 이유로 근거를 요구한다. 공정 이름이 없는 청크에서
            # LLM이 아무 공정이나 골라 붙인다(표 청크는 '공정:' 줄이 있어 항상 통과).
            if chunk_text and not step_is_grounded_in(tgt, chunk_text):
                log.append(f"{raw}: 청크 원문에 공정 '{tgt}' 언급 없음 (환각)")
                continue
        elif rel.kind == "CAUSED_BY":
            src, tgt = normalize_id(src), normalize_id(tgt)
            if src not in fm_ids or tgt not in cause_ids:
                log.append(f"{raw}: FailureMode/Cause가 이 청크에서 추출되지 않음")
                continue
        elif rel.kind == "VERIFIED_BY":
            deferred.append(rel)   # 패스 2에서 처리
            continue
        else:
            log.append(f"{raw}: 알 수 없는 kind")
            continue

        rel.source, rel.target = src, tgt
        valid.append(rel)

    # FailureMode -> 공정, 그리고 Cause -> 공정 (CAUSED_BY를 타고 물려받는다)
    fm_step = {r.source: r.target for r in valid if r.kind == "OCCURS_IN"}
    cause_steps: dict[str, set[str]] = {}
    for r in valid:
        if r.kind == "CAUSED_BY" and r.source in fm_step:
            cause_steps.setdefault(r.target, set()).add(fm_step[r.source])

    # --- 패스 2: VERIFIED_BY. Parameter는 Cause의 공정 안에서 해석한다. ---
    for rel in deferred:
        raw = f"{rel.kind} {rel.source!r} -> {rel.target!r}"

        src = normalize_id(rel.source.strip())
        tgt = rel.target.strip()

        if src not in cause_ids:
            log.append(f"{raw}: Cause가 이 청크에서 추출되지 않음")
            continue
        if rel.target_label is None:
            log.append(f"{raw}: VERIFIED_BY에 target_label이 없음")
            continue

        if rel.target_label == "Parameter":
            # 고정 vocabulary. Cause가 속한 공정 안에서만 별칭을 푼다.
            tgt, reason = resolve_parameter(tgt, cause_steps.get(src, set()))
            if tgt is None:
                log.append(f"{raw}: {reason}")
                # 문헌이 지목한 신호 자체는 지식이다 — fab이 계측하지 않을 뿐(C2 성격).
                # 버리되 신호명은 Cause에 보존해 출력까지 흘려보낸다 (정합성검토 X1-c).
                if unverifiable is not None:
                    signal = normalize_id(rel.target.strip()) or rel.target.strip()
                    unverifiable.setdefault(src, set()).add(signal)
                continue
        else:
            # Maintenance / Recipe 는 문서에서 자유 추출. 같은 청크에 노드가 있어야 한다.
            tgt = normalize_id(tgt)
            if tgt not in evidence_ids[rel.target_label]:
                log.append(f"{raw}: {rel.target_label} 노드가 이 청크에서 추출되지 않음")
                continue
            # direction은 Parameter 전용이다. 나머지에 붙어 오면 버린다.
            rel.direction = None

        rel.source, rel.target = src, tgt
        valid.append(rel)

    # 어디에서도 가리켜지지 않는 Cause는 그래프에서 도달할 수 없다(고아).
    # FailureMode를 거치거나(CAUSED_BY), DefectPattern이 직접 지목하면(ATTRIBUTED_TO) 살아남는다.
    # 그 Cause를 버리면 거기서 출발하던 VERIFIED_BY도 같이 버려야 한다.
    linked_causes = {
        r.target for r in valid if r.kind in ("CAUSED_BY", "ATTRIBUTED_TO")
    }
    for c in kg.causes:
        if c.id not in linked_causes:
            log.append(f"Cause {c.id!r}: FailureMode/DefectPattern 어느 쪽도 가리키지 않는 고아")
    causes = [c for c in kg.causes if c.id in linked_causes]
    valid = [
        r for r in valid
        if r.kind != "VERIFIED_BY" or r.source in linked_causes
    ]

    # 살아남은 VERIFIED_BY가 가리키지 않는 evidence 노드도 고아라 저장하지 않는다.
    used = {
        (r.target_label, r.target) for r in valid if r.kind == "VERIFIED_BY"
    }
    maintenance = [m for m in kg.maintenance if ("Maintenance", m.id) in used]
    recipes = [r for r in kg.recipes if ("Recipe", r.id) in used]

    # 어떤 관계에도 걸리지 않은 Signature도 고아라 버린다.
    linked_sigs = {r.target for r in valid if r.kind == "HAS_SIGNATURE"} \
                | {r.source for r in valid if r.kind == "FORMS_IN"}
    signatures = [s for s in kg.signatures if s.id in linked_sigs and s.id in sig_ids]
    # 같은 (shape,zone)이 중복 추출됐으면 하나만
    seen: set[str] = set()
    signatures = [s for s in signatures if not (s.id in seen or seen.add(s.id))]

    return RcaGraph(
        failure_modes=kg.failure_modes,
        causes=causes,
        maintenance=maintenance,
        recipes=recipes,
        signatures=signatures,
        relationships=valid,
    )


# =========================
# 5. Neo4j 저장
# =========================

def get_graph() -> Neo4jGraph:
    return Neo4jGraph(
        url=NEO4J_URI,
        username=NEO4J_USERNAME,
        password=NEO4J_PASSWORD,
        database=NEO4J_DATABASE,
    )


# 관계 속성에 이 청크를 근거로 덧붙이는 조각 (중복 없이 append)
_CHUNK_IDS_SET = """
            rel.chunk_ids = CASE
                WHEN rel.chunk_ids IS NULL THEN [$chunk_id]
                WHEN NOT $chunk_id IN rel.chunk_ids THEN rel.chunk_ids + [$chunk_id]
                ELSE rel.chunk_ids END
"""


def save_unverifiable_signals(graph: Neo4jGraph, signals: dict[str, set[str]]) -> None:
    """
    문헌이 지목했지만 fab 어휘로 붙지 못한 검증 신호를 Cause 노드에 보존한다.
    (예: film_stress, resist_thickness) — VERIFIED_BY 엣지는 만들지 않는다.
    join key 원칙은 지키되 "지식은 있는데 계측이 없다"는 사실을 잃지 않기 위함.
    """
    if not signals:
        return
    items = [{"cause": c, "signals": sorted(s)} for c, s in signals.items()]
    graph.query(
        """
        UNWIND $items AS it
        MATCH (c:Cause {id: it.cause})
        SET c.unverifiable_signals = coalesce(c.unverifiable_signals, [])
            + [s IN it.signals WHERE NOT s IN coalesce(c.unverifiable_signals, [])]
        """,
        params={"items": items},
    )


def save_kg_to_neo4j(graph: Neo4jGraph, kg: RcaGraph, chunk: dict) -> None:
    failure_modes = [n.model_dump() for n in kg.failure_modes]
    causes = [n.model_dump() for n in kg.causes]
    maintenance = [n.model_dump() for n in kg.maintenance]
    recipes = [n.model_dump() for n in kg.recipes]
    signatures = [{**s.model_dump(), "id": s.id} for s in kg.signatures]
    rels = [r.model_dump() for r in kg.relationships]

    chunk_id = chunk["chunk_id"]

    # (0) SpatialSignature 노드 — 시딩하지 않으므로 여기서 생성된다.
    #     id가 enum 조합이라 문서가 달라도 같은 (shape,zone)은 같은 노드로 MERGE된다.
    if signatures:
        graph.query(
            """
            MATCH (c:Chunk {id: $chunk_id})
            UNWIND $nodes AS n
            MERGE (g:SpatialSignature {id: n.id})
            SET g.shape = n.shape,
                g.zone = n.zone,
                g.name = n.id
            MERGE (c)-[:MENTIONS]->(g)
            """,
            params={"chunk_id": chunk_id, "nodes": signatures},
        )

    # (1) FailureMode 노드 + 이 청크가 언급했음을 기록
    if failure_modes:
        graph.query(
            """
            MATCH (c:Chunk {id: $chunk_id})
            UNWIND $nodes AS n
            MERGE (fm:FailureMode {id: n.id})
            SET fm.name = n.name,
                fm.description = n.description,
                fm.aliases = n.aliases
            MERGE (c)-[:MENTIONS]->(fm)
            """,
            params={"chunk_id": chunk_id, "nodes": failure_modes},
        )

    # (2) Cause 노드
    if causes:
        graph.query(
            """
            MATCH (c:Chunk {id: $chunk_id})
            UNWIND $nodes AS n
            MERGE (cause:Cause {id: n.id})
            SET cause.name = n.name,
                cause.description = n.description,
                cause.aliases = n.aliases
            MERGE (c)-[:MENTIONS]->(cause)
            """,
            params={"chunk_id": chunk_id, "nodes": causes},
        )

    # (3) Maintenance / Recipe evidence 노드
    #     :Evidence 슈퍼라벨을 함께 붙여, "이 Cause의 모든 검증 신호"를 한 번에 조회 가능하게 한다.
    if maintenance:
        graph.query(
            """
            MATCH (c:Chunk {id: $chunk_id})
            UNWIND $nodes AS n
            MERGE (m:Maintenance {id: n.id})
            SET m:Evidence,
                m.name = n.name,
                m.description = n.description,
                m.consumable = n.consumable,
                m.fab_table = $fab_table
            MERGE (c)-[:MENTIONS]->(m)
            """,
            params={
                "chunk_id": chunk_id,
                "nodes": maintenance,
                "fab_table": FAB_TABLE["Maintenance"],
            },
        )

    if recipes:
        graph.query(
            """
            MATCH (c:Chunk {id: $chunk_id})
            UNWIND $nodes AS n
            MERGE (rc:Recipe {id: n.id})
            SET rc:Evidence,
                rc.name = n.name,
                rc.description = n.description,
                rc.fab_table = $fab_table
            MERGE (c)-[:MENTIONS]->(rc)
            """,
            params={
                "chunk_id": chunk_id,
                "nodes": recipes,
                "fab_table": FAB_TABLE["Recipe"],
            },
        )

    if not rels:
        return

    # (4) ARISES_IN : DefectPattern -> ProcessStep  (문서 A)
    graph.query(
        f"""
        UNWIND $rels AS r
        WITH r WHERE r.kind = 'ARISES_IN'
        MATCH (p:DefectPattern {{id: r.source}})
        MATCH (s:ProcessStep {{id: r.target}})
        MERGE (p)-[rel:ARISES_IN]->(s)
        SET rel.occurrence_prior = r.occurrence_prior,
            rel.extraction_confidence = r.extraction_confidence,
            rel.description = r.description,
            rel.quotes = r.quotes,
        {_CHUNK_IDS_SET}
        """,
        params={"rels": rels, "chunk_id": chunk_id},
    )

    # (4a-1) HAS_SIGNATURE : DefectPattern -> SpatialSignature  (문서의 형상 서술에서 추출)
    graph.query(
        f"""
        UNWIND $rels AS r
        WITH r WHERE r.kind = 'HAS_SIGNATURE'
        MATCH (p:DefectPattern {{id: r.source}})
        MATCH (g:SpatialSignature {{id: r.target}})
        MERGE (p)-[rel:HAS_SIGNATURE]->(g)
        SET rel.extraction_confidence = r.extraction_confidence,
            rel.description = r.description,
            rel.quotes = r.quotes,
        {_CHUNK_IDS_SET}
        """,
        params={"rels": rels, "chunk_id": chunk_id},
    )

    # (4a) FORMS_IN : SpatialSignature -> ProcessStep  (문서 D, 형상 수준 서술)
    graph.query(
        f"""
        UNWIND $rels AS r
        WITH r WHERE r.kind = 'FORMS_IN'
        MATCH (g:SpatialSignature {{id: r.source}})
        MATCH (s:ProcessStep {{id: r.target}})
        MERGE (g)-[rel:FORMS_IN]->(s)
        SET rel.occurrence_prior = r.occurrence_prior,
            rel.density = r.density,
            rel.continuity = r.continuity,
            rel.angular_coverage = r.angular_coverage,
            rel.clock_positions = r.clock_positions,
            rel.extraction_confidence = r.extraction_confidence,
            rel.description = r.description,
            rel.quotes = r.quotes,
        {_CHUNK_IDS_SET}
        """,
        params={"rels": rels, "chunk_id": chunk_id},
    )

    # (4b) ATTRIBUTED_TO : DefectPattern -> Cause  (문서 C, 공정을 거치지 않는 직결)
    graph.query(
        f"""
        UNWIND $rels AS r
        WITH r WHERE r.kind = 'ATTRIBUTED_TO'
        MATCH (p:DefectPattern {{id: r.source}})
        MATCH (c:Cause {{id: r.target}})
        MERGE (p)-[rel:ATTRIBUTED_TO]->(c)
        SET rel.extraction_confidence = r.extraction_confidence,
            rel.description = r.description,
            rel.quotes = r.quotes,
        {_CHUNK_IDS_SET}
        """,
        params={"rels": rels, "chunk_id": chunk_id},
    )

    # (5) OCCURS_IN : FailureMode -> ProcessStep  (앵커)
    graph.query(
        f"""
        UNWIND $rels AS r
        WITH r WHERE r.kind = 'OCCURS_IN'
        MATCH (fm:FailureMode {{id: r.source}})
        MATCH (s:ProcessStep {{id: r.target}})
        MERGE (fm)-[rel:OCCURS_IN]->(s)
        SET rel.extraction_confidence = r.extraction_confidence,
            rel.description = r.description,
            rel.quotes = r.quotes,
        {_CHUNK_IDS_SET}
        """,
        params={"rels": rels, "chunk_id": chunk_id},
    )

    # (6) CAUSED_BY : FailureMode -> Cause
    graph.query(
        f"""
        UNWIND $rels AS r
        WITH r WHERE r.kind = 'CAUSED_BY'
        MATCH (fm:FailureMode {{id: r.source}})
        MATCH (c:Cause {{id: r.target}})
        MERGE (fm)-[rel:CAUSED_BY]->(c)
        SET rel.extraction_confidence = r.extraction_confidence,
            rel.description = r.description,
            rel.quotes = r.quotes,
        {_CHUNK_IDS_SET}
        """,
        params={"rels": rels, "chunk_id": chunk_id},
    )

    # (7) VERIFIED_BY : Cause -> Parameter | Maintenance | Recipe  (검증 종착점)
    #     Cypher는 라벨을 파라미터로 못 받는다. target_label 별로 쿼리를 나눈다.
    for label in FAB_TABLE:
        graph.query(
            f"""
            UNWIND $rels AS r
            WITH r WHERE r.kind = 'VERIFIED_BY' AND r.target_label = $label
            MATCH (c:Cause {{id: r.source}})
            MATCH (e:{label} {{id: r.target}})
            MERGE (c)-[rel:VERIFIED_BY]->(e)
            SET rel.target_label = r.target_label,
                rel.direction = r.direction,
                rel.extraction_confidence = r.extraction_confidence,
                rel.description = r.description,
                rel.quotes = r.quotes,
            {_CHUNK_IDS_SET}
            """,
            params={"rels": rels, "chunk_id": chunk_id, "label": label},
        )


# =========================
# 6. 추출 결과 JSONL 저장
# =========================

def append_result_to_jsonl(output_path: Path, chunk: dict, kg: RcaGraph) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "chunk_id": chunk["chunk_id"],
        "doc_id": chunk.get("doc_id"),
        "kg": kg.model_dump(),
    }
    with output_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# =========================
# 7. chunks.jsonl 로드
# =========================

def load_chunks(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"chunks.jsonl 파일을 찾을 수 없습니다: {path}")
    chunks = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            metadata = row.get("metadata", {})
            chunks.append({
                "chunk_id": row["chunk_id"],
                "chunk_index": row["chunk_index"],
                "text": row["page_content"],
                "doc_id": metadata.get("doc_id"),
            })
    return chunks


# =========================
# 8. 실행
# =========================

def main() -> None:
    assert_enums_match_seeds()

    chunks = load_chunks(CHUNKS_PATH)
    print("처리할 청크 수:", len(chunks))

    graph = get_graph()

    llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0)
    structured_llm = llm.with_structured_output(RcaGraph, method="json_schema")

    # 재실행 시 결과 파일 초기화
    if OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()

    totals = {
        "failure_modes": 0, "causes": 0,
        "maintenance": 0, "recipes": 0, "signatures": 0, "relationships": 0,
    }
    total_dropped = 0

    for i, chunk in enumerate(chunks, start=1):
        print("=" * 80)
        print(f"[{i}/{len(chunks)}] {chunk['chunk_id']}")
        print(chunk["text"][:160].replace("\n", " "))

        kg = extract_kg_from_chunk(structured_llm, chunk)

        dropped: list[str] = []
        unverifiable: dict[str, set[str]] = {}
        kg = validate_kg(kg, dropped, chunk_text=chunk["text"], unverifiable=unverifiable)

        print(
            "FailureMode:", len(kg.failure_modes),
            "| Cause:", len(kg.causes),
            "| Maintenance:", len(kg.maintenance),
            "| Recipe:", len(kg.recipes),
            "| Signature:", len(kg.signatures),
            "| 관계:", len(kg.relationships),
        )
        for reason in dropped:
            print("  버림:", reason)
        total_dropped += len(dropped)

        save_kg_to_neo4j(graph, kg, chunk)
        save_unverifiable_signals(graph, unverifiable)
        append_result_to_jsonl(OUTPUT_PATH, chunk, kg)

        totals["failure_modes"] += len(kg.failure_modes)
        totals["causes"] += len(kg.causes)
        totals["maintenance"] += len(kg.maintenance)
        totals["recipes"] += len(kg.recipes)
        totals["signatures"] += len(kg.signatures)
        totals["relationships"] += len(kg.relationships)

    # 앵커 보강: 패턴/형상을 언급하는 청크만 K-1회 재추출해 합집합 (MERGE라 중복 없음)
    # 진입점 엣지는 mini 모델이 자주 놓친다(헤딩 규칙을 예시로 줘도). ANCHOR_MODEL로
    # 보강 패스만 상위 모델을 쓸 수 있다 — 대상이 ~30청크라 비용 부담이 작다.
    anchor_model = os.getenv("ANCHOR_MODEL", OPENAI_MODEL)
    anchor_llm = structured_llm if anchor_model == OPENAI_MODEL else \
        ChatOpenAI(model=anchor_model, temperature=0).with_structured_output(
            RcaGraph, method="json_schema")
    anchor_chunks = [c for c in chunks if mentions_pattern_or_signature(c["text"])]
    for pass_no in range(2, ANCHOR_PASSES + 1):
        print("=" * 80)
        print(f"앵커 보강 패스 {pass_no}/{ANCHOR_PASSES} — 대상 {len(anchor_chunks)}청크 (모델: {anchor_model})")
        for chunk in anchor_chunks:
            kg = extract_kg_from_chunk(anchor_llm, chunk)
            dropped = []
            unverifiable = {}
            kg = validate_kg(kg, dropped, chunk_text=chunk["text"], unverifiable=unverifiable)
            save_kg_to_neo4j(graph, kg, chunk)
            save_unverifiable_signals(graph, unverifiable)
            anchors = [
                f"{r.kind} {r.source}->{r.target}"
                for r in kg.relationships
                if r.kind in ("ARISES_IN", "FORMS_IN", "ATTRIBUTED_TO")
            ]
            if anchors:
                print(f"  {chunk['chunk_id']}: {anchors}")

    graph.refresh_schema()

    print("\n완료")
    for key, value in totals.items():
        print(f"총 추출 {key}: {value}")
    print("총 버린 관계/노드:", total_dropped)
    print("결과 저장:", OUTPUT_PATH)

    print("\nGraph schema:")
    print(graph.schema)


if __name__ == "__main__":
    main()
