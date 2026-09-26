"""One-time setup check: Python, Tesseract, the TrOCR model, and the Gemini key.

Run after `pip install -r requirements.txt`:

    venv/Scripts/python -m scripts.setup_models

It downloads the handwriting model now (instead of on the first handwritten
upload) and tells you exactly what is missing. It never prints your API key
and makes no Gemini calls.
"""

import sys

from app import __version__
from app.config import settings

REQUIRED_PYTHON = (3, 11)


def check(label: str, ok: bool, detail: str) -> bool:
    print(f"  [{'OK' if ok else 'MISSING'}] {label}: {detail}")
    return ok


def main() -> int:
    print(f"DocBlendAI {__version__} setup check\n")
    results = []

    py = sys.version_info
    results.append(check(
        "Python", py[:2] == REQUIRED_PYTHON,
        f"{py.major}.{py.minor}.{py.micro}" + ("" if py[:2] == REQUIRED_PYTHON else " (use Python 3.11)"),
    ))

    from app.modules import ocr_extractor

    try:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = ocr_extractor._tesseract_cmd(settings.tesseract_cmd)
        version = pytesseract.get_tesseract_version()
        languages = pytesseract.get_languages()
        results.append(check("Tesseract OCR", True, f"{version} at {pytesseract.pytesseract.tesseract_cmd}"))
        results.append(check(
            "Tesseract data", {"eng", "osd"} <= set(languages),
            "eng + osd (orientation) installed" if {"eng", "osd"} <= set(languages)
            else f"found {languages}; reinstall Tesseract with English and OSD data",
        ))
    except ocr_extractor.OCRUnavailableError as e:
        results.append(check("Tesseract OCR", False, str(e)))

    from app.modules import htr_extractor, paddle_extractor

    try:
        paddle_extractor._engine(settings.ocr_threads)
        results.append(check("PaddleOCR engine", True, "PP-OCRv6 via RapidOCR / ONNX Runtime (models bundled)"))
    except htr_extractor.HTRUnavailableError as e:
        results.append(check("PaddleOCR engine", settings.htr_engine != "paddle", str(e)))

    print(f"\n  Downloading / loading TrOCR model {settings.htr_model} (optional engine; first time: a few hundred MB)...")
    try:
        htr_extractor._load(settings.htr_model)
        from huggingface_hub.constants import HF_HUB_CACHE

        results.append(check("TrOCR model", True, f"{settings.htr_model} ready (cache: {HF_HUB_CACHE})"))
    except htr_extractor.HTRUnavailableError as e:
        # Only required when TrOCR is the selected engine.
        results.append(check("TrOCR model", settings.htr_engine != "trocr", str(e)))

    print(f"  Handwriting engine in use: {settings.htr_engine} (set HTR_ENGINE=paddle|trocr in .env)")

    results.append(check(
        "Gemini API key", bool(settings.gemini_api_key),
        "set in .env" if settings.gemini_api_key else "copy .env.example to .env and set GEMINI_API_KEY",
    ))

    print("\nAll set. Start the app with:  venv/Scripts/python -m uvicorn app.main:app --reload"
          if all(results) else "\nFix the MISSING items above, then run this again.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
