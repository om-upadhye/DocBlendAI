"""Module 2 — HTR path (handwritten PDFs and images).

Responsibility: split each page into text lines and run TrOCR (transformers)
on them, returning page text plus a confidence (0-1) as raw_conf for Module 3.

TrOCR reads one line at a time, so pages are segmented first. Real notes are
photos or scans of ruled notebook paper, so segmentation first flattens the
lighting, drops scan borders, erases ruling and margin lines, then splits the
ink-projection profile into lines using the page's own line spacing (see
text_mask / line_bands). A line's confidence is the geometric mean
of its generated tokens' probabilities; the page's raw_conf is the mean of
its lines' confidences weighted by line length.

Uses from schemas.py: nothing directly; output feeds chunker.py -> RecognizedChunk.
"""

import math
from contextlib import closing
from functools import lru_cache

import numpy as np
from PIL import Image, ImageFilter

from app.config import settings
from app.modules import ocr_extractor
from app.modules.pdf_render import denoise, render_pages

HTR_DPI = 200  # TrOCR resizes each line to 384x384 anyway; higher DPI only slows segmentation
BATCH_SIZE = 8
MAX_LINE_TOKENS = 64

# Line segmentation, as fractions of page height / width.
INK_LEVEL = 175  # after lighting is flattened (paper ~255), darker than this is ink
STROKE_MIN_FRACTION = 1 / 350  # vertical stroke length that separates letters from ruling lines
MIN_INK_ROW_FRACTION = 0.004  # a row counts as text if this share of its pixels is ink
MIN_LINE_HEIGHT = 0.008
MERGE_GAP = 0.002  # bands closer than this are one line (i-dots, broken strokes)
PITCH_MIN_CORRELATION = 0.2  # line spacing is trusted only if lines repeat this clearly
PAD = 0.006


class HTRUnavailableError(RuntimeError):
    """The TrOCR model could not be loaded (e.g. not downloaded and no internet)."""


def _otsu_threshold(gray: np.ndarray) -> int:
    hist = np.bincount(gray.ravel(), minlength=256).astype(float)
    total = gray.size
    cum_count = np.cumsum(hist)
    cum_sum = np.cumsum(hist * np.arange(256))
    best_t, best_var = 0, -1.0
    for t in range(255):
        w0 = cum_count[t]
        w1 = total - w0
        if w0 == 0 or w1 == 0:
            continue
        m0 = cum_sum[t] / w0
        m1 = (cum_sum[-1] - cum_sum[t]) / w1
        var = w0 * w1 * (m0 - m1) ** 2
        if var > best_var:
            best_t, best_var = t, var
    return best_t


def _long_runs(mask: np.ndarray, length: int) -> np.ndarray:
    """Pixels lying on a horizontal run of at least `length` True pixels (opening with a 1 x length kernel)."""
    h, w = mask.shape
    if w < length:
        return np.zeros_like(mask)
    c = np.cumsum(np.pad(mask.astype(np.int32), ((0, 0), (1, 0))), axis=1)
    start = (c[:, length:] - c[:, :-length]) == length  # a full run begins at this column
    s = np.cumsum(np.pad(start.astype(np.int32), ((0, 0), (1, 0))), axis=1)
    x = np.arange(w)
    lo = np.clip(x - length + 1, 0, start.shape[1])
    hi = np.clip(x + 1, 0, start.shape[1])
    return (s[:, hi] - s[:, lo]) > 0


def flatten_lighting(page: Image.Image) -> np.ndarray:
    """Divide out the paper background so shadows, gradients, and scan-edge darkening become white.

    The background is estimated by erasing ink (max filter) and blurring heavily.
    Returns a float array where paper is ~255 regardless of lighting.
    """
    gray = page.convert("L")
    w, h = gray.size
    background = gray.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(max(w, h) // 40))
    g = np.asarray(gray, dtype=np.float32)
    b = np.maximum(np.asarray(background, dtype=np.float32), 1.0)
    return np.clip(g / b * 255.0, 0, 255)


def text_mask(flat: np.ndarray) -> np.ndarray:
    """Ink that belongs to handwriting: no ruling lines, margin lines, or scan borders.

    Ruling lines on notebook paper curve and tilt, so they are removed by what
    they lack rather than their shape: they are only a few pixels thick, while
    letters have vertical strokes. Keeping only pixels on vertical runs of at
    least STROKE_MIN_FRACTION of the page height erases them at any angle.
    """
    h, w = flat.shape
    ink = flat < INK_LEVEL
    if ink.mean() > 0.5:  # mostly "ink": a blank dark or inverted page
        return np.zeros_like(ink)

    # Scan borders: edge columns that are mostly ink.
    edge = max(4, w // 40)
    for side in (slice(0, edge), slice(w - edge, w)):
        strip = ink[:, side]
        strip[:, strip.mean(axis=0) > 0.3] = False

    strokes = _long_runs(ink.T, max(5, int(STROKE_MIN_FRACTION * h))).T
    # Straight vertical margin lines survive the stroke filter; drop very long vertical runs.
    near = strokes | np.roll(strokes, 1, axis=1) | np.roll(strokes, -1, axis=1)
    margins = _long_runs(near.T, max(60, h // 8)).T
    return strokes & ~margins


def _line_pitch(mask: np.ndarray) -> int | None:
    """Typical distance between text lines, from the row profile's autocorrelation; None if unclear."""
    h = mask.shape[0]
    profile = mask.sum(axis=1).astype(float)
    p = profile - profile.mean()
    ac = np.correlate(p, p, "full")[h - 1 :]
    lo, hi = max(15, h // 80), max(40, h // 5)
    if hi >= h or ac[0] <= 0:
        return None
    pitch = lo + int(np.argmax(ac[lo:hi]))
    return pitch if ac[pitch] > PITCH_MIN_CORRELATION * ac[0] else None


def line_bands(mask: np.ndarray) -> list[tuple[int, int]]:
    """(top, bottom) rows of each text line in a text mask, top to bottom."""
    h, w = mask.shape
    rows = mask.sum(axis=1) >= max(2, MIN_INK_ROW_FRACTION * w)
    bands: list[list[int]] = []
    for y in np.flatnonzero(rows):
        if bands and y - bands[-1][1] <= max(1, MERGE_GAP * h):
            bands[-1][1] = y
        else:
            bands.append([y, y])

    pitch = _line_pitch(mask)
    if pitch:
        # Descenders and ascenders bridge the gap between handwritten lines, so bands can hold
        # several lines. Cut a band taller than ~1.5 lines at the emptiest row near each boundary.
        profile = np.convolve(mask.sum(axis=1).astype(float), np.ones(5) / 5, "same")
        split: list[list[int]] = []
        for top, bottom in bands:
            while bottom - top > 1.45 * pitch:
                lo, hi = top + int(0.6 * pitch), min(bottom - int(0.4 * pitch), top + int(1.4 * pitch))
                if hi <= lo:
                    break
                cut = lo + int(np.argmin(profile[lo:hi]))
                split.append([top, cut])
                top = cut + 1
            split.append([top, bottom])
        bands = split

        # Slivers (a stray descender, a leftover bit of ruling) join an adjacent line. A sliver is
        # short compared with this page's typical line AND hugs its neighbour; separate lines on
        # clean, widely spaced pages are short too but have clear gaps, so they stay apart.
        typical = float(np.median([b - t for t, b in bands])) if bands else 0.0

        def sliver(band: list[int]) -> bool:
            return band[1] - band[0] < 0.65 * typical

        merged: list[list[int]] = []
        for band in bands:
            close = merged and band[0] - merged[-1][1] < 0.35 * pitch
            if close and (sliver(band) or sliver(merged[-1])):
                merged[-1][1] = band[1]
            else:
                merged.append(band)
        bands = merged

    return [(t, b) for t, b in bands if b - t + 1 >= MIN_LINE_HEIGHT * h]


def segment_lines(page: Image.Image) -> list[Image.Image]:
    """Crop a page image into text-line images (lighting flattened), top to bottom."""
    flat = flatten_lighting(page)
    mask = text_mask(flat)
    h, w = mask.shape
    flat_img = Image.fromarray(flat.astype(np.uint8))
    pad_y, pad_x = int(PAD * h), int(PAD * w)
    lines = []
    for top, bottom in line_bands(mask):
        cols = np.flatnonzero(mask[top : bottom + 1].any(axis=0))
        box = (max(0, cols[0] - pad_x), max(0, top - pad_y), min(w, cols[-1] + pad_x + 1), min(h, bottom + pad_y + 1))
        lines.append(flat_img.crop(box))
    return lines


def is_degenerate(text: str) -> bool:
    """TrOCR sometimes loops on noise ("000 000 000 ...") with high confidence; such lines are dropped."""
    words = text.split()
    if len(words) < 6:
        return False
    most_common = max(words.count(word) for word in set(words))
    return most_common / len(words) > 0.5


@lru_cache
def _load(model_name: str):
    try:
        from transformers import (
            AutoImageProcessor,
            AutoTokenizer,
            TrOCRProcessor,
            VisionEncoderDecoderModel,
            XLMRobertaTokenizer,
        )

        try:
            tokenizer = AutoTokenizer.from_pretrained(model_name)
        except ValueError:
            # transformers 5 cannot auto-build trocr-small's legacy SentencePiece
            # tokenizer config, but the named class loads it fine.
            tokenizer = XLMRobertaTokenizer.from_pretrained(model_name)
        processor = TrOCRProcessor(image_processor=AutoImageProcessor.from_pretrained(model_name), tokenizer=tokenizer)
        model = VisionEncoderDecoderModel.from_pretrained(model_name)
    # OSError: not downloaded / no internet. ValueError, ImportError: a tokenizer dependency
    # (e.g. sentencepiece for trocr-small) is missing.
    except (OSError, ValueError, ImportError) as e:
        raise HTRUnavailableError(f"Could not load HTR model {model_name!r}: {e}") from e
    model.eval()
    return processor, model


def recognize_lines(lines: list[Image.Image]) -> list[tuple[str, float]]:
    """Run TrOCR on line images. Returns (text, confidence) per line."""
    import torch  # imported lazily: torch is slow to import and only this path needs it

    processor, model = _load(settings.htr_model)
    pad_id = model.generation_config.pad_token_id
    results: list[tuple[str, float]] = []
    for i in range(0, len(lines), BATCH_SIZE):
        batch = [img.convert("RGB") for img in lines[i : i + BATCH_SIZE]]
        pixel_values = processor(images=batch, return_tensors="pt").pixel_values
        with torch.no_grad():
            out = model.generate(
                pixel_values,
                max_new_tokens=MAX_LINE_TOKENS,
                num_beams=1,
                output_scores=True,
                return_dict_in_generate=True,
            )
        logprobs = model.compute_transition_scores(out.sequences, out.scores, normalize_logits=True)
        generated = out.sequences[:, 1:]  # drop the decoder start token
        texts = processor.batch_decode(out.sequences, skip_special_tokens=True)
        for text, lp, tokens in zip(texts, logprobs, generated):
            # Ignore padding after EOS in shorter sequences.
            real = tokens != pad_id if pad_id is not None else torch.ones_like(tokens, dtype=torch.bool)
            conf = math.exp(lp[real].mean().item()) if real.any() else 0.0
            results.append((text.strip(), conf))
    return results


def htr_image(page: Image.Image) -> tuple[str, float]:
    """HTR one page image. Returns (text, raw_conf); a page with no lines gives ("", 0.0)."""
    recognized = [(t, c) for t, c in recognize_lines(segment_lines(denoise(page))) if t and not is_degenerate(t)]
    chars = sum(len(t) for t, _ in recognized)
    if not chars:
        return "", 0.0
    return "\n".join(t for t, _ in recognized), sum(c * len(t) for t, c in recognized) / chars


def htr_file(file_path: str, max_pages: int | None = None) -> list[tuple[str, float]]:
    """Return (page_text, raw_conf) for each page of a PDF or image (or the first max_pages)."""
    # closing(): release the PDF immediately if HTR fails (see ocr_extractor.ocr_file).
    with closing(render_pages(file_path, HTR_DPI, max_pages)) as pages:
        # Orientation uses Tesseract OSD; it degrades to a no-op if Tesseract is missing.
        return [htr_image(ocr_extractor.auto_orient(img)) for img in pages]
