import re
import sys
import json
import unicodedata
from pathlib import Path

from langchain_core.documents import Document

# Windows 콘솔(cp949)에서 em-dash 등 유니코드 출력 시 크래시 방지
sys.stdout.reconfigure(encoding="utf-8")


# =========================
# 1. 경로 설정
# =========================

BASE_DIR = Path(__file__).resolve().parent          # 프로젝트 루트

# 원문 문헌. 하위 디렉토리(_reference/)는 읽지 않는다 — 교과서 본문을 거기 넣어 뒀다.
# 본문 339KB는 물리 이론 서술이라 RCA 노이즈만 늘리고, 인과 서술은
# _troubleshootingTABLE.md 에 100% 옮겨져 있다.
DOCS_DIR = BASE_DIR / "data" / "raw"
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_PATH = OUTPUT_DIR / "parsed_docs.jsonl"


# =========================
# 2. 텍스트 정제
# -------------------------
# .txt는 PDF보다 깨끗하지만, 최소한의 정규화는 해준다.
# =========================

def clean_text(text: str) -> str:
    if not text:
        return ""

    # 유니코드 정규화 (NFC)
    text = unicodedata.normalize("NFC", text)

    # 줄바꿈 통일
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 탭/연속 공백 정리
    text = re.sub(r"[ \t]+", " ", text)

    # 3줄 이상 연속 빈 줄은 2줄로
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# =========================
# 3. 문헌 로드
# -------------------------
# 파일 하나 = 문헌 하나(Document 하나).
# doc_id는 파일 이름(확장자 제외), title은 문서 첫 줄로 잡는다.
#
# 확장자 없이 떨궈진 텍스트 파일도 받는다(과거에 그런 문헌이 있었고, 조용히 누락됐었다).
# 내용이 빈 파일은 건너뛴다.
# =========================

TEXT_SUFFIXES = {"", ".txt", ".md"}


def load_txt_documents(docs_dir: Path) -> list[Document]:
    if not docs_dir.exists():
        raise FileNotFoundError(f"문헌 폴더를 찾을 수 없습니다: {docs_dir}")

    paths = sorted(
        p for p in docs_dir.iterdir()
        if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES
    )

    if not paths:
        raise FileNotFoundError(f"문헌 파일이 없습니다: {docs_dir}")

    docs = []

    for path in paths:
        raw = path.read_text(encoding="utf-8")
        cleaned = clean_text(raw)

        if not cleaned:
            print(f"  (건너뜀: 내용이 비어 있음) {path.name}")
            continue

        # 첫 줄을 제목으로 사용 (없으면 파일명)
        first_line = cleaned.split("\n", 1)[0].strip()
        title = first_line if first_line else path.stem

        docs.append(
            Document(
                page_content=cleaned,
                metadata={
                    "doc_id": path.stem,      # 예: "etch_rca_guide"
                    "title": title,
                    "source": path.name,      # 예: "etch_rca_guide.txt"
                },
            )
        )

    if not docs:
        raise ValueError(f"읽을 수 있는 문헌이 없습니다: {docs_dir}")

    return docs


# =========================
# 4. JSONL 저장
# -------------------------
# 다음 단계(3_split.py)가 다시 읽기 쉽도록 JSONL로 저장.
# =========================

def save_documents_to_jsonl(docs: list[Document], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        for doc in docs:
            row = {
                "doc_id": doc.metadata["doc_id"],
                "page_content": doc.page_content,
                "metadata": doc.metadata,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# =========================
# 5. 실행
# =========================

def main() -> None:
    print("문헌 폴더:", DOCS_DIR)

    docs = load_txt_documents(DOCS_DIR)
    print("불러온 문헌 수:", len(docs))

    for doc in docs:
        print(f"- {doc.metadata['doc_id']} ({doc.metadata['title']})")

    docs = [
        Document(page_content=clean_text(d.page_content), metadata=d.metadata)
        for d in docs
    ]

    save_documents_to_jsonl(docs, OUTPUT_PATH)
    print("\n저장 완료:", OUTPUT_PATH)

    print("\n미리보기")
    print("=" * 80)
    print(docs[0].metadata)
    print(docs[0].page_content[:500])


if __name__ == "__main__":
    main()
