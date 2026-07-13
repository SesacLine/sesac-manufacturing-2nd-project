import re
import sys
import json
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Windows 콘솔(cp949)에서 em-dash 등 유니코드 출력 시 크래시 방지
sys.stdout.reconfigure(encoding="utf-8")


# =========================
# 1. 경로 설정
# =========================

BASE_DIR = Path(__file__).resolve().parent

INPUT_PATH = BASE_DIR / "outputs" / "parsed_docs.jsonl"
OUTPUT_PATH = BASE_DIR / "outputs" / "chunks.jsonl"


# =========================
# 2. parsed_docs.jsonl 로드
# =========================

def load_parsed_documents(input_path: Path) -> list[Document]:
    """
    2_load_txt.py가 저장한 parsed_docs.jsonl을 Document 리스트로 복원
    """
    if not input_path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {input_path}")

    docs = []

    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            docs.append(
                Document(
                    page_content=row["page_content"],
                    metadata=dict(row.get("metadata", {})),
                )
            )

    return docs


# =========================
# 3. 마크다운 트러블슈팅 표 청킹
# -------------------------
# 표 한 행이 곧 하나의 인과 서술(고장 → 원인 → 조치)이다.
# 500자 재귀 분할로 자르면 행이 잘려 인과가 끊긴다. 그래서 행 단위로 청크를 만든다.
#
# 표는 두 종류이고 열의 의미가 다르다.
#   troubleshooting : Problem | Probable Cause | Corrective Action
#                     (CMP는 한국어판) 문제점 | 발생 원인 | 해결방법
#   quality         : Quality Parameter | Types of Defects | Remarks
#                     (CMP는 한국어판) 품질 매개변수 | 결함의 형태 | 설명
#
# 어느 쪽인지 헤더로 판별해 역할 이름표를 붙인다. 5번 프롬프트가 이 이름표를 읽고
# "조치 열은 Cause가 아니다"를 지킨다.
# =========================

STEP_HEADING = re.compile(r"^#\s+([A-Z]{3,5})\b")
PROCESS_STEPS = {"LITHO", "ETCH", "DEPO", "CMP", "CLEAN", "EDS"}

# 헤더로 표 종류를 가른다 (영문판/한국어판 모두 대응)
TROUBLESHOOTING_KEYS = ("probable cause", "발생 원인")
QUALITY_KEYS = ("types of defects", "결함의 형태")
PATTERN_CAUSE_KEYS = ("source of defects",)   # ref56 Table 1: 패턴 -> 원인 직결

ROLE_LABELS = {
    "troubleshooting": ("고장모드", "원인", "조치"),
    "quality": ("품질항목", "결함유형", "비고"),
    "pattern_cause": ("불량패턴", "패턴설명", "원인"),
}

# 이 표들은 공정 섹션(`# ETCH`) 아래에 있지 않다. 공정 이름표를 붙이지 않는다.
STEPLESS_KINDS = {"pattern_cause"}


def _clean_cell(cell: str) -> str:
    cell = cell.replace("<br>", "\n").replace("<br/>", "\n")
    cell = cell.replace("**", "").strip()
    return re.sub(r"\n\s*", "\n", cell)


def _is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|[\s:|-]+\|", line.strip()))


def _classify(header_cells: list[str]) -> str | None:
    if len(header_cells) < 3:
        return None
    lowered = [c.lower() for c in header_cells]
    if any(k in c for c in lowered for k in PATTERN_CAUSE_KEYS):
        return "pattern_cause"
    h2 = lowered[1]
    if any(k in h2 for k in TROUBLESHOOTING_KEYS):
        return "troubleshooting"
    if any(k in h2 for k in QUALITY_KEYS):
        return "quality"
    return None


def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def chunk_markdown_tables(doc: Document) -> list[Document]:
    lines = doc.page_content.split("\n")
    chunks: list[Document] = []

    step = None
    title = None
    kind = None
    in_table = False

    i = 0
    while i < len(lines):
        line = lines[i]

        m = STEP_HEADING.match(line)
        if m and m.group(1) in PROCESS_STEPS:
            step, in_table = m.group(1), False

        elif line.startswith("#"):
            # `### TABLE 16.11 ...` 뿐 아니라, 공정 섹션이 없는 문서의 `# 제목`도 출처로 쓴다.
            title, in_table = line.lstrip("#").strip(), False

        elif line.strip().startswith("|"):
            # 헤더 행인가? (다음 줄이 구분선)
            if i + 1 < len(lines) and _is_separator(lines[i + 1]):
                kind = _classify(_split_row(line))
                in_table = kind is not None
                i += 2
                continue

            if in_table and not _is_separator(line):
                cells = _split_row(line)
                stepless = kind in STEPLESS_KINDS
                if len(cells) >= 3 and (step or stepless):
                    labels = ROLE_LABELS[kind]
                    body = "\n\n".join(
                        f"[{label}]\n{_clean_cell(cell)}"
                        for label, cell in zip(labels, cells[:3])
                        if _clean_cell(cell)
                    )
                    header = "" if stepless else f"공정: {step}\n"
                    text = (
                        f"{header}"
                        f"출처: {title}\n"
                        f"표 유형: {kind}\n\n{body}"
                    )
                    chunks.append(
                        Document(
                            page_content=text,
                            metadata={
                                **doc.metadata,
                                "step": None if stepless else step,
                                "table": title,
                                "table_kind": kind,
                            },
                        )
                    )
        i += 1

    return chunks


def looks_like_markdown_table(doc: Document) -> bool:
    return bool(re.search(r"^\|[\s:|-]+\|$", doc.page_content, re.M))


# =========================
# 4. 일반 문서 청킹
# -------------------------
# 문단(빈 줄) → 줄 → 문장 순으로 잘라 문맥이 최대한 안 끊기게 한다.
# =========================

def chunk_documents(docs: list[Document]) -> list[Document]:
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=80,
        add_start_index=True,
        keep_separator=True,
        separators=[
            "\n\n",   # 문단
            "\n",     # 줄
            ". ",     # 문장
            " ",
            "",
        ],
    )

    # 표 문서는 행 단위로, 나머지는 재귀 분할로 자른다.
    table_docs = [d for d in docs if looks_like_markdown_table(d)]
    prose_docs = [d for d in docs if not looks_like_markdown_table(d)]

    chunks: list[Document] = []
    for doc in table_docs:
        rows = chunk_markdown_tables(doc)
        print(f"  표 문서 {doc.metadata['doc_id']}: 행 {len(rows)}개")
        chunks.extend(rows)

    chunks.extend(text_splitter.split_documents(prose_docs))

    # 문서별 청크 순번을 매기기 위한 카운터
    per_doc_index: dict[str, int] = {}
    cleaned_chunks = []

    for chunk in chunks:
        text = chunk.page_content.strip()

        # 너무 짧은 청크는 버린다
        if len(text) < 20:
            continue

        doc_id = chunk.metadata.get("doc_id", "unknown")

        # 문서 안에서 0,1,2... 로 증가하는 순번
        idx = per_doc_index.get(doc_id, 0)
        per_doc_index[doc_id] = idx + 1

        # 사람이 읽기 좋은 chunk_id: "etch_rca_guide#c00"
        chunk_id = f"{doc_id}#c{idx:02d}"

        chunk.metadata["chunk_id"] = chunk_id
        chunk.metadata["chunk_index"] = idx
        chunk.metadata["char_count"] = len(text)
        chunk.page_content = text

        cleaned_chunks.append(chunk)

    return cleaned_chunks


# =========================
# 4. JSONL 저장
# =========================

def save_chunks_to_jsonl(chunks: list[Document], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            row = {
                "chunk_id": chunk.metadata["chunk_id"],
                "chunk_index": chunk.metadata["chunk_index"],
                "page_content": chunk.page_content,
                "metadata": chunk.metadata,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# =========================
# 5. 실행
# =========================

def main() -> None:
    docs = load_parsed_documents(INPUT_PATH)
    print("불러온 문헌 수:", len(docs))

    chunks = chunk_documents(docs)
    print("생성된 청크 수:", len(chunks))

    save_chunks_to_jsonl(chunks, OUTPUT_PATH)
    print("저장 완료:", OUTPUT_PATH)

    print("\n미리보기")
    print("=" * 80)
    for chunk in chunks[:3]:
        print("chunk_id:", chunk.metadata["chunk_id"])
        print("doc_id:", chunk.metadata.get("doc_id"))
        print("char_count:", chunk.metadata["char_count"])
        print(chunk.page_content[:300])
        print("-" * 80)


if __name__ == "__main__":
    main()
