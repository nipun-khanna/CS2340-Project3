import re
from dataclasses import dataclass

from .text_cleaner import clean_text


@dataclass(frozen=True)
class Chunk:
    text: str
    page_start: int
    page_end: int


def chunk_pages(pages: list[tuple[int, str]], target: int = 400, overlap: int = 50) -> list[Chunk]:
    if target < 1 or overlap < 0 or overlap >= target:
        raise ValueError("Chunk target must exceed overlap")
    chunks = []
    seen = set()
    for page_number, raw in pages:
        text = clean_text(raw)
        words = list(re.finditer(r"\S+", text))
        start = 0
        while start < len(words):
            end = min(start + target, len(words))
            if end < len(words):
                # Prefer ending at a sentence boundary near the target size.
                for candidate in range(end - 1, max(start + target // 2, end - 80) - 1, -1):
                    if re.search(r"[.!?][\"')\]]*$", words[candidate].group()):
                        end = candidate + 1
                        break
            piece = text[words[start].start():words[end - 1].end()].strip()
            if piece and (page_number, piece) not in seen:
                chunks.append(Chunk(piece, page_number, page_number))
                seen.add((page_number, piece))
            if end == len(words):
                break
            start = max(start + 1, end - overlap)
    return chunks
