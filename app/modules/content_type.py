"""Module 4 — Content-Type Identification.

Responsibility: label each chunk as table, paragraph, or image content.

Uses from schemas.py: ContentType, RecognizedChunk.
"""

from app.models.schemas import ContentType, RecognizedChunk


def classify(text: str) -> ContentType:
    """Return the content type of one piece of text."""
    raise NotImplementedError("TODO (build step 5)")


def label_chunks(chunks: list[RecognizedChunk]) -> list[RecognizedChunk]:
    """Set content_type on every chunk."""
    raise NotImplementedError("TODO (build step 5)")
