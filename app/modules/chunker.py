"""Supports Modules 4/5 — text chunking.

Responsibility: split extracted page text into overlapping chunks, carrying
each page's raw_conf onto its chunks.

Uses from schemas.py: RecognizedChunk.
"""

from app.models.schemas import RecognizedChunk


def chunk_pages(
    doc_id: str,
    pages: list[tuple[str, float]],
    chunk_size: int = 1000,
    overlap: int = 200,
) -> list[RecognizedChunk]:
    """Turn (page_text, raw_conf) pages into RecognizedChunks with unique chunk_ids."""
    raise NotImplementedError("TODO (build step 1)")
