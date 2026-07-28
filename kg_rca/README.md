# Wafer Defect RCA — GraphRAG

반도체 웨이퍼 결함의 **근본원인 분석(RCA)** 을 위한 지식그래프 파이프라인.

공정 문헌에서 "어떤 불량 패턴이 어느 공정을 의심케 하는가",
"그 공정에서 어떤 고장 모드가 어떤 원인으로 생기는가", "그 원인은 어떤 fab 신호로 검증하는가"를
LLM으로 추출해 Neo4j 그래프로 만들고, 관측된 패턴에 대한 **원인 가설 목록**을 생성한다.

그래프는 가설 **생성**까지만 책임진다. 채택/기각은 fab 데이터(SQL)의 몫이며,
그래프는 `Evidence` 노드(`Parameter`/`Maintenance`/`Recipe`)로 그 SQL과 이어진다.

```text
data/raw/ + data/docs/ 문헌 (표·산문·전문가 암묵지 목업)
  -> 로드 (raw + docs 두 폴더)  (2_load_txt.py)
  -> 표 행 단위 청킹    (3_split.py)
  -> 시드 앵커 + Chunk 적재 (4_ingest_chunks_to_neo4j.py)
  -> LLM 추출 + 검증 규칙 (5_build_kg_from_chunks.py)
  -> 결정적 순회 + 가설 출력 (6_ask_graphrag.py)  -> stdout + outputs/hypotheses.json
```

## 그래프 구조

```text
                ┌──ATTRIBUTED_TO───────────────────────────┐   (문헌이 공정을 안 밝힐 때)
                │                                           ▼
DefectPattern ──ARISES_IN──> ProcessStep <──OCCURS_IN── FailureMode
 (Edge-Ring)                   (ETCH)        (join)   (incorrect_etch_rate)
     │ HAS_SIGNATURE (문서 추출)  ▲                          │ CAUSED_BY
     ▼                          │                          ▼
SpatialSignature ──FORMS_IN─────┘                        Cause
 (ring@edge)   (문헌이 형상으로 말할 때)                     │ VERIFIED_BY
                                     ┌──────────────────────┼──────────────────────┐
                                     ▼                      ▼                      ▼
                                Parameter              Maintenance              Recipe
                             → telemetry.param       → maintenance         → lot_history.recipe_id
                                 [자동]                  [반자동]               [반자동]
```

- **질의 진입점:** `DefectPattern` (고정 3종: `Center` / `Scratch` / `Edge-Ring`)
- **join 노드:** `ProcessStep` — 패턴 문서와 troubleshooting 문서가 만나는 지점
- **검증 종착점:** `:Evidence` (Parameter / Maintenance / Recipe, `fab_table` 프로퍼티로 조회 대상 명시)

가설 1건 = 경로 1개. 세 갈래가 있다:
`DefectPattern → ProcessStep → FailureMode → Cause → Evidence` (공정 경유),
`DefectPattern → SpatialSignature → ProcessStep → ...` (형상 경유 — 문헌이 패턴명 없이
"ring-shaped pattern at the edge"처럼 형상으로 말할 때. 미지 패턴도 VLM이 형상만 넘기면 순회 가능),
`DefectPattern → Cause` (문헌 직결, `ATTRIBUTED_TO`).

**[v3.0] 형상 진입점 + 모폴로지 (설계 B):** `SpatialSignature`(`shape@zone`)가 `DefectPattern`과
함께 **두 번째 하드 진입점**이다(미지 패턴=`Unknown` 대응). 관측의 모폴로지
(`density`/`continuity`/`angular_coverage`/`clock_positions`)는 노드가 아니라 **`FORMS_IN` 엣지
속성**으로 들어온다(노드 정체성=`shape@zone` 유지 → clobber·폭증 회피). 조회 시 `angular_coverage`를
**판별자(강)**, 나머지를 소프트 신호로 후보를 재랭킹한다(감점 전용, `backend/graph_client/morphology_rank.py`).
형상·모폴로지 문헌 공급은 목업 `data/docs/doc_H`. 상세는 [`데이터 모델 설계_v3.0.md`](데이터%20모델%20설계_v3.0.md) §0/§2/§3.

**검증 등급** — "fab.db에 있느냐"가 아니라 **"agent가 스스로 판정할 수 있느냐"**로 가른다:

| 등급 | Evidence | 근거 |
|---|---|---|
| `[자동]` | `Parameter` | `telemetry.param`과 결정적 조인 + 정상범위 판정 → agent가 결론까지 |
| `[반자동]` | `Maintenance` / `Recipe` | fab 조회는 되지만 조인 키·기대값이 없어 판정은 사람 몫 |
| `[근거없음]` | 없음 | 문헌 서술로만 존재 (예: RTP 원인 — fab 6스텝 밖) |

전체 명세는 [`KG_schema_v1.3.md`](../docs/KG_schema_v1.3.md) (정본), fab.db 테이블 스키마는
[`secsgem-mcp/README.md` §3](../secsgem-mcp/README.md) (정본 — 7테이블 전체).
[`backup/schema.md`](backup/schema.md)는 v1 기록용.

**장비군별 파라미터 (Quick Reference).** 파라미터 집합이 갈리는 단위는 개별 장비가 아니라
**장비군(공정 스텝)** 이다 — ETCH-01/02/03은 파라미터가 같고, ETCH와 DEPO는 다르다.
정본은 [`data/seeds/parameters.json`](data/seeds/parameters.json)(고유 21종, 각 항목의 `steps` 필드),
아래는 그걸 장비군별로 편 것이다 — `rf_power`·`chamber_pressure`는 ETCH·DEPO 양쪽에서
계측되어 두 번 나온다(그래서 표의 슬롯 합 23 ≠ 고유 21).

| 장비군 | 파라미터 이름 | 개수 |
|---|---|---|
| **LITHO** | `exposure_dose` · `focus_offset` · `stage_temp` · `alignment_offset` | 4 |
| **ETCH** | `rf_power` · `chamber_pressure` · `he_flow` · `temperature` · `etch_rate` | 5 |
| **DEPO** | `chamber_pressure` · `rf_power` · `gas_flow` · `susceptor_temp` · `deposition_rate` | 5 |
| **CMP** | `down_force` · `slurry_flow` · `pad_usage_hours` | 3 |
| **CLEAN** | `flow_rate` · `megasonic_power` · `chemical_temp` · `rinse_time` | 4 |
| **EDS** | `chuck_temp` · `contact_resistance` | 2 |

## 준비

### 1. Neo4j 접속 (DB가 있어야 파이프라인이 돈다)

**0728부터 AuraDB(관리형 클라우드)를 쓴다 — 로컬 설치는 하지 않는다.**
[console.neo4j.io](https://console.neo4j.io)에서 인스턴스를 만들면 자격증명 파일이 1회
내려온다. **비밀번호는 생성 직후 한 번만 표시되므로 반드시 저장할 것.**

접속값은 아래 형태이고, 로컬 시절과 달리 스킴이 `bolt://`가 아니라 **`neo4j+s://`**(TLS)다:

```ini
NEO4J_URI=neo4j+s://xxxxxxxx.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<콘솔에서 받은 값>
NEO4J_DATABASE=neo4j
```

붙는지부터 확인하고 넘어간다 — 안 붙으면 이후 스크립트가 전부 같은 지점에서 죽는다:

```bash
python 1_test_connection.py
```

> APOC·GDS 같은 플러그인은 필요 없다. 순회는 순수 Cypher다.
> DB 이름은 Aura에서 `neo4j` 하나로 고정된다 (`NEO4J_DATABASE`, 별도 DB 생성 불가).
> 무료 티어는 장기간 미사용 시 인스턴스가 일시정지된다 — 콘솔에서 재개하면 된다.
> **데모/발표 당일 아침에 인스턴스가 깨어 있는지 반드시 확인할 것.**

### 2. 파이썬 환경

가상환경은 `kg_rca/`가 아니라 저장소 루트(`SesacLine_SemiRCA/`)에서 하나로 관리한다(`pyproject.toml`에
`kg_rca` 의존성도 포함되어 있음).

```bash
cd ..                    # 저장소 루트로 이동
pip install uv
uv venv
uv sync
.venv\Scripts\activate   # Windows (macOS/Linux: source .venv/bin/activate)
```

### 3. 환경변수 (`.env`)

`.env_example`을 복사해 값을 채운다. 코드는 `python-dotenv`로 이 파일을 자동으로 읽는다.

```bash
cp .env_example .env
```

| 변수 | 예시 | 설명 |
|---|---|---|
| `OPENAI_API_KEY` | `sk-...` | 추출·문장 합성용. langchain이 자동으로 읽는다 |
| `KG_EXTRACT_MODEL` | `gpt-5.4-mini` | 5번(추출). **미설정이 기본** — 코드 기본값이 곧 정본 |
| `KG_SYNTH_MODEL` | `gpt-5.4-mini` | 6번(합성). 동상 |
| `ANCHOR_MODEL` | (미설정) | 앵커 보강 패스만 상위 모델. 미설정이면 `KG_EXTRACT_MODEL`과 동일 |
| `NEO4J_URI` | `neo4j+s://xxxx.databases.neo4j.io` | Aura 접속 주소(TLS). 구 로컬값은 `bolt://localhost:7687` |
| `NEO4J_USERNAME` | `neo4j` | 기본 계정명 |
| `NEO4J_PASSWORD` | (콘솔 발급값) | **Aura 인스턴스 생성 시 1회만 표시된다 — 저장 필수** |
| `NEO4J_DATABASE` | `neo4j` | Aura는 `neo4j` 고정 |

> ⚠️ 이 값들은 **저장소 루트의 `.env` 한 곳**에만 둔다(0728 통합 — `kg_rca/.env`는 삭제됐다).
> 이 스크립트들은 인자 없는 `load_dotenv()`를 쓰는데, `find_dotenv()`는 cwd가 아니라 **호출한
> `.py` 파일의 디렉터리**부터 위로 걷는다. 즉 `kg_rca/.env`가 있으면 실행 위치와 무관하게 항상
> 그쪽이 먼저 잡혀 루트 `.env`가 영영 안 읽힌다(두 파일이 갈리면 "5번은 되는데 6번은 죽는"
> 식으로 조용히 어긋난다). 없으면 같은 탐색이 한 칸 더 올라가 루트 `.env`를 찾는다.
> **`kg_rca/.env`를 다시 만들지 말 것.**

선택 변수: `TOP_K` — `6_ask_graphrag.py`의 패턴별 가설 출력 상한 (미설정 시 전건 출력).

`.env`는 `.gitignore`에 있다. 커밋하지 말 것.
설정이 끝나면 `python 1_test_connection.py`로 연결을 먼저 확인한다.

## 실행

```bash
python 1_test_connection.py            # Neo4j 연결 확인
python 0_reset.py                      # DB 전체 초기화 (스키마 변경 후 필수, y 확인)
python 2_load_txt.py                   # data/raw/ + data/docs/ -> outputs/parsed_docs.jsonl
python 3_split.py                      #           -> outputs/chunks.jsonl (표 행 = 청크)
python 4_ingest_chunks_to_neo4j.py     # 시드 앵커(:Evidence 포함) + Document/Chunk 적재
python 5_build_kg_from_chunks.py       # LLM 추출 -> outputs/extracted_kg.jsonl + Neo4j
python 6_ask_graphrag.py               # 패턴별 가설 전건 -> stdout + outputs/hypotheses.json
python 7_build_signature_index.py      # (선택) 의미 진입용 시그니처 임베딩 -> outputs/signature_index.json
```

- `6_ask_graphrag.py`는 기본으로 탐색된 **모든** 가설을 낸다. 상한을 두려면 `TOP_K=3 python 6_ask_graphrag.py`.
- `7_build_signature_index.py`는 backend 라이브 조회(`KG_LIVE`+`KG_SEMANTIC`)의 **의미 진입**용
  선택 산출물이다. **그래프를 재빌드(0~5 재실행)하면 이 인덱스도 낡으므로 반드시 다시 돌린다**
  (인덱스는 그래프의 파생 스냅샷). 안 쓰면 backend는 패턴/enum 진입만으로 동작한다.
- 질문은 `"{패턴} 결함 패턴이 나타나는 근본 원인은 무엇인가요?"` 하나로 고정.
  Cypher는 LLM이 생성하지 않는다(결정적 순회). LLM은 경로를 한국어 문장으로 옮기고 관계를 추출할 때만 쓴다.
- `outputs/hypotheses.json`: 가설마다 경로·검증 등급·`direction`·`fab_table`·점수 성분·
  근거(`chunk_ids`/`quotes`)를 담은 구조화 출력. hypothesis agent의 입력용.

> `0_reset.py`를 건너뛰고 스키마를 바꾸면 중복 노드가 생긴다.
> Neo4j의 UNIQUE 제약은 null을 무시하므로, `id`가 없는 옛 노드를 `MERGE {id: ...}`가 찾지 못한다.

## 데이터

```text
data/
  raw/      실문헌 (파이프라인 입력. .txt / .md, 하위 디렉토리는 제외)
    cause_center.txt, cause_edgering.txt, cause_scratch.txt
                                       문서 A: 패턴 -> 공정 산문        (ARISES_IN)
    table_sze_troubleshooting.md       문서 B: 교과서 트러블슈팅 표 82행 (FailureMode -> Cause -> Evidence)
    table_ref56_patterns.md            문서 C: 논문 Table 1, 패턴 -> 원인 직결 (ATTRIBUTED_TO)
    paper_liao_rag.txt                 문서 D: Liao et al. 2026, 패턴/형상 -> 공정 (ARISES_IN, FORMS_IN)
    paper_edgering_cmp.txt             문서 E: Xie & Boning 2005, Edge-Ring -> CMP (ARISES_IN)
    _reference/                        교과서 본문 339KB — 로더가 읽지 않음
  docs/     [v3.0] 전문가 암묵지 목업 (파이프라인 입력. 2_load가 raw와 함께 읽음)
    doc_A_wafermap_patterns.txt        패턴 -> 공정 + HAS_SIGNATURE(형상노드 정의)
    doc_B~G_*_troubleshooting.txt      공정별 내부 체인 (OCCURS_IN / CAUSED_BY / VERIFIED_BY)
    doc_H_spatial_morphology_...txt    형상·모폴로지 -> 공정 (FORMS_IN + density/continuity/angular/clock)
  seeds/    고정 vocabulary (문헌에서 뽑지 않고 미리 적재하는 앵커 — 이 3종이 전부)
    defect_patterns.json   3종   VLM 출력 클래스와 일치해야 함
    process_steps.json     6종   join key: lot_history.step
    parameters.json       21종   join key: telemetry.param  (steps 필드 = 별칭 해석 스코프)
```

`FailureMode` / `Cause` / `Maintenance` / `Recipe` / `SpatialSignature`는 LLM이 문헌에서 만든다.
단 `SpatialSignature`는 어휘가 코드 enum(`shape` 6종 × `zone` 4종)으로 닫혀 있고
id를 코드가 `{shape}@{zone}`으로 조합하므로, 표현이 달라도 노드가 파편화되지 않는다.
앵커 3종(`DefectPattern`/`ProcessStep`/`Parameter`)은 시드에 있는 노드에 **연결만** 한다 —
LLM이 뱉은 표기(`circular ring`, `etching step`, `RF Power`)는 시드 `aliases` 역인덱스로
canonical id에 치환된 뒤 `MATCH`로만 붙으므로, 시드 밖 노드는 생길 수 없다.
`Parameter`는 공정 조건부로 해석된다 (`temperature`가 ETCH에선 `temperature`, DEPO에선 `susceptor_temp`).

시드 id는 추출 코드의 `Literal`에도 하드코딩돼 있어, 시드만 바꾸면 실행 즉시
`assert_enums_match_seeds()`가 예외를 던진다. 둘을 함께 고칠 것.

## 현재 상태

진행 상황·남은 문제·다음 작업은 [`STATUS.md`](STATUS.md) 참조.
진입점 엣지(ARISES_IN/FORMS_IN/ATTRIBUTED_TO)는 추출 비결정성 완화를 위해
패턴/형상 언급 청크만 `ANCHOR_PASSES`(기본 3)회 재추출해 합집합한다.

> **[v3.0 · 2026-07-22]** `data/docs`(doc_A~H) 로더 편입 + `FORMS_IN` 모폴로지(설계 B) +
> angular 판별자 재랭킹이 **코드에 반영**됐다. 단 위 실행 수치(문헌 6편 기준)는 v2.4 시점 값이라,
> 새 문헌·모폴로지가 그래프에 실제 반영되려면 `0_reset→3→4→5→6` **재빌드가 필요**하다
> (LLM 비용·비결정). 데이터 모델 전체는 [`데이터 모델 설계_v3.0.md`](데이터%20모델%20설계_v3.0.md).
