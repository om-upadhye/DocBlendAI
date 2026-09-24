"""Module 2 — direct parsing path (typed/digital PDFs).

Responsibility: pull text from a PDF's embedded text layer (pdfplumber/PyPDF2).
No recognition step, so raw_conf is 1.0 for every page.

Uses from schemas.py: nothing directly; output feeds chunker.py -> RecognizedChunk.
"""


def parse_pdf(file_path: str) -> list[tuple[str, float]]:
    """Return (page_text, raw_conf=1.0) for each page."""
    raise NotImplementedError("TODO (build step 1): pdfplumber text extraction")
