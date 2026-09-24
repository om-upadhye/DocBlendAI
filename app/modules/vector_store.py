"""Module 5 — ChromaDB client wrapper.

Responsibility: persist RecognizedChunk vectors (plus content_type and
calibrated_conf as metadata) in ChromaDB at settings.chroma_dir, and run
similarity search. Nothing relational is stored here (that is SQLite).

Uses from schemas.py: RecognizedChunk.
"""

from app.models.schemas import RecognizedChunk


def add_chunks(doc_id: str, chunks: list[RecognizedChunk]) -> None:
    """Upsert embedded chunks for one document."""
    raise NotImplementedError("TODO (build step 2)")


def search(query_vector: list[float], top_k: int = 5) -> list[tuple[RecognizedChunk, float]]:
    """Return the top_k nearest chunks with their similarity scores."""
    raise NotImplementedError("TODO (build step 3)")
