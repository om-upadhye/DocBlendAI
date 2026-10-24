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

import math
import re
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
# Columns (a two-page spread, a two-column page): a vertical strip crossed by at most this share
# of the text pieces on either side of it separates columns, each read top to bottom in turn.
COLUMN_VALLEY = 0.25
MIN_COLUMN_BOXES = 4  # fewer pieces than this on one side is a stray word, not a column
# A tilted photo (slope of its long text pieces above this) is straightened before columns and
# lines are found; only the piece positions are turned, the image is not read again.
DESKEW_MIN_SLOPE = 0.02  # about 1 degree
LONG_PIECE = 3  # pieces narrower than this many line heights give an unreliable slope
# The detector misses or merges lines in very wide or tall images (a one-line strip, a cropped
# heading), so those are padded with white paper to this short:long side ratio first.
MAX_ASPECT = 2.0
PAD_RATIO = 0.75
# The recogniser knows Chinese and Japanese; on Latin-script notes it turns scribbles and stamps
# into stray CJK characters, which are dropped when they are this small a share of the page.
CJK = re.compile("[\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]")
MAX_STRAY_CJK = 0.1
# Orientation check (see orientation_score): pieces read at least this confidently count.
ORIENT_MIN_SCORE = 0.8


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
            "Rec.model_type": ModelType(settings.ocr_rec_model),
            # Longest image side the detector works on. 1600 reads A4 pages the same as the
            # default 2000 but needs ~100 MB less memory: it keeps the server within 512 MB.
            "Global.max_side_len": settings.ocr_max_side,
        }
    )


def _split_columns(boxes: list[tuple[float, float, float, float, str, float]]) -> list[list[tuple]]:
    """Split text pieces into columns, left to right, at a deep vertical gap in the text.

    A photo of an open notebook holds two pages side by side; grouping pieces by height
    alone would join each left-page line to the right-page line beside it. The split is
    the emptiest vertical strip in the middle of the text, kept only if far fewer pieces
    cross it than cover the text on each side (a slanted page or a long line may cross
    the spine, so it need not be empty). A piece crossing it goes to the side holding
    its centre. Each column is split again, so three columns work too.
    """
    if len(boxes) < 2 * MIN_COLUMN_BOXES:
        return [boxes]
    left_edge = int(min(b[0] for b in boxes))
    cover = np.zeros(int(max(b[2] for b in boxes)) - left_edge + 1, dtype=int)
    for b in boxes:
        cover[int(b[0]) - left_edge : int(b[2]) - left_edge + 1] += 1
    lo, hi = len(cover) // 5, 4 * len(cover) // 5
    if hi <= lo:
        return [boxes]
    gap = lo + int(np.argmin(cover[lo:hi]))
    left = [b for b in boxes if (b[0] + b[2]) / 2 < left_edge + gap]
    right = [b for b in boxes if (b[0] + b[2]) / 2 >= left_edge + gap]
    if min(len(left), len(right)) < MIN_COLUMN_BOXES:
        return [boxes]
    sides = (cover[:gap], cover[gap:])
    if cover[gap] > COLUMN_VALLEY * min(float(np.median(side[side > 0])) for side in sides):
        return [boxes]
    return _split_columns(left) + _split_columns(right)


def _quad_shape(q: np.ndarray) -> tuple[float, float]:
    """(slope, height) of a detected text quad: points run top-left, top-right, bottom-right, bottom-left."""
    dx, dy = q[1] - q[0]
    slope = float(dy / dx) if dx > 0 else 0.0
    return slope, float(np.hypot(*(q[3] - q[0])))


def _group_lines(boxes: list[tuple]) -> list[list[tuple]]:
    """Group (x0, y0, x1, y1, text, score[, slope, height]) boxes into text lines, top to bottom, left to right.

    A photographed page is often tilted, so its lines slope: pieces are compared by their
    height measured along the column's slope, and by their own heights rather than their
    upright bounding boxes, which a sloping piece makes too tall. The slope is the median
    of the long pieces' own slopes (a short word's angle is unreliable). Boxes without
    slope and height are treated as level.
    """
    if not boxes:
        return []
    detailed = len(boxes[0]) > 7
    height = (lambda b: b[7]) if detailed else (lambda b: b[3] - b[1])
    typical = float(np.median([height(b) for b in boxes]))
    long = [b[6] for b in boxes if detailed and b[2] - b[0] > 3 * typical]
    slope = float(np.median(long)) if long else 0.0

    def level(b: tuple) -> float:  # vertical centre with the slope taken out
        return (b[1] + b[3]) / 2 - slope * (b[0] + b[2]) / 2

    lines: list[list[tuple]] = []
    for box in sorted(boxes, key=level):
        if lines and abs(level(box) - np.mean([level(b) for b in lines[-1]])) < SAME_LINE * typical:
            lines[-1].append(box)
        else:
            lines.append([box])
    return [sorted(line, key=lambda b: b[0]) for line in lines]


def _padded(page: Image.Image) -> Image.Image:
    """The page with white paper added below or to the right if it is very wide or tall (see MAX_ASPECT)."""
    w, h = page.size
    if max(w, h) <= MAX_ASPECT * min(w, h):
        return page
    size = (w, max(h, int(w * PAD_RATIO))) if w > h else (max(w, int(h * PAD_RATIO)), h)
    canvas = Image.new(page.mode, size, 255 if page.mode == "L" else "white")
    canvas.paste(page, (0, 0))
    return canvas


def _pieces(result) -> list[tuple]:
    """Detected pieces as (x0, y0, x1, y1, text, score, slope, height, page_box) for grouping into lines.

    page_box is the piece's box on the page. The other coordinates are the piece turned with
    the whole page level when the photo is tilted (see DESKEW_MIN_SLOPE): on a tilted
    two-page photo the gap between the pages runs at an angle and columns are not found.
    """
    quads = [np.asarray(q, dtype=float) for q in result.boxes]
    shapes = [_quad_shape(q) for q in quads]
    typical = float(np.median([height for _, height in shapes]))
    long = [slope for (slope, _), q in zip(shapes, quads) if np.ptp(q[:, 0]) > LONG_PIECE * typical]
    slope = float(np.median(long)) if long else 0.0
    turn = None
    if abs(slope) > DESKEW_MIN_SLOPE:
        a = -math.atan(slope)
        turn = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])

    texts = [text.strip() for text in result.txts]
    total = sum(len(t) for t in texts)
    stray_cjk = total and sum(len(CJK.findall(t)) for t in texts) <= MAX_STRAY_CJK * total
    pieces = []
    for q, text, score in zip(quads, texts, result.scores):
        if stray_cjk:
            text = " ".join(CJK.sub(" ", text).split())
        if not text:
            continue
        page_box = (float(q[:, 0].min()), float(q[:, 1].min()), float(q[:, 0].max()), float(q[:, 1].max()))
        r = q @ turn.T if turn is not None else q
        pieces.append((float(r[:, 0].min()), float(r[:, 1].min()), float(r[:, 0].max()), float(r[:, 1].max()), text, float(score), *_quad_shape(r), page_box))
    return pieces


def orientation_score(page: Image.Image) -> float:
    """How well a page reads this way up: characters in confidently read pieces (for ocr_extractor.auto_orient).

    Upside-down or sideways handwriting yields few confident pieces, while Tesseract's
    confidence cannot tell (see auto_orient).
    """
    small = page.reduce(2) if max(page.size) > 1600 else page
    result = _engine(settings.ocr_threads)(np.array(_padded(small).convert("RGB")))
    if not result.txts:
        return 0.0
    return float(sum(len(t.strip()) for t, s in zip(result.txts, result.scores) if s >= ORIENT_MIN_SCORE))


def read_image(page: Image.Image, lines_out: list | None = None, columns: bool = True) -> tuple[str, float]:
    """Read one page image. Returns (text, raw_conf); nothing found gives ("", 0.0).

    Text in side-by-side columns (e.g. two notebook pages in one photo) is read column by
    column; columns=False reads straight across, as a table's rows must be.

    If lines_out is a list, one {"text", "conf", "box", "words"} dict per line is appended,
    box = [x0, y0, x1, y1] as fractions of the page size; words are the detected text pieces
    of the line, each with its own text, conf and box.
    """
    result = _engine(settings.ocr_threads)(np.array(_padded(page).convert("RGB")))
    if not result.txts:
        return "", 0.0
    boxes = _pieces(result)
    lines = [(k, line) for k, column in enumerate(_split_columns(boxes) if columns else [boxes]) for line in _group_lines(column)]
    texts, weighted, chars = [], 0.0, 0
    w, h = page.size

    def frac(box: tuple) -> list[float]:  # page box as page fractions (padding lies beyond 1.0)
        return [round(min(box[0] / w, 1.0), 5), round(min(box[1] / h, 1.0), 5), round(min(box[2] / w, 1.0), 5), round(min(box[3] / h, 1.0), 5)]

    for column, line in lines:
        text = " ".join(b[4] for b in line)
        line_chars = sum(len(b[4]) for b in line)
        conf = sum(b[5] * len(b[4]) for b in line) / line_chars
        texts.append(text)
        weighted += conf * line_chars
        chars += line_chars
        if lines_out is not None:
            on_page = [b[8] for b in line]
            box = (min(b[0] for b in on_page), min(b[1] for b in on_page), max(b[2] for b in on_page), max(b[3] for b in on_page))
            # Each detected text piece too: table cells and spacing (layout_analysis.py) need them.
            words = [{"text": b[4], "conf": round(b[5], 4), "box": frac(b[8])} for b in line]
            # column: which side-by-side column (page) the line is in, for layout_analysis's reading order.
            lines_out.append({"text": text, "conf": round(conf, 4), "box": frac(box), "words": words, "column": column})
    return "\n".join(texts), (weighted / chars if chars else 0.0)


def paddle_file(file_path: str, max_pages: int | None = None, layout: list | None = None) -> list[tuple[str, float]]:
    """Return (page_text, raw_conf) for each page of a PDF or image (or the first max_pages).

    If layout is a list, one {"image", "lines"} record per page is appended for the viewer.
    """
    results = []
    with closing(render_pages(file_path, HTR_DPI, max_pages)) as pages:
        for img in pages:
            img = ocr_extractor.auto_orient(img, orientation_score)
            lines: list | None = [] if layout is not None else None
            results.append(read_image(img, lines) if lines is not None else read_image(img))
            if layout is not None:
                layout.append({"image": img, "lines": lines})
    return results
