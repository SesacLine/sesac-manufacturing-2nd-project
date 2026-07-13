# mapping_table.yaml -> mapping_table.md 렌더링
# .md는 이 스크립트로만 생성. 직접 편집 금지 — 수기 복사가 .yaml과의 드리프트 만듦.
import yaml, pathlib

def main():
    data = yaml.safe_load(pathlib.Path("simulator/mapping_table.yaml").read_text())
    lines = [
        "<!-- 자동 생성: python -m simulator.render_mapping_md — 직접 편집 금지 -->",
        "# 결함↔후보 원인 매핑 테이블",
        "",
        "이 테이블은 (a) 시나리오 생성 스펙, (b) KG 구축 시드, (c) 평가 정답지의 공통 원천.",
        "단일 진실원본은 `mapping_table.yaml`이며 본 문서는 리뷰용 렌더링.",
        "리뷰 코멘트(현직자 검토)는 이 파일이 아니라 `mapping_table_review.md`에 남김.",
        "",
    ]
    for pattern, causes in data.items():
        lines += [
            f"## {pattern}",
            "",
            "| cause | process | equipment_group | prob | telemetry (param / drift) | citation |",
            "|---|---|---|---|---|---|",
        ]
        for c in causes:
            sig = c["telemetry_signature"]
            lines.append(
                f"| {c['cause']} | {c['process']} | {c['equipment_group']} "
                f"| {c['prob']} | {sig['param']} / {sig['drift']} | {c['citation']} |")
        lines.append("")
    pathlib.Path("simulator/mapping_table.md").write_text("\n".join(lines), encoding="utf-8")
    print("rendered simulator/mapping_table.md")

if __name__ == "__main__":
    main()
