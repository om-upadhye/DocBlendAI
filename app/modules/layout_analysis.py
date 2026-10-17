"""Supports Modules 2 and 4 — layout analysis of scanned and handwritten pages.

Responsibility: find what each part of a page is, rebuild tables, and keep the page's spacing:
- regions: a layout model (PP layout family, ONNX via rapid-layout) boxes titles, text, tables,
  figures, captions, formulas, headers, and footers. Each recognised line is assigned to the
  region it sits in; lines no region covers are grouped by position (large lines become titles).
- tables: SLANet-plus (ONNX via rapid-table, the table model PP-StructureV3 uses) predicts the
  table's row/cell structure, and the words OCR already read are matched into its cells. If the
  model is unavailable, rows and cells come from the alignment of the words.
- reading order: headers first, footers last; full-width regions split the page into bands,
  and inside a band the left column is read before the right one.
- layout text: the page as monospace text, each line at its row with indentation and column
  gaps kept (the "spacing kept" export).

The page text used for answering is rebuilt from the regions in reading order, with table rows
written as cells separated by two spaces (the shape content_type.py recognises as a table), so
multi-column pages read correctly and tables become their own chunks.

Region: {"type", "box": [x0, y0, x1, y1] as page fractions, "text", "conf",
         "rows": [[cell, ...], ...] (tables only)}

Uses from schemas.py: ContentType.
"""

import logging
import re
import threading
from functools import lru_cache
from html.parser import HTMLParser

import numpy as np
from PIL import Image

from app.config import settings
from app.models.schemas import ContentType

logger = logging.getLogger(__name__)

TYPES = ("title", "text", "table", "figure", "caption", "formula", "header", "footer", "reference")

# Layout model class names (pp_layout_* and PP-DocLayout families) -> our region types.
_CLASS_MAP = {
    "title": "title", "doc_title": "title", "paragraph_title": "title",
    "text": "text", "abstract": "text", "content": "text", "algorithm": "text", "aside_text": "text",
    "reference_content": "text", "list": "text",
    "table": "table",
    "figure": "figure", "image": "figure", "chart": "figure", "seal": "figure",
    "figure_caption": "caption", "table_caption": "caption", "figure_title": "caption",
    "chart_title": "caption", "table_title": "caption", "caption": "caption",
    "equation": "formula", "formula": "formula", "formula_number": "formula",
    "header": "header", "header_image": "header",
    "footer": "footer", "footer_image": "footer", "number": "footer", "footnote": "footer",
    "vision_footnote": "footer",
    "reference": "reference",
}
# When two detections cover the same area, the more specific type wins.
_PRIORITY = {t: i for i, t in enumerate(["table", "figure", "formula", "caption", "title", "header", "footer", "reference", "text"])}

# Content type each region contributes to answering (Module 4).
CONTENT_TYPE = {"table": ContentType.TABLE, "figure": ContentType.IMAGE, "caption": ContentType.IMAGE}

SAME_AREA = 0.8  # share of the smaller box two detections must share to count as duplicates
TITLE_HEIGHT = 1.25  # a short block whose lines are this much taller than body text is a title
FULL_WIDTH = 0.55  # regions wider than this share of the page split it into reading bands
CELL_SEPARATOR = "  "  # same as text_parser.CELL_SEPARATOR
COLUMN_GAP_CHARS = 2.5  # a gap wider than this many characters is a column gap, not a space
MAX_BLANK_ROWS = 2
LAYOUT_INPUT_SIDE = 1024  # page side given to the layout model (it resizes to ~800 px itself)


class LayoutUnavailableError(RuntimeError):
    """The layout model could not be loaded (package or model file missing)."""


# ---------------------------------------------------------------------------------------------
# Models (loaded once, on first use)

_lock = threading.Lock()


@lru_cache
def _layout_engine(model_type: str):
    try:
        from rapid_layout import RapidLayout
    except ImportError as e:
        raise LayoutUnavailableError("rapid-layout is not installed (see requirements.txt)") from e
    return RapidLayout(model_type=model_type, conf_thresh=settings.layout_min_score)


@lru_cache
def _table_engine(model_type: str):
    """SLANet(-plus) structure model + cell matcher, without rapid-table's own OCR engine."""
    try:
        from rapid_table import ModelType, RapidTable, RapidTableInput
    except ImportError as e:
        raise LayoutUnavailableError("rapid-table is not installed (see requirements.txt)") from e
    return RapidTable(RapidTableInput(model_type=ModelType(model_type), use_ocr=False))


def detect(image: Image.Image) -> list[dict]:
    """Layout detections: [{"type", "box" (page fractions), "score"}]. Raises LayoutUnavailableError."""
    # The layout models work at ~800 px, so a 1024 px copy gives the same boxes (they come back as
    # page fractions) and saves ~100 MB on a full-size page.
    small = image.convert("RGB")
    small.thumbnail((LAYOUT_INPUT_SIDE, LAYOUT_INPUT_SIDE))
    rgb = np.array(small)
    with _lock:  # one ONNX session shared by upload threads
        result = _layout_engine(settings.layout_model)(rgb)
    h, w = rgb.shape[:2]
    found = []
    for box, name, score in zip(result.boxes or [], result.class_names or [], result.scores or []):
        x0, y0, x1, y1 = (float(v) for v in box)
        found.append({
            "type": _CLASS_MAP.get(str(name).lower(), "text"),
            "box": [max(0.0, x0 / w), max(0.0, y0 / h), min(1.0, x1 / w), min(1.0, y1 / h)],
            "score": float(score),
        })
    return found


# ---------------------------------------------------------------------------------------------
# Geometry helpers (boxes are [x0, y0, x1, y1] fractions)


def _area(b: list[float]) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _overlap(a: list[float], b: list[float]) -> float:
    return _area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def _union(boxes: list[list[float]]) -> list[float]:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _centre(b: list[float]) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def _median(values: list[float], default: float) -> float:
    values = sorted(v for v in values if v > 0)
    return values[(len(values) - 1) // 2] if values else default  # lower median: a few tall lines never set it


def dedupe(detections: list[dict]) -> list[dict]:
    """Drop detections that cover the same area as a better one (more specific type, then higher score)."""
    ranked = sorted(detections, key=lambda d: (_PRIORITY.get(d["type"], 99), -d["score"]))
    kept: list[dict] = []
    for det in ranked:
        if _area(det["box"]) <= 0:
            continue
        if any(_overlap(det["box"], k["box"]) >= SAME_AREA * min(_area(det["box"]), _area(k["box"])) for k in kept):
            continue
        kept.append(det)
    return kept


# ---------------------------------------------------------------------------------------------
# Lines -> regions


def _region_of(line: dict, regions: list[dict]) -> int | None:
    """Index of the region holding the line's centre (the smallest if several), else the best overlap."""
    cx, cy = _centre(line["box"])
    inside = [i for i, r in enumerate(regions) if r["box"][0] <= cx <= r["box"][2] and r["box"][1] <= cy <= r["box"][3]]
    if inside:
        return min(inside, key=lambda i: _area(regions[i]["box"]))
    best, best_share = None, 0.0
    for i, r in enumerate(regions):
        share = _overlap(line["box"], r["box"]) / max(_area(line["box"]), 1e-9)
        if share > best_share:
            best, best_share = i, share
    return best if best_share >= 0.5 else None


def _group_loose_lines(lines: list[dict], line_h: float) -> list[dict]:
    """Regions for lines no detection covers: neighbouring lines form a block; tall ones are titles."""
    groups: list[list[dict]] = []
    for line in sorted(lines, key=lambda l: l["box"][1]):
        if groups:
            last = groups[-1][-1]
            close = line["box"][1] - last["box"][3] < 1.2 * line_h
            same_column = min(line["box"][2], last["box"][2]) - max(line["box"][0], last["box"][0]) > 0
            same_size = abs((line["box"][3] - line["box"][1]) - (last["box"][3] - last["box"][1])) < 0.5 * line_h
            if close and same_column and same_size:
                groups[-1].append(line)
                continue
        groups.append([line])
    return [
        {"type": "title" if _is_title(group, line_h) else "text", "box": _union([l["box"] for l in group]), "score": 0.0, "lines": group}
        for group in groups
    ]


def _is_title(lines: list[dict], line_h: float) -> bool:
    """One to three lines clearly taller than body text."""
    if not 1 <= len(lines) <= 3:
        return False
    return _median([l["box"][3] - l["box"][1] for l in lines], line_h) >= TITLE_HEIGHT * line_h


def _lines_text(lines: list[dict]) -> str:
    return "\n".join(l["text"] for l in sorted(lines, key=lambda l: (round(_centre(l["box"])[1], 3), l["box"][0])))


def _conf(lines: list[dict]) -> float:
    chars = sum(len(l["text"]) for l in lines)
    return round(sum(l.get("conf", 1.0) * len(l["text"]) for l in lines) / chars, 4) if chars else 0.0


def reading_order(regions: list[dict]) -> list[dict]:
    """Headers, then bands top to bottom (full-width regions split bands; left column first), then footers."""
    headers = sorted((r for r in regions if r["type"] == "header"), key=lambda r: (r["box"][1], r["box"][0]))
    footers = sorted((r for r in regions if r["type"] == "footer"), key=lambda r: (r["box"][1], r["box"][0]))
    body = sorted((r for r in regions if r["type"] not in ("header", "footer")), key=lambda r: r["box"][1])
    ordered: list[dict] = []
    band: list[dict] = []

    def flush() -> None:
        band.sort(key=lambda r: (0 if _centre(r["box"])[0] < 0.5 else 1, r["box"][1]))
        ordered.extend(band)
        band.clear()

    for region in body:
        if region["box"][2] - region["box"][0] > FULL_WIDTH:
            flush()
            ordered.append(region)
        else:
            band.append(region)
    flush()
    return headers + ordered + footers


# ---------------------------------------------------------------------------------------------
# Tables


class _TableParser(HTMLParser):
    """HTML table -> rows of cell text; cells covered by a colspan or rowspan are empty strings."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._colspan = self._rowspan = 1
        self._covered: dict[int, int] = {}  # column -> rows still covered by a rowspan from above
        self._this_row: set[int] = set()

    @staticmethod
    def _span(attrs: list[tuple[str, str | None]], name: str) -> int:
        value = dict(attrs).get(name) or "1"
        return max(1, int(value)) if value.isdigit() else 1

    def _skip_covered(self) -> None:
        while self._row is not None and len(self._row) in self._this_row:
            self._row.append("")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
            self._this_row = {c for c, n in self._covered.items() if n > 0}
        elif tag in ("td", "th"):
            self._cell = []
            self._colspan, self._rowspan = self._span(attrs, "colspan"), self._span(attrs, "rowspan")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._skip_covered()
            start = len(self._row)
            self._row.append(" ".join("".join(self._cell).split()))
            self._row.extend([""] * (self._colspan - 1))
            if self._rowspan > 1:
                for c in range(start, start + self._colspan):
                    self._covered[c] = self._rowspan  # decremented once at the end of this row
            self._cell = None
        elif tag == "tr" and self._row is not None:
            while self._this_row and len(self._row) <= max(self._this_row):
                self._skip_covered()
                if len(self._row) <= max(self._this_row) and len(self._row) not in self._this_row:
                    break
            self._covered = {c: n - 1 for c, n in self._covered.items() if n - 1 > 0}
            if any(cell for cell in self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def parse_table_html(html: str) -> list[list[str]]:
    parser = _TableParser()
    parser.feed(html)
    parser.close()
    return parser.rows


def _pieces(line: dict) -> list[dict]:
    """The line's words when they still spell the line, else the whole line as one piece."""
    words = [w for w in line.get("words") or [] if w.get("box") and w.get("text")]
    if words and "".join(w["text"] for w in words).replace(" ", "") == line["text"].replace(" ", ""):
        return words
    return [{"text": line["text"], "box": line["box"], "conf": line.get("conf", 1.0)}]


def rows_from_alignment(lines: list[dict]) -> list[list[str]]:
    """Fallback table: one row per line, cells split where words are far apart."""
    rows = []
    for line in sorted(lines, key=lambda l: _centre(l["box"])[1]):
        pieces = sorted(_pieces(line), key=lambda p: p["box"][0])
        if len(pieces) == 1:
            cells = [c for c in re.split(r"\s{2,}|\t|\|", pieces[0]["text"]) if c.strip()]
        else:
            char_w = (line["box"][2] - line["box"][0]) / max(1, len(line["text"]))
            cells, current, prev_x1 = [], [], None
            for p in pieces:
                if prev_x1 is not None and p["box"][0] - prev_x1 > COLUMN_GAP_CHARS * char_w:
                    cells.append(" ".join(current))
                    current = []
                current.append(p["text"])
                prev_x1 = p["box"][2]
            cells.append(" ".join(current))
        if cells:
            rows.append([c.strip() for c in cells])
    return rows


def _rule_positions(mask: np.ndarray, axis: int, min_len: int) -> list[int]:
    """Centres of drawn rules: rows (axis=1) or columns (axis=0) holding a long enough line."""
    counts = (mask > 0).sum(axis=axis)
    hits = np.where(counts >= min_len)[0]
    positions, start = [], None
    for i, v in enumerate(hits):
        if start is None:
            start = v
        if i + 1 == len(hits) or hits[i + 1] > v + 2:  # end of a run of neighbouring pixel rows/columns
            positions.append(int((start + v) // 2))
            start = None
    return positions


def grid_rows(image: Image.Image, box: list[float], lines: list[dict]) -> list[list[str]] | None:
    """Rows of a ruled table from its drawn lines, or None if the table has no full grid.

    Horizontal and vertical rules give the grid; two neighbouring grid cells with no rule
    between them are one merged cell (colspan / rowspan). Each word goes to the cell holding
    its centre, so a cell spanning several lines keeps all of them. A merged cell's text is
    written in its top-left position; the cells it covers stay empty.
    """
    import cv2

    w, h = image.size
    x0, y0 = int(max(0.0, box[0] - 0.01) * w), int(max(0.0, box[1] - 0.01) * h)
    x1, y1 = int(min(1.0, box[2] + 0.01) * w), int(min(1.0, box[3] + 0.01) * h)
    gray = np.array(image.crop((x0, y0, x1, y1)).convert("L"))
    ch, cw = gray.shape
    if ch < 20 or cw < 20:
        return None
    ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 10)
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, cw // 25), 1)))
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, ch // 25))))
    # Real rules run across most of the table (merged cells only cut them short); stacked letters
    # (e.g. the stems of first letters in a column) add up to far less.
    ys = _rule_positions(horizontal, 1, max(15, int(0.3 * cw)))
    xs = _rule_positions(vertical, 0, max(15, int(0.5 * ch)))
    if len(ys) < 3 or len(xs) < 3:
        return None  # not a ruled table (or only its outline): let the structure model decide

    rows_n, cols_n = len(ys) - 1, len(xs) - 1
    band = 3  # pixels either side of a rule's centre

    def has_vertical(c: int, r: int) -> bool:  # rule at xs[c] between rows ys[r]..ys[r+1]
        top, bottom = ys[r] + band, ys[r + 1] - band
        if bottom <= top:
            return True
        strip = vertical[top:bottom, max(0, xs[c] - band):xs[c] + band + 1]
        return (strip.max(axis=1) > 0).mean() > 0.6 if strip.size else True

    def has_horizontal(r: int, c: int) -> bool:  # rule at ys[r] between columns xs[c]..xs[c+1]
        left, right = xs[c] + band, xs[c + 1] - band
        if right <= left:
            return True
        strip = horizontal[max(0, ys[r] - band):ys[r] + band + 1, left:right]
        return (strip.max(axis=0) > 0).mean() > 0.6 if strip.size else True

    parent = list(range(rows_n * cols_n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for r in range(rows_n):
        for c in range(cols_n):
            if c + 1 < cols_n and not has_vertical(c + 1, r):
                parent[find(r * cols_n + c + 1)] = find(r * cols_n + c)
            if r + 1 < rows_n and not has_horizontal(r + 1, c):
                parent[find((r + 1) * cols_n + c)] = find(r * cols_n + c)

    # Words into cells by their centre (crop pixel coordinates).
    texts: dict[int, list[tuple[float, float, str]]] = {}
    for line in lines:
        for piece in _pieces(line):
            cx = ((piece["box"][0] + piece["box"][2]) / 2) * w - x0
            cy = ((piece["box"][1] + piece["box"][3]) / 2) * h - y0
            c = next((i for i in range(cols_n) if xs[i] <= cx < xs[i + 1]), None)
            r = next((i for i in range(rows_n) if ys[i] <= cy < ys[i + 1]), None)
            if r is not None and c is not None:
                texts.setdefault(find(r * cols_n + c), []).append((cy, cx, piece["text"]))

    first: dict[int, int] = {}  # merged cell -> its top-left grid position
    for i in range(rows_n * cols_n):
        first.setdefault(find(i), i)
    rows = []
    for r in range(rows_n):
        row = []
        for c in range(cols_n):
            root = find(r * cols_n + c)
            if first[root] != r * cols_n + c:
                row.append("")
                continue
            parts = sorted(texts.get(root, []))
            row.append(" ".join(text for _, _, text in parts))
        rows.append(row)
    rows = [row for row in rows if any(row)]
    filled = sum(bool(cell) for row in rows for cell in row)
    placed = sum(len(v) for v in texts.values())
    pieces = sum(len(_pieces(l)) for l in lines)
    if not rows or filled < 2 or placed < 0.8 * pieces:
        return None  # the grid does not hold the words: not a real ruled table
    return rows


def table_rows(image: Image.Image, box: list[float], lines: list[dict]) -> list[list[str]]:
    """Rows and cells of the table in box.

    Ruled tables: from their drawn grid (exact cells, merged cells, multi-line cells).
    Otherwise SLANet-plus structure + the OCR words; word alignment as the last fallback.
    """
    if not lines:
        return []
    try:
        rows = grid_rows(image, box, lines)
        if rows:
            return rows
    except Exception:
        logger.exception("Reading the table grid failed; trying the structure model")
    if settings.table_model:
        try:
            return _model_rows(image, box, lines) or rows_from_alignment(lines)
        except LayoutUnavailableError as e:
            logger.warning("Table structure model unavailable (%s); using word alignment", e)
        except Exception:  # never fail an upload over table structure
            logger.exception("Table structure recognition failed; using word alignment")
    return rows_from_alignment(lines)


def _model_rows(image: Image.Image, box: list[float], lines: list[dict]) -> list[list[str]]:
    from rapid_table.utils import format_ocr_results

    w, h = image.size
    pad = 0.005
    x0, y0 = int(max(0.0, box[0] - pad) * w), int(max(0.0, box[1] - pad) * h)
    x1, y1 = int(min(1.0, box[2] + pad) * w), int(min(1.0, box[3] + pad) * h)
    crop = np.array(image.crop((x0, y0, x1, y1)).convert("RGB"))  # crop first: only the table in colour
    quads, texts, scores = [], [], []
    for line in lines:
        for p in _pieces(line):
            a = [p["box"][0] * w - x0, p["box"][1] * h - y0, p["box"][2] * w - x0, p["box"][3] * h - y0]
            quads.append([[a[0], a[1]], [a[2], a[1]], [a[2], a[3]], [a[0], a[3]]])
            texts.append(p["text"])
            scores.append(float(p.get("conf", 1.0)))
    if not quads:
        return []
    engine = _table_engine(settings.table_model)
    with _lock:
        structures, cell_boxes = engine.table_structure([crop])
    dt_boxes, rec_res = format_ocr_results((np.array(quads, dtype=np.float32), tuple(texts), tuple(scores)), *crop.shape[:2])
    html = engine.table_matcher(structures, cell_boxes, [dt_boxes], [rec_res])[0]
    return parse_table_html(html)


def read_region(image: Image.Image, box: list[float]) -> list[dict]:
    """Lines read inside one region with the PaddleOCR engine, boxes as page fractions.

    Tesseract often reads nothing inside ruled table cells; Paddle's detector finds them.
    """
    from app.modules import paddle_extractor

    w, h = image.size
    x0, y0 = int(box[0] * w), int(box[1] * h)
    x1, y1 = max(x0 + 1, int(box[2] * w)), max(y0 + 1, int(box[3] * h))
    crop_lines: list[dict] = []
    paddle_extractor.read_image(image.crop((x0, y0, x1, y1)), crop_lines)
    cw, ch = (x1 - x0) / w, (y1 - y0) / h

    def to_page(b: list[float]) -> list[float]:
        return [round(x0 / w + b[0] * cw, 5), round(y0 / h + b[1] * ch, 5), round(x0 / w + b[2] * cw, 5), round(y0 / h + b[3] * ch, 5)]

    for line in crop_lines:
        line["box"] = to_page(line["box"])
        for word in line.get("words", []):
            word["box"] = to_page(word["box"])
    return crop_lines


def table_text(rows: list[list[str]]) -> str:
    return "\n".join(CELL_SEPARATOR.join(cell for cell in row) for row in rows)


# ---------------------------------------------------------------------------------------------
# Spacing-preserving text


def _row_items(line: dict) -> list[tuple[float, float, str]]:
    return [(p["box"][0], p["box"][2], p["text"]) for p in _pieces(line)]


def _char_width(line: dict) -> float:
    """Width of one character in this line, from its words (gaps between table cells don't count)."""
    pieces = _pieces(line)
    chars = sum(len(p["text"]) for p in pieces)
    return sum(p["box"][2] - p["box"][0] for p in pieces) / max(1, chars)


def layout_text(lines: list[dict]) -> str:
    """The page as monospace text: lines at their rows, indentation and column gaps kept.

    Columns come from the page's median character width (measured on words, so the gaps between
    table cells don't inflate it) and rows from its median line height;
    gaps between rows become blank lines (at most MAX_BLANK_ROWS). Inside a row, pieces are
    joined by one space unless the gap is a real column gap (tables, tab stops), which is kept.
    """
    lines = [l for l in lines if l.get("box") and l.get("text", "").strip()]
    if not lines:
        return ""
    char_w = _median([_char_width(l) for l in lines], 0.01)
    line_h = _median([l["box"][3] - l["box"][1] for l in lines], 0.015)
    left = min(l["box"][0] for l in lines)

    rows: list[list[dict]] = []  # lines that share a row (vertical overlap), top to bottom
    for line in sorted(lines, key=lambda l: _centre(l["box"])[1]):
        y0, y1 = line["box"][1], line["box"][3]
        if rows:
            top, bottom = min(l["box"][1] for l in rows[-1]), max(l["box"][3] for l in rows[-1])
            if min(bottom, y1) - max(top, y0) > 0.5 * min(bottom - top, y1 - y0):
                rows[-1].append(line)
                continue
        rows.append([line])

    out: list[str] = []
    previous_bottom = None
    for row in rows:
        top = min(l["box"][1] for l in row)
        if previous_bottom is not None:
            out.extend([""] * max(0, min(MAX_BLANK_ROWS, int(round((top - previous_bottom) / line_h)))))
        previous_bottom = max(l["box"][3] for l in row)
        pieces = []
        for line in row:
            own_w = _char_width(line)
            pieces.extend((x0, x1, text, own_w) for x0, x1, text in _row_items(line))
        text, prev_x1 = "", 0.0
        for x0, x1, piece, own_w in sorted(pieces, key=lambda i: i[0]):
            column = int(round((x0 - left) / char_w))
            if not text:
                text = " " * column + piece
            elif x0 - prev_x1 > COLUMN_GAP_CHARS * own_w:
                text = text.ljust(max(column, len(text) + 2)) + piece  # column gap: keep the position
            else:
                text += " " + piece
            prev_x1 = x1
        out.append(text.rstrip())
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------
# Whole page


def analyze_page(image: Image.Image, lines: list[dict]) -> dict:
    """Regions in reading order, the rebuilt page text, and the spacing-preserving layout text.

    Never raises: if the layout model is unavailable, every line goes through the position rules.
    Returns {"regions": [...], "text": str, "layout_text": str, "lines": [...]}; lines are the
    page's lines with the text inside tables replaced by a second, table-friendly read
    (read_region), so the viewer and answers see the better text.
    """
    lines = [l for l in lines if l.get("text", "").strip() and l.get("box")]
    try:
        detections = dedupe(detect(image)) if settings.layout_analysis else []
    except LayoutUnavailableError as e:
        logger.warning("Layout model unavailable (%s); grouping lines by position", e)
        detections = []
    except Exception:
        logger.exception("Layout detection failed; grouping lines by position")
        detections = []

    for det in detections:
        det["lines"] = []
    loose = []
    for line in lines:
        i = _region_of(line, detections)
        (detections[i]["lines"] if i is not None else loose).append(line)

    # Tables are read again with the PaddleOCR engine, whose detector finds the text of ruled
    # cells that Tesseract often misses or breaks up; its lines replace the page OCR's there.
    replaced: set[int] = set()
    for det in detections:
        if det["type"] != "table" or not settings.table_reread:
            continue
        try:
            again = read_region(image, det["box"])
        except Exception:
            logger.exception("Could not read the table again; keeping the page OCR's text")
            continue
        if sum(len(l["text"]) for l in again) >= sum(len(l["text"]) for l in det["lines"]):
            replaced.update(id(l) for l in det["lines"])
            det["lines"] = again
    lines = [l for l in lines if id(l) not in replaced] + [l for d in detections if d["type"] == "table" for l in d["lines"] if id(l) not in {id(x) for x in lines}]

    # Body text height: tables, figures, and formulas often use other sizes, so leave them out.
    other = {id(l) for d in detections if d["type"] in ("table", "figure", "formula") for l in d["lines"]}
    body = [l["box"][3] - l["box"][1] for l in lines if id(l) not in other]
    line_h = _median(body or [l["box"][3] - l["box"][1] for l in lines], 0.015)

    regions = [d for d in detections if d["lines"] or d["type"] == "figure"] + _group_loose_lines(loose, line_h)
    for r in regions:  # the layout model sometimes calls a heading plain text
        if r["type"] == "text" and _is_title(r["lines"], line_h):
            r["type"] = "title"
    out = []
    for r in reading_order(regions):
        region = {"type": r["type"], "box": [round(v, 5) for v in r["box"]], "conf": _conf(r["lines"])}
        if r["type"] == "table":
            region["rows"] = table_rows(image, r["box"], r["lines"])
            region["text"] = table_text(region["rows"])
        elif r["type"] == "title":
            region["text"] = " ".join(l["text"] for l in sorted(r["lines"], key=lambda l: (_centre(l["box"])[1], l["box"][0])))
        else:
            region["text"] = _lines_text(r["lines"])
        out.append(region)
    text = "\n\n".join(r["text"] for r in out if r["text"])
    return {"regions": out, "text": text, "layout_text": layout_text(lines), "lines": lines}


def qa_blocks(regions: list[dict]) -> list[tuple[str, ContentType | None]]:
    """(text, content type or None) per region for chunking: tables and figures keep their type."""
    return [(r["text"], CONTENT_TYPE.get(r["type"])) for r in regions if r.get("text")]
