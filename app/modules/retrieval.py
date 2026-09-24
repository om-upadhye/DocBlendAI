"""Module 5 — Confidence-Aware Retrieval (RAG).

Responsibility: embed the question, search the vector store, and rank chunks
by combined_score, a weighted sum of retrieval similarity and calibrated
recognition confidence:

    combined_score = w * similarity + (1 - w) * confidence    (w = settings.similarity_weight)

A wider candidate pool is fetched by similarity alone, then re-ranked by
combined_score, so a relevant chunk can win over a slightly more similar one
that was poorly recognized.

Uses from schemas.py: Query, RecognizedChunk, RetrievalResult.
"""

from app.config import settings
from app.models.schemas import Query, RecognizedChunk, RetrievalResult
from app.modules import embedder, vector_store


def combined_score(similarity: float, confidence: float) -> float:
    """Blend retrieval similarity with calibrated recognition confidence."""
    w = settings.similarity_weight
    return w * similarity + (1 - w) * confidence


def retrieve(query: Query, top_k: int = 5) -> list[tuple[RecognizedChunk, RetrievalResult]]:
    """Return the top_k chunks and their scores, best combined_score first.

    Raises embedder.EmbeddingError if the question cannot be embedded.
    """
    hits = vector_store.search(embedder.embed_query(query.question_text), top_k * settings.candidate_multiplier)
    scored = []
    for chunk, similarity in hits:
        confidence = chunk.calibrated_conf if chunk.calibrated_conf is not None else chunk.raw_conf
        result = RetrievalResult(
            chunk_id=chunk.chunk_id,
            similarity=similarity,
            confidence=confidence,
            combined_score=combined_score(similarity, confidence),
        )
        scored.append((chunk, result))
    scored.sort(key=lambda pair: pair[1].combined_score, reverse=True)
    return scored[:top_k]
