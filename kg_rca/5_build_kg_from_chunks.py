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

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")


# =========================
# 2. KG 스키마 정의 (schema_v2.md)
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


class FailureModeNode(BaseModel):
    """공정 내부의 고장 모드. 예: post-etch residue, metal corrosion."""
    id: str = Field(description="유일 키. 소문자 snake_case. 예: post_etch_residue")
    name: str = Field(description="문헌에 쓰인 그대로의 고장 모드 이름. 예: excessive post-etch residue")
    description: str = Field(description="완결된 한국어 한 문장")
    aliases: list[str] = Field(default_factory=list, description="문헌 속 별칭들")


class CauseNode(BaseModel):
    """고장 모드의 근본 원인. 예: high etch rate, nonuniform etch process."""
    id: str = Field(description="유일 키. 소문자 snake_case. 예: high_etch_rate")
    name: str = Field(description="문헌에 쓰인 그대로의 원인 이름. 예: incorrect process parameter (high etch rate)")
    description: str = Field(description="완결된 한국어 한 문장. 나중에 가설 문장의 부품으로 이어 붙인다.")
    aliases: list[str] = Field(default_factory=list, description="문헌 속 별칭들")


class MaintenanceNode(BaseModel):
    """
    정비 행위. 문헌의 '조치(Corrective Action)' 열에서 뽑는다.
    원인 열에는 'Improper maintenance'라는 뭉뚱그린 표현만 있고,
    구체적 정비 행위(chamber wet clean 등)는 조치 열에 적혀 있다.
    """
    id: str = Field(description="유일 키. 소문자 snake_case. 예: chamber_wet_clean")
    name: str = Field(description="문헌 표기 그대로. 예: chamber wet clean")
    description: str = Field(description="완결된 한국어 한 문장")
    consumable: bool = Field(
        description="소모품(패드·브러시·슬러리·필터·컨디셔너 등)의 교체/마모/수명 계열이면 true, "
                    "일반 정비·세정·점검·교정이면 false. "
                    "예: replace polishing pad -> true, chamber wet clean -> false"
    )


class RecipeNode(BaseModel):
    """레시피 검증 대상. 예: process recipe."""
    id: str = Field(description="유일 키. 소문자 snake_case. 예: process_recipe")
    name: str = Field(description="문헌 표기 그대로. 예: process recipe")
    description: str = Field(description="완결된 한국어 한 문장")


class SignatureNode(BaseModel):
    """
    웨이퍼맵 공간 시그니처 = (형상, 구역) 쌍. 문서의 형상 서술에서 추출한다.
    id는 코드가 "{shape}@{zone}"으로 조합하므로 LLM은 두 enum만 고르면 된다.
    """
    shape: ShapeId = Field(description="형상. 예: ring-shaped -> ring, linear streaks -> line")
    zone: ZoneId = Field(description="구역. 예: outer edge -> edge, geometric center -> center, 전체/불특정 -> any")
    description: str = Field(default="", description="문헌의 형상 서술 원문 요약(짧게)")

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
    source: str = Field(description="출발 노드의 id")
    target: str = Field(description="도착 노드의 id")

    target_label: Optional[EvidenceLabel] = Field(
        default=None,
        description="VERIFIED_BY 전용: 도착 노드의 라벨. 나머지 kind에서는 비워둔다.",
    )
    direction: Optional[Literal["high", "low"]] = Field(
        default=None,
        description="VERIFIED_BY + target_label=Parameter 전용: 변수 이상 방향",
    )
    occurrence_prior: Optional[Literal["high", "mid", "low"]] = Field(
        default=None, description="ARISES_IN 전용: 문헌상 흔한 정도(commonly/rare)"
    )
    extraction_confidence: float = Field(description="추출 신뢰도 1~5. 애매하면 낮게.")
    description: str = Field(description="이 관계를 뒷받침하는 완결된 한 문장")
    quotes: list[str] = Field(default_factory=list, description="근거 원문 스니펫(짧게)")


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
다음은 반도체 웨이퍼 불량 원인분석(RCA) 문헌의 한 조각입니다.
이 조각에서 고장 모드(FailureMode), 원인(Cause), 검증 신호(Evidence)와 그 관계를 지식그래프로 추출하세요.

청크 메타데이터:
- chunk_id: {chunk['chunk_id']}
- doc_id: {chunk.get('doc_id')}

추출 규칙:
- 원문에 명시된 내용만 추출하고, 추측하지 마세요.
- 의미 있는 내용이 없으면 모든 리스트를 빈 리스트로 반환하세요.
- 노드 id는 소문자 snake_case. 예: post_etch_residue, high_etch_rate
- description은 완결된 한국어 한 문장으로 쓰세요.
- 공정 변수 자체(rf_power, etch_rate 등)를 Cause로 만들지 마세요.
  변수는 VERIFIED_BY의 target으로만 씁니다.
  "etch rate too high"처럼 이상 방향이 붙은 서술만 Cause입니다.
- FailureMode(증상/고장 모드)와 Cause(그 배후 원인)를 섞지 마세요.
  예: "excessive post-etch residue"는 FailureMode, "nonuniform etch process"는 Cause.
- 조치/처방(“~를 교정하라”, “~를 점검하라”)은 Cause가 아닙니다.
  조치 문장에 등장하는 정비 행위는 Maintenance 노드로만 만드세요.

이 청크가 트러블슈팅 표의 한 행이면 아래 이름표가 붙어 있습니다. 열의 역할이 다릅니다.

  공정: <ProcessStep>        <- 이 행의 OCCURS_IN 대상. 이 공정을 그대로 쓰세요.
  표 유형: troubleshooting
  [고장모드]  -> FailureMode 하나
  [원인]      -> Cause 후보. "A." "B." 처럼 항목이 나뉘어 있으면 **항목마다 Cause 하나**
  [조치]      -> 조치 문장. **절대 Cause로 만들지 마세요.**
                 여기 나오는 구체적 정비 행위(chamber wet clean, replace thermocouple 등)만
                 Maintenance 노드로 만들고, 대응하는 Cause에서 VERIFIED_BY로 연결하세요.

  표 유형: quality
  [품질항목]  -> 측정 항목. 노드로 만들지 마세요.
  [결함유형]  -> FailureMode
  [비고]      -> 원인이 서술돼 있으면 Cause. 조치성 문장("~를 확인하라")은 제외.

  표 유형: pattern_cause     (웨이퍼맵 패턴 -> 원인 직결. 공정 줄이 없습니다)
  [불량패턴]  -> DefectPattern. 고정 3종에 없으면 이 행은 전부 건너뛰세요.
  [패턴설명]  -> 노드로 만들지 마세요.
  [원인]      -> Cause. 쉼표/or 로 나뉜 원인이 여럿이면 **각각 별도 Cause**로 만들고,
                 DefectPattern에서 ATTRIBUTED_TO로 잇습니다. FailureMode는 만들지 마세요.
                 원인 문장이 공정을 명시하면(예: "during chemical-mechanical polishing (CMP)")
                 ARISES_IN도 함께 만드세요.

원인 열의 뭉뚱그린 표현은 이렇게 처리하세요.
  "Improper maintenance"      -> Cause로 만들고, VERIFIED_BY -> Maintenance (조치 열의 구체 행위)
  "Incorrect process recipe"  -> Cause로 만들고, VERIFIED_BY -> Recipe ("process recipe")

아래 세 목록은 고정입니다. 새로 만들지 말고 목록 안에서만 고르세요.
해당하는 항목이 목록에 없으면 그 관계는 추출하지 마세요.

공정 단계(ProcessStep) 6종:
  LITHO, ETCH, DEPO, CMP, CLEAN, EDS

불량 패턴(DefectPattern) 3종:
  Center, Scratch, Edge-Ring
  (웨이퍼맵 상의 공간 패턴만 해당. "circular ring"→Edge-Ring, "bulls eye"→Center,
   "linear defect"/"scuff mark"→Scratch)

공간 시그니처(SpatialSignature) — 문헌의 형상 서술에서 추출하는 노드:
  signatures 리스트에 shape와 zone을 enum으로 골라 넣으세요.
    shape 6종: ring, cluster, line, blob, global, random
    zone 4종: center, mid, edge, any (불특정이면 any)
  관계에서 이 노드를 가리킬 때는 "{{shape}}@{{zone}}" 형식의 id를 쓰세요.
    "ring-shaped pattern at the outer edge" -> shape=ring, zone=edge -> id "ring@edge"
    "concentrated cluster near the geometric center" -> cluster@center
    "linear streaks across the wafer" / "directional scratches" -> line@any
  문헌이 형상을 서술할 때만 만드세요. 형상 언급이 없는 청크에서는 만들지 마세요.

공정 변수(Parameter) 20종:
  exposure_dose, focus_offset, stage_temp, alignment_offset,
  rf_power, chamber_pressure, he_flow, temperature, etch_rate,
  gas_flow, susceptor_temp, deposition_rate,
  down_force, slurry_flow,
  flow_rate, megasonic_power, chemical_temp, rinse_time,
  chuck_temp, contact_resistance

검증 신호(Evidence)는 세 종류이고, Parameter만 위 고정 목록에서 고릅니다.
Maintenance와 Recipe는 문헌 표현으로 자유롭게 만드세요.
- Parameter   : 계측 변수. 위 20종 중 하나. (예: rf_power)
                **어느 변수인지 확실하지 않으면 문헌의 일반 표현을 그대로 쓰세요**
                (temperature, pressure, gas flow, focus, overlay ...).
                공정에 맞는 변수로 자동 매핑됩니다. 예: ETCH의 "Incorrect temperature"는
                'temperature'라고 쓰세요. 'chuck_temp'처럼 다른 공정의 변수를 고르면 버려집니다.
- Maintenance : 정비 행위. 조치 문장에서 뽑는다. (예: chamber wet clean, replace defective thermocouple)
                consumable 필드를 채우세요: 소모품(패드/브러시/슬러리/필터/컨디셔너)의
                교체·마모·수명 계열이면 true, 일반 정비·세정·점검·교정이면 false.
- Recipe      : 레시피 확인 대상. (예: process recipe)

관계(kind) 7종:
- ARISES_IN:     (DefectPattern) -> (ProcessStep)  "이 불량 패턴은 이 공정을 의심케 한다" (occurrence_prior 채우기)
- HAS_SIGNATURE: (DefectPattern) -> (SpatialSignature)  "이 패턴은 이런 형상으로 나타난다"
                 문헌이 패턴의 생김새를 서술할 때 씁니다. target은 "{{shape}}@{{zone}}" id.
                 예: "The Edge-Ring defect appears as a ring-shaped pattern near the outer edge"
                     -> signatures에 (ring, edge) 추가 + HAS_SIGNATURE: Edge-Ring -> ring@edge
- FORMS_IN:      (SpatialSignature) -> (ProcessStep)  "이 형상은 주로 이 공정에서 생긴다" (occurrence_prior 채우기)
                 문헌이 패턴 클래스명 없이 **형상 서술**로 공정을 지목할 때 씁니다.
                 예: "This ring-shaped failure pattern at the outer edge reflects issues in cleaning steps"
                     -> FORMS_IN: ring@edge -> CLEAN
                 같은 문장이 패턴 클래스명(Center/Scratch/Edge-Ring)도 함께 말하면
                 ARISES_IN을 우선하고 FORMS_IN은 만들지 마세요(중복 방지).
- ATTRIBUTED_TO: (DefectPattern) -> (Cause)        "이 불량 패턴의 원인은 저것이다"
                 문헌이 **공정을 말하지 않고** 패턴에서 원인으로 바로 건너뛸 때 씁니다.
- OCCURS_IN:   (FailureMode)   -> (ProcessStep)  "이 고장 모드는 이 공정에서 일어난다" (고장 모드마다 정확히 1개)
- CAUSED_BY:   (FailureMode)   -> (Cause)        "이 고장 모드의 원인은 저것이다"
- VERIFIED_BY: (Cause)         -> (Parameter | Maintenance | Recipe)
               "이 원인은 이 신호로 검증한다"
               target_label에 'Parameter' / 'Maintenance' / 'Recipe' 중 하나를 반드시 적으세요.
               target_label이 'Parameter'일 때만 direction(high/low)을 채우세요.

VERIFIED_BY 대상 고르는 법:
- 원인이 계측 변수의 이상이면      -> Parameter  (예: "RF power drift" -> rf_power)
  양의 과부족을 말하는 원인도 여기 해당합니다. direction으로 방향을 적으세요.
    "insufficient rinsing"        -> Parameter rinse_time (direction=low)
    "excessive down force"        -> Parameter down_force (direction=high)
    "localized over-pressure"     -> Parameter down_force (direction=high, CMP 문맥)
- 원인이 정비 부족/부품 열화면      -> Maintenance (예: "improper maintenance" -> chamber wet clean)
- 원인이 잘못된 레시피면            -> Recipe     (예: "incorrect process recipe" -> process recipe)

중요:
- source/target에는 반드시 노드의 id를 쓰세요.
  고정 목록의 값은 **위에 적힌 문자열 그대로** 대소문자까지 정확히 옮기세요.
  예: 'Edge-Ring' (O) / 'edge-ring' (X), 'ETCH' (O) / 'etching' (X)
- ARISES_IN은 **원문에 공정 이름이 실제로 등장할 때만** 만드세요.
  공정이 언급되지 않은 서론·요약 문단에서는 ARISES_IN을 추측해 만들지 마세요.
- 청크 머리의 "## Center pattern", "## Scratch pattern — Cleaning" 같은 헤딩은
  **그 단락 전체가 해당 DefectPattern에 대한 서술**임을 뜻합니다.
  헤딩에 패턴명이 있고 본문이 공정을 지목하면, 고장 모드 추출과 **별개로**
  그 패턴의 ARISES_IN도 반드시 만드세요.
  예: "## Scratch pattern — Cleaning" + 본문에 cleaning 서술
      -> ARISES_IN: Scratch -> CLEAN (+ 본문의 FailureMode/Cause 추출은 평소대로)
- **"retaining ring"은 CMP 캐리어 부품이지 결함 패턴이 아닙니다.**
  retaining ring 언급만으로 Edge-Ring 패턴이나 ring 형상을 만들지 마세요.
  패턴/형상은 웨이퍼맵 상의 불량 분포를 서술할 때만 해당합니다.
- 문서 머리의 [Metadata] 블록에 "Related Defect: Edge Ring"처럼 관련 결함이 명시돼 있고
  Process가 지목돼 있으면, 그것은 큐레이션된 패턴-공정 연결이므로 ARISES_IN으로 추출하세요.
- 불량 패턴(Center/Scratch/Edge-Ring)은 DefectPattern이지 FailureMode가 아닙니다.
  'scratch_pattern' 같은 FailureMode를 만들지 마세요. 패턴은 ARISES_IN의 source로만 씁니다.
  FailureMode는 공정 내부의 고장(post-etch residue, overlay misregistration 등)입니다.
- 청크가 "웨이퍼맵 상의 어떤 모양이 어느 공정 탓인가"를 서술하면, 그것은 ARISES_IN입니다.
  그 모양을 FailureMode로 만들지 말고 DefectPattern으로 매핑해 ARISES_IN을 만드세요.
    "a center often arises due to problems in the thin film deposition"
        -> ARISES_IN: Center -> DEPO          (O)
        -> FailureMode 'thin_film_deposition_problem'   (X)
    "a ring is due to problems in the etching step"      -> ARISES_IN: Edge-Ring -> ETCH
    "a linear scratch is a result of machine handling"   -> 공정이 명시되지 않았으므로 ARISES_IN 없음
- 모든 FailureMode에는 OCCURS_IN 관계가 정확히 하나 있어야 합니다.
- 장비 인스턴스(ETCH-03 등)는 추출하지 마세요. fab 데이터 영역입니다.
- 각 관계에 extraction_confidence(1~5)와 근거 quotes를 채우세요.

원문:
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
