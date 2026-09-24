"""Module 2 — HTR path (handwritten PDFs).

Responsibility: segment pages into lines and run TrOCR (transformers),
returning page text plus a sequence-probability confidence (0-1) as raw_conf.

Uses from schemas.py: nothing directly; output feeds chunker.py -> RecognizedChunk.
"""


def htr_pdf(file_path: str) -> list[tuple[str, float]]:
    """Return (page_text, raw_conf) for each page."""
    raise NotImplementedError("TODO (build step 4): TrOCR handwriting recognition")
