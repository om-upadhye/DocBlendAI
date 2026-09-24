"""Module 2 — OCR path (scanned/printed PDFs).

Responsibility: rasterize pages and run pytesseract, returning page text plus
a confidence (0-1) as raw_conf for Module 3. raw_conf is the mean of
Tesseract's word confidences, weighted by word length, so it tracks the share
of characters recognized confidently.

Uses from schemas.py: nothing directly; output feeds chunker.py -> RecognizedChunk.
Requires the Tesseract binary on the system (see CLAUDE.md).
"""

import shutil
from contextlib import closing
from functools import lru_cache
from pathlib import Path

import pytesseract
from PIL import Image

from app.config import settings
from app.modules.pdf_render import render_pages

# The UB Mannheim Windows installer's default location (not added to PATH by default).
_WINDOWS_DEFAULT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


class OCRUnavailableError(RuntimeError):
    """The Tesseract binary could not be found."""


@lru_cache
def _tesseract_cmd(configured: str) -> str:
    for candidate in (configured, shutil.which("tesseract"), str(_WINDOWS_DEFAULT)):
        if candidate and Path(candidate).is_file():
            return candidate
    raise OCRUnavailableError(
        "Tesseract is not installed. Install it (Windows: winget install UB-Mannheim.TesseractOCR) "
        "or set TESSERACT_CMD in .env to the full path of tesseract.exe."
    )


def ocr_image(image: Image.Image) -> tuple[str, float]:
    """OCR one page image. Returns (text, raw_conf); a page with no words gives ("", 0.0)."""
    pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd(settings.tesseract_cmd)
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

    # Rebuild text from word boxes: words on the same line joined by spaces,
    # lines by newlines, paragraphs by a blank line. conf == -1 marks non-word boxes.
    lines: dict[tuple[int, int, int], list[str]] = {}
    weighted, chars = 0.0, 0
    for word, conf, block, par, line in zip(
        data["text"], data["conf"], data["block_num"], data["par_num"], data["line_num"]
    ):
        word = word.strip()
        if not word or float(conf) < 0:
            continue
        lines.setdefault((block, par, line), []).append(word)
        weighted += float(conf) / 100 * len(word)
        chars += len(word)

    if not chars:
        return "", 0.0

    parts: list[str] = []
    prev_par = None
    for (block, par, _), words in lines.items():  # dicts keep Tesseract's reading order
        if prev_par is not None and (block, par) != prev_par:
            parts.append("")
        parts.append(" ".join(words))
        prev_par = (block, par)
    return "\n".join(parts), weighted / chars


def ocr_pdf(file_path: str, max_pages: int | None = None) -> list[tuple[str, float]]:
    """Return (page_text, raw_conf) for each page (or the first max_pages)."""
    # closing(): if OCR fails mid-document, release the PDF now, not at garbage
    # collection (Windows cannot delete a file that is still open).
    with closing(render_pages(file_path, settings.ocr_dpi, max_pages)) as pages:
        return [ocr_image(img) for img in pages]
