"""Module 2 — direct parsing path (typed/digital PDFs).

Responsibility: pull text from a PDF's embedded text layer (pdfplumber).
No recognition step, so raw_conf is 1.0 for every page.

Uses from schemas.py: nothing directly; output feeds chunker.py -> RecognizedChunk.
"""

import pdfplumber

TYPED_CONFIDENCE = 1.0


def parse_pdf(file_path: str) -> list[tuple[str, float]]:
    """Return (page_text, raw_conf=1.0) for each page; pages without text give ""."""
    with pdfplumber.open(file_path) as pdf:
        return [((page.extract_text() or "").strip(), TYPED_CONFIDENCE) for page in pdf.pages]
