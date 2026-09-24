"""Module 2 — Format Detection & Text Extraction (router).

Responsibility: decide whether a PDF is typed, scanned, or handwritten, then
route it to the matching extractor (text_parser / ocr_extractor / htr_extractor).

Uses from schemas.py: Document, FormatType.
"""

import pdfplumber

from app.models.schemas import Document, FormatType
from app.modules import htr_extractor, ocr_extractor, text_parser

# A page counts as "has a text layer" above this many extracted characters
# (filters out stray page numbers / headers on scanned pages).
MIN_TEXT_CHARS_PER_PAGE = 25
# Share of pages that must have a text layer for the PDF to count as typed.
MIN_TEXT_PAGE_RATIO = 0.5


def page_count(file_path: str) -> int:
    with pdfplumber.open(file_path) as pdf:
        return len(pdf.pages)


def detect_format(file_path: str) -> FormatType:
    """Classify the PDF's format from its text layer.

    Raises pdfplumber's PdfminerException if the file is not a readable PDF.
    """
    with pdfplumber.open(file_path) as pdf:
        pages = pdf.pages
        if not pages:
            return FormatType.SCANNED
        text_pages = sum(len((p.extract_text() or "").strip()) >= MIN_TEXT_CHARS_PER_PAGE for p in pages)

    if text_pages / len(pages) >= MIN_TEXT_PAGE_RATIO:
        return FormatType.TYPED
    # TODO (build step 4): tell scanned print apart from handwriting (image analysis).
    return FormatType.SCANNED


def extract(document: Document) -> list[tuple[str, float]]:
    """Dispatch to the right extractor. Returns (page_text, raw_conf) per page."""
    if document.format_type is FormatType.TYPED:
        return text_parser.parse_pdf(document.file_path)
    if document.format_type is FormatType.SCANNED:
        return ocr_extractor.ocr_pdf(document.file_path)
    return htr_extractor.htr_pdf(document.file_path)
