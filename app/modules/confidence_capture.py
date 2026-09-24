"""Module 3 — Confidence Capture & Calibration.

Responsibility: map each extractor's raw_conf onto a comparable 0-1 scale
(calibrated_conf), since OCR and HTR confidences are not directly comparable.

Uses from schemas.py: RecognizedChunk, FormatType.
"""

from app.models.schemas import FormatType, RecognizedChunk


def calibrate(raw_conf: float, format_type: FormatType) -> float:
    """Return the calibrated confidence for one raw score."""
    raise NotImplementedError("TODO (build step 4): per-format calibration")


def apply_calibration(chunks: list[RecognizedChunk], format_type: FormatType) -> list[RecognizedChunk]:
    """Fill calibrated_conf on every chunk."""
    raise NotImplementedError("TODO (build step 4)")
