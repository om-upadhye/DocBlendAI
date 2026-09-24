"""Module 7 — LLM Answer Generation.

Responsibility: prompt Gemini with the question and retrieved chunk text,
and return the answer tagged with its reliability label.

Uses from schemas.py: Query, RecognizedChunk, ReliabilityLabel, Answer.
"""

from app.models.schemas import Answer, Query, RecognizedChunk, ReliabilityLabel


def generate_answer(
    query: Query,
    chunks: list[RecognizedChunk],
    reliability_label: ReliabilityLabel,
) -> Answer:
    """Generate a grounded answer from the retrieved chunks."""
    raise NotImplementedError("TODO (build step 3)")
