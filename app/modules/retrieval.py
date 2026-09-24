"""Module 5 — Confidence-Aware Retrieval (RAG).

Responsibility: embed the question, search the vector store, and rank chunks
by combined_score = similarity + calibrated confidence.

Uses from schemas.py: Query, RecognizedChunk, RetrievalResult.
"""

from app.models.schemas import Query, RecognizedChunk, RetrievalResult


def combined_score(similarity: float, confidence: float) -> float:
    """Blend retrieval similarity with calibrated recognition confidence."""
    raise NotImplementedError("TODO (build step 5)")


def retrieve(query: Query, top_k: int = 5) -> list[tuple[RecognizedChunk, RetrievalResult]]:
    """Return the top_k chunks and their scores, best first."""
    raise NotImplementedError("TODO (build step 3: similarity only; step 5: combined_score)")
