"""Module 2 — HTR path with PaddleOCR models (default handwriting engine).

Responsibility: read handwritten pages with PaddleOCR's PP-OCRv6 detection +
recognition models, run through RapidOCR on ONNX Runtime. Unlike TrOCR, the
detector finds every text line by itself, so ruled notebook paper, margins,
and uneven lighting need no hand-written segmentation. It needs no
PaddlePaddle framework or PyTorch, and reads a page in ~3 s on CPU.

Returns page text (lines in reading order) plus raw_conf for Module 3: the
recogniser's line scores averaged by line length. Each line's box and score
can also be collected for the document viewer.

Uses from schemas.py: nothing directly; output feeds chunker.py -> RecognizedChunk.
"""

from contextlib import closing
from functools import lru_cache

import numpy as np
from PIL import Image

from app.config import settings
from app.modules import ocr_extractor
from app.modules.htr_extractor import HTR_DPI, HTRUnavailableError
from app.modules.pdf_render import render_pages

# Boxes whose vertical centres are closer than this share of the typical box
# height belong to the same text line (the detector may split one line in pieces).
SAME_LINE = 0.5


class PaddleUnavailableError(HTRUnavailableError):
    """RapidOCR / ONNX Runtime could not be loaded."""


@lru_cache
def _engine(threads: int):
    try:
        from rapidocr import EngineType, ModelType, OCRVersion, RapidOCR
    except ImportError as e:
        raise PaddleUnavailableError(f"PaddleOCR engine not installed (pip install rapidocr): {e}") from e
    return RapidOCR(
        params={
            "Global.use_cls": False,  # orientation is handled by ocr_extractor.auto_orient
            "EngineConfig.onnxruntime.intra_op_num_threads": threads,
            "Det.engine_type": EngineType.ONNXRUNTIME,
            "Rec.engine_type": EngineType.ONNXRUNTIME,
            "Det.ocr_version": OCRVersion.PPOCRV6,
            "Rec.ocr_version": OCRVersion.PPOCRV6,
            "Det.model_type": ModelType.SMALL,
            "Rec.model_type": ModelType.SMALL,
        }
    )


def _group_lines(boxes: list[tuple[float, float, float, float, str, float]]) -> list[list[tuple]]:
    """Group (x0, y0, x1, y1, text, score) boxes into text lines, top to bottom, left to right."""
    if not boxes:
        return []
    typical = float(np.median([b[3] - b[1] for b in boxes]))
    lines: list[list[tuple]] = []
    for box in sorted(boxes, key=lambda b: (b[1] + b[3]) / 2):
        centre = (box[1] + box[3]) / 2
        if lines and abs(centre - np.mean([(b[1] + b[3]) / 2 for b in lines[-1]])) < SAME_LINE * typical:
            lines[-1].append(box)
        else:
            lines.append([box])
    return [sorted(line, key=lambda b: b[0]) for line in lines]


def read_image(page: Image.Image, lines_out: list | None = None) -> tuple[str, float]:
    """Read one page image. Returns (text, raw_conf); nothing found gives ("", 0.0).

    If lines_out is a list, one {"text", "conf", "box"} dict per line is appended,
    box = [x0, y0, x1, y1] as fractions of the page size.
    """
    result = _engine(settings.ocr_threads)(np.array(page.convert("RGB")))
    if not result.txts:
        return "", 0.0
    boxes = [
        (float(q[:, 0].min()), float(q[:, 1].min()), float(q[:, 0].max()), float(q[:, 1].max()), text.strip(), float(score))
        for q, text, score in zip(result.boxes, result.txts, result.scores)
        if text.strip()
    ]
    lines = _group_lines(boxes)
    texts, weighted, chars = [], 0.0, 0
    w, h = page.size
    for line in lines:
        text = " ".join(b[4] for b in line)
        line_chars = sum(len(b[4]) for b in line)
        conf = sum(b[5] * len(b[4]) for b in line) / line_chars
        texts.append(text)
        weighted += conf * line_chars
        chars += line_chars
        if lines_out is not None:
            box = [min(b[0] for b in line) / w, min(b[1] for b in line) / h, max(b[2] for b in line) / w, max(b[3] for b in line) / h]
            lines_out.append({"text": text, "conf": round(conf, 4), "box": [round(v, 5) for v in box]})
    return "\n".join(texts), (weighted / chars if chars else 0.0)


def paddle_file(file_path: str, max_pages: int | None = None, layout: list | None = None) -> list[tuple[str, float]]:
    """Return (page_text, raw_conf) for each page of a PDF or image (or the first max_pages).

    If layout is a list, one {"image", "lines"} record per page is appended for the viewer.
    """
    results = []
    with closing(render_pages(file_path, HTR_DPI, max_pages)) as pages:
        for img in pages:
            img = ocr_extractor.auto_orient(img)
            lines: list | None = [] if layout is not None else None
            results.append(read_image(img, lines) if lines is not None else read_image(img))
            if layout is not None:
                layout.append({"image": img, "lines": lines})
    return results
