from dataclasses import dataclass
from pathlib import Path
from collections import Counter

import pymupdf


@dataclass(frozen=True)
class ExtractedPDF:
    pages: list[tuple[int, str]]
    page_count: int
    title: str
    publisher: str
    sparse_pages: list[int]


def extract_pdf(path: Path) -> ExtractedPDF:
    try:
        pdf = pymupdf.open(path)
        if not pdf.is_pdf or pdf.needs_pass:
            raise ValueError("Not a readable, unencrypted PDF")
        with pdf:
            if pdf.page_count == 0:
                raise ValueError("PDF has no pages")
            metadata = pdf.metadata or {}
            pages = []
            sparse = []
            for number, page in enumerate(pdf, 1):
                blocks = [b for b in page.get_text("blocks", sort=True) if len(b) > 6 and b[6] == 0 and b[4].strip()]
                # Reorder clear two-column body layouts; retain ordinary page order otherwise.
                width = page.rect.width
                left = [b for b in blocks if b[2] <= width * 0.5]
                right = [b for b in blocks if b[0] >= width * 0.5]
                if len(left) >= 3 and len(right) >= 3 and len(left) + len(right) == len(blocks):
                    blocks = sorted(left, key=lambda b: b[1]) + sorted(right, key=lambda b: b[1])
                text = "\n\n".join(b[4].strip() for b in blocks)
                pages.append((number, text))
                if len(text.strip()) < 40:
                    sparse.append(number)
            if not any(text.strip() for _, text in pages):
                raise ValueError("No selectable text; document may require OCR")
            if len(pages) >= 3:
                lines_by_page = [text.splitlines() for _, text in pages]
                for edge in (0, -1):
                    edge_lines = [next((line for line in (lines if edge == 0 else reversed(lines)) if line.strip()), "") for lines in lines_by_page]
                    repeated = Counter(line for line in edge_lines if line and len(line) < 120)
                    boilerplate = {line for line, count in repeated.items() if count >= 3 and count > len(pages) / 2}
                    for i in range(1, len(lines_by_page)):
                        if edge_lines[i] in boilerplate:
                            index = next((j for j in (range(len(lines_by_page[i])) if edge == 0 else range(len(lines_by_page[i]) - 1, -1, -1)) if lines_by_page[i][j].strip()), None)
                            if index is not None:
                                lines_by_page[i].pop(index)
                pages = [(number, "\n".join(lines)) for (number, _), lines in zip(pages, lines_by_page)]
            title = (metadata.get("title") or "").strip()
            if not title:
                lines = [line.strip() for line in pages[0][1].splitlines() if line.strip()]
                title = (" ".join(lines[:2]) if len(lines) > 1 and len(lines[0]) < 60 and len(lines[1]) < 60 else (lines[0] if lines else ""))[:200]
            publisher = (metadata.get("author") or "").strip()
            return ExtractedPDF(pages, pdf.page_count, title, publisher, sparse)
    except (pymupdf.FileDataError, pymupdf.EmptyFileError) as exc:
        raise ValueError("PDF could not be opened or read") from exc
