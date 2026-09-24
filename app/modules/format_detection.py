"""Module 2 — Format Detection & Text Extraction (router).

Responsibility: decide whether a PDF is typed, scanned, or handwritten, then
route it to the matching extractor (text_parser / ocr_extractor / htr_extractor).

Uses from schemas.py: Document, FormatType.
"""

from app.models.schemas import Document, FormatType


def detect_format(file_path: str) -> FormatType:
    """Classify the PDF's format (e.g. has a text layer -> TYPED)."""
    raise NotImplementedError("TODO: format detection")


def extract(document: Document) -> list[tuple[str, float]]:
    """Dispatch to the right extractor. Returns (page_text, raw_conf) per page."""
    raise NotImplementedError("TODO: route to text_parser / ocr_extractor / htr_extractor")
