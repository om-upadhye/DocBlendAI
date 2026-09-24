"""Module 2 — OCR path (scanned/printed PDFs).

Responsibility: rasterize pages and run pytesseract, returning page text plus
the mean word-level confidence (0-1) as raw_conf for Module 3.

Uses from schemas.py: nothing directly; output feeds chunker.py -> RecognizedChunk.
Requires the Tesseract binary on the system (see CLAUDE.md).
"""


def ocr_pdf(file_path: str) -> list[tuple[str, float]]:
    """Return (page_text, raw_conf) for each page."""
    raise NotImplementedError("TODO (build step 4): pytesseract OCR")
