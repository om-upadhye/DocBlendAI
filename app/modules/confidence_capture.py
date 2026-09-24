"""Module 3 — Confidence Capture & Calibration.

Responsibility: map each extractor's raw_conf onto a comparable 0-1 scale
(calibrated_conf), since OCR and HTR confidences are not directly comparable.

Calibrated confidence means "expected character accuracy" (1 - CER). Each
format gets a monotonic piecewise-linear table of (raw_conf, accuracy) knots,
fitted from evaluation samples with fit_calibration() and stored in
settings.calibration_file. Until a format has a fitted table, calibration is
the identity (calibrated_conf = raw_conf). Typed text is always 1.0.

Uses from schemas.py: RecognizedChunk, FormatType.
"""

import json
from functools import lru_cache

import numpy as np

from app.config import settings
from app.models.schemas import FormatType, RecognizedChunk

Knots = list[tuple[float, float]]


@lru_cache
def _tables(path: str) -> dict[str, Knots]:
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}
    return {fmt: [(float(x), float(y)) for x, y in knots] for fmt, knots in raw.items()}


def calibrate(raw_conf: float, format_type: FormatType) -> float:
    """Return the calibrated confidence for one raw score."""
    if format_type is FormatType.TYPED:
        return 1.0
    knots = _tables(str(settings.calibration_file)).get(format_type.value)
    if not knots:
        return raw_conf
    xs, ys = zip(*knots)
    return float(np.clip(np.interp(raw_conf, xs, ys), 0.0, 1.0))


def apply_calibration(chunks: list[RecognizedChunk], format_type: FormatType) -> list[RecognizedChunk]:
    """Return copies of the chunks with calibrated_conf set."""
    return [c.model_copy(update={"calibrated_conf": calibrate(c.raw_conf, format_type)}) for c in chunks]


def fit_calibration(samples: list[tuple[float, float]], bins: int = 10) -> Knots:
    """Fit knots from (raw_conf, observed_accuracy) samples, e.g. accuracy = 1 - CER per page.

    Samples are grouped into equal-width raw_conf bins; each non-empty bin
    becomes a knot at its mean (raw_conf, accuracy). Knots are then made
    non-decreasing (pool adjacent violators), so a higher raw score never
    maps to a lower calibrated score.
    """
    if not samples:
        raise ValueError("need at least one sample to fit calibration")
    raw = np.clip(np.array([s[0] for s in samples]), 0.0, 1.0)
    acc = np.clip(np.array([s[1] for s in samples]), 0.0, 1.0)
    idx = np.minimum((raw * bins).astype(int), bins - 1)

    # Each block: [mean_raw, mean_acc, weight]; merge neighbours while accuracy decreases.
    blocks: list[list[float]] = []
    for b in range(bins):
        mask = idx == b
        if mask.any():
            blocks.append([raw[mask].mean(), acc[mask].mean(), float(mask.sum())])
            while len(blocks) > 1 and blocks[-2][1] > blocks[-1][1]:
                x2, y2, w2 = blocks.pop()
                x1, y1, w1 = blocks.pop()
                w = w1 + w2
                blocks.append([(x1 * w1 + x2 * w2) / w, (y1 * w1 + y2 * w2) / w, w])
    return [(round(x, 4), round(y, 4)) for x, y, _ in blocks]


def save_calibration(format_type: FormatType, knots: Knots) -> None:
    """Store a fitted table for one format in settings.calibration_file."""
    path = settings.calibration_file
    tables = dict(_tables(str(path)))
    tables[format_type.value] = knots
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tables, indent=2), encoding="utf-8")
    _tables.cache_clear()
