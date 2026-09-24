"""Supports Module 2 — render PDF pages to images for OCR and HTR.

Responsibility: rasterize pages with pypdfium2 (already a pdfplumber
dependency, so no Poppler install is needed).

Uses from schemas.py: nothing; returns PIL images to ocr_extractor/htr_extractor.
"""

from collections.abc import Iterator

import pypdfium2 as pdfium
from PIL import Image

PDF_POINTS_PER_INCH = 72


def render_pages(file_path: str, dpi: int, max_pages: int | None = None) -> Iterator[Image.Image]:
    """Yield each page as a grayscale PIL image at the given DPI."""
    pdf = pdfium.PdfDocument(file_path)
    try:
        count = len(pdf) if max_pages is None else min(len(pdf), max_pages)
        for i in range(count):
            page = pdf[i]
            try:
                yield page.render(scale=dpi / PDF_POINTS_PER_INCH).to_pil().convert("L")
            finally:
                page.close()
    finally:
        pdf.close()
