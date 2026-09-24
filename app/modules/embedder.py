"""Supports Module 5 — Gemini embeddings.

Responsibility: turn chunk text and questions into vectors via the Gemini
embedding API (key from config.settings.gemini_api_key).

Uses from schemas.py: RecognizedChunk (fills its vector field).
"""

from app.models.schemas import RecognizedChunk


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of document texts."""
    raise NotImplementedError("TODO (build step 2)")


def embed_query(text: str) -> list[float]:
    """Embed a single question (query-side task type)."""
    raise NotImplementedError("TODO (build step 2)")


def embed_chunks(chunks: list[RecognizedChunk]) -> list[RecognizedChunk]:
    """Set vector on every chunk."""
    raise NotImplementedError("TODO (build step 2)")
