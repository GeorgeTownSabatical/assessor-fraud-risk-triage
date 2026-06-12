#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import textwrap


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Markdown-ish text to a simple dependency-free PDF.")
    parser.add_argument("input")
    parser.add_argument("output")
    args = parser.parse_args()
    render(Path(args.input), Path(args.output))
    return 0


def render(src: Path, out: Path) -> None:
    lines: list[str] = []
    for raw in src.read_text(encoding="utf-8").splitlines():
        raw = raw.replace("\t", "    ")
        if not raw:
            lines.append("")
            continue
        width = 96 if raw.startswith("|") else 100
        lines.extend(textwrap.wrap(raw, width=width, replace_whitespace=False, drop_whitespace=False) or [""])

    pages = [lines[i : i + 58] for i in range(0, len(lines), 58)] or [[]]
    objects: list[str] = []

    def add(obj: str) -> int:
        objects.append(obj)
        return len(objects)

    font_id = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    content_ids: list[int] = []
    page_ids: list[int] = []
    for page in pages:
        y = 760
        parts = ["BT", "/F1 9 Tf", "12 TL"]
        for line in page:
            safe = _pdf_escape(line)
            parts.append(f"1 0 0 1 36 {y} Tm ({safe}) Tj")
            y -= 12
        parts.append("ET")
        stream = "\n".join(parts).encode("latin-1", "replace")
        content_ids.append(add(f"<< /Length {len(stream)} >>\nstream\n{stream.decode('latin-1')}\nendstream"))

    for content_id in content_ids:
        page_ids.append(
            add(
                f"<< /Type /Page /Parent 0 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
            )
        )
    pages_id = add("<< /Type /Pages /Kids [" + " ".join(f"{pid} 0 R" for pid in page_ids) + f"] /Count {len(page_ids)} >>")
    for page_id in page_ids:
        objects[page_id - 1] = objects[page_id - 1].replace("/Parent 0 0 R", f"/Parent {pages_id} 0 R")
    catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

    chunks = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
    offsets = [0]
    for idx, obj in enumerate(objects, 1):
        offsets.append(sum(len(chunk) for chunk in chunks))
        chunks.append(f"{idx} 0 obj\n{obj}\nendobj\n".encode("latin-1", "replace"))

    xref = sum(len(chunk) for chunk in chunks)
    chunks.append(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1"))
    for offset in offsets[1:]:
        chunks.append(f"{offset:010d} 00000 n \n".encode("latin-1"))
    chunks.append(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("latin-1")
    )
    out.write_bytes(b"".join(chunks))


def _pdf_escape(value: str) -> str:
    return value.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


if __name__ == "__main__":
    raise SystemExit(main())

