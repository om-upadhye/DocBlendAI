"""Module 5 — Confidence-Aware Retrieval (RAG).

Responsibility: embed the question, search the vector store, and rank chunks
by combined_score = similarity + calibrated confidence.

Build step 3 (typed-only): combined_score is just the similarity. Step 5
switches it to combined_score() once OCR/HTR confidences exist.

Uses from schemas.py: Query, RecognizedChunk, RetrievalResult.
"""

from app.models.schemas import Query, RecognizedChunk, RetrievalResult
from app.modules import embedder, vector_store


def combined_score(similarity: float, confidence: float) -> float:
    """Blend retrieval similarity with calibrated recognition confidence."""
    raise NotImplementedError("TODO (build step 5)")


def retrieve(query: Query, top_k: int = 5) -> list[tuple[RecognizedChunk, RetrievalResult]]:
    """Return the top_k chunks and their scores, best first.

    Raises embedder.EmbeddingError if the question cannot be embedded.
    """
    hits = vector_store.search(embedder.embed_query(query.question_text), top_k)
    results = []
    for chunk, similarity in hits:
        confidence = chunk.calibrated_conf if chunk.calibrated_conf is not None else chunk.raw_conf
        # TODO (build step 5): combined_score(similarity, confidence), then re-sort.
        result = RetrievalResult(
            chunk_id=chunk.chunk_id, similarity=similarity, confidence=confidence, combined_score=similarity
        )
        results.append((chunk, result))
    return results
