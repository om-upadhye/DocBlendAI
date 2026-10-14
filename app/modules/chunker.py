"""Supports Modules 4/5 — text chunking.

Responsibility: split extracted page text into overlapping chunks, carrying
each page's raw_conf onto its chunks.

Uses from schemas.py: ContentType, RecognizedChunk.
"""

import re

from app.models.schemas import ContentType, RecognizedChunk

# A word plus the whitespace after it. Keeping the original whitespace (not
# re-joining with spaces) preserves line breaks that Module 4 needs to spot tables.
_TOKEN = re.compile(r"\S+\s*")


def chunk_pages(
    doc_id: str,
    pages: list[tuple[str, float]],
    chunk_size: int = 1000,
    overlap: int = 200,
    blocks: list[list[tuple[str, ContentType | None]] | None] | None = None,
) -> list[RecognizedChunk]:
    """Turn (page_text, raw_conf) pages into RecognizedChunks with unique chunk_ids.

    Chunks never cross a page boundary, so each chunk keeps its own page's
    raw_conf. Splits happen between words; a single word longer than
    chunk_size becomes its own chunk. chunk_id is "<doc_id>:<n>", stable
    across re-runs so ChromaDB upserts replace rather than duplicate.

    blocks (optional, per page): the page's layout regions in reading order as (text, content
    type or None); tables and figures then become their own chunks (see _block_pieces).
    """
    if not 0 <= overlap < chunk_size:
        raise ValueError("overlap must be >= 0 and smaller than chunk_size")

    chunks: list[RecognizedChunk] = []
    for i, (page_text, raw_conf) in enumerate(pages):
        page_blocks = blocks[i] if blocks and i < len(blocks) else None
        if not page_blocks:
            pieces = [(text, None) for text in _split(page_text, chunk_size, overlap)]
        else:
            pieces = _block_pieces(page_blocks, chunk_size, overlap)
        for text, kind in pieces:
            chunk = RecognizedChunk(chunk_id=f"{doc_id}:{len(chunks)}", text=text, raw_conf=raw_conf)
            chunks.append(chunk.model_copy(update={"content_type": kind}) if kind else chunk)
    return chunks


def _block_pieces(
    blocks: list[tuple[str, ContentType | None]], chunk_size: int, overlap: int
) -> list[tuple[str, ContentType | None]]:
    """Chunks for one page laid out in blocks (layout_analysis.qa_blocks).

    Consecutive untyped blocks (titles, paragraphs) are joined and split as usual; a table or
    figure block becomes its own chunk(s) with its content type, so a table is never cut into
    a paragraph. Long tables split between rows, each part repeating the header row.
    """
    pieces: list[tuple[str, ContentType | None]] = []
    running: list[str] = []

    def flush() -> None:
        if running:
            pieces.extend((text, None) for text in _split("\n\n".join(running), chunk_size, overlap))
            running.clear()

    for text, kind in blocks:
        if not text.strip():
            continue
        if kind is None:
            running.append(text)
            continue
        flush()
        if kind is ContentType.TABLE:
            pieces.extend((part, kind) for part in _split_table(text, chunk_size))
        else:
            pieces.extend((part, kind) for part in _split(text, chunk_size, overlap))
    flush()
    return pieces


def _split_table(text: str, chunk_size: int) -> list[str]:
    rows = [row for row in text.splitlines() if row.strip()]
    if len(text) <= chunk_size or len(rows) < 3:
        return [text.strip()]
    header, parts, current = rows[0], [], [rows[0]]
    for row in rows[1:]:
        if len(current) > 1 and sum(len(r) + 1 for r in current) + len(row) > chunk_size:
            parts.append("\n".join(current))
            current = [header]
        current.append(row)
    parts.append("\n".join(current))
    return parts


def _split(text: str, chunk_size: int, overlap: int) -> list[str]:
    tokens = _TOKEN.findall(text)
    pieces: list[str] = []
    start = 0
    while start < len(tokens):
        end, length = start, 0
        while end < len(tokens) and (end == start or length + len(tokens[end].rstrip()) <= chunk_size):
            length += len(tokens[end])
            end += 1
        pieces.append("".join(tokens[start:end]).strip())
        if end == len(tokens):
            break

        # Step back over whole words until ~overlap chars repeat, always advancing at least one word.
        next_start, back = end, 0
        while next_start - 1 > start and back + len(tokens[next_start - 1]) <= overlap:
            next_start -= 1
            back += len(tokens[next_start])
        start = next_start
    return pieces
