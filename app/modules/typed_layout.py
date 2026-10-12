"""Supports Module 4 — paragraphs, tables, and pictures of typed documents, for the viewer.

Responsibility: split each page of a typed document into blocks the viewer can
outline, one colour per content type (the same three types as Module 4):
- PDF: tables (pdfplumber's ruled-table finder), embedded pictures, and
  paragraphs (text lines grouped by spacing and font size), each with a box
  as fractions of the page, drawn over the page preview
- Word: body paragraphs (consecutive list items merged), tables, and pictures,
  in document order (Word files have no fixed pages, so no boxes)
- PowerPoint: per slide, text boxes, tables, pictures, and charts in reading order
- text: blank-line-separated blocks; column-aligned ones are tables

Types come from the file's structure, not from content_type.classify, which
labels the chunks used for answering from their text alone. Pictures are
saved as PNG next to the page images so the viewer can show them.

Block: {"type": "paragraph"|"table"|"image", "text", "box": [x0, y0, x1, y1] | None,
        "rows": [[cell, ...], ...] (tables only), "picture": file name | None (images only)}

Uses from schemas.py: ContentType.
"""

import io
import logging
import re
from pathlib import Path
from statistics import median

import pdfplumber
from docx import Document as open_docx
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.shapes.picture import Picture

from app.models.schemas import ContentType
from app.modules import content_type, text_parser
from app.modules.file_types import FileKind, kind_of

logger = logging.getLogger(__name__)

# A gap between lines wider than the page's usual line gap by this factor (and at least
# PARAGRAPH_MIN_EXTRA points more) starts a new paragraph.
PARAGRAPH_GAP_FACTOR = 1.5
PARAGRAPH_MIN_EXTRA = 2.0
FONT_SIZE_JUMP = 1.0  # points; a size change this large (e.g. heading -> body) starts one too
MIN_PICTURE_AREA = 0.005  # share of the page; smaller images are bullets, logos, or rules
PICTURE_MAX_SIDE = 1000

_CELL_SPLIT = re.compile(r"\s{2,}|\t|\|")
_CAPTION = re.compile(r"^\s*(figure|fig\.?|chart|graph)\s*\d+", re.IGNORECASE)


def blocks(file_path: str, pictures_dir: Path, max_pages: int | None = None) -> list[list[dict]]:
    """The blocks on each page (PDF page, slide; Word and text files are one page)."""
    kind = kind_of(file_path)
    if kind is FileKind.DOCX:
        return [_docx_blocks(file_path, pictures_dir)]
    if kind is FileKind.PPTX:
        return _pptx_blocks(file_path, pictures_dir, max_pages)
    if kind is FileKind.TXT:
        return [_txt_blocks(file_path)]
    return _pdf_blocks(file_path, pictures_dir, max_pages)


def _block(kind: ContentType, text: str, box=None, rows=None, picture=None) -> dict:
    block = {"type": kind.value, "text": text, "box": box}
    if kind is ContentType.TABLE:
        block["rows"] = rows or []
    if kind is ContentType.IMAGE:
        block["picture"] = picture
    return block


def _rows_text(rows: list[list[str]]) -> str:
    return "\n".join("  ".join(c for c in row if c) for row in rows if any(row))


def _dedupe_cells(cells: list[str]) -> list[str]:
    # Merged cells repeat the same text in every cell they span; keep it once.
    return [c for i, c in enumerate(cells) if i == 0 or c != cells[i - 1]]


class _PictureSaver:
    """Saves pictures as pic_<n>.png; formats the browser cannot show (EMF/WMF, broken data) give None."""

    def __init__(self, directory: Path):
        self.directory, self.count = directory, 0

    def save(self, image: Image.Image) -> str | None:
        try:
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            image.thumbnail((PICTURE_MAX_SIDE, PICTURE_MAX_SIDE))
            self.count += 1
            name = f"pic_{self.count}.png"
            self.directory.mkdir(parents=True, exist_ok=True)
            image.save(self.directory / name)
            return name
        except Exception:  # an unviewable picture still shows as a block, just without its image
            logger.debug("Could not save picture", exc_info=True)
            return None

    def save_blob(self, blob: bytes) -> str | None:
        try:
            with Image.open(io.BytesIO(blob)) as image:
                image.load()
                return self.save(image)
        except Exception:
            return None


# --- PDF -----------------------------------------------------------------------------------


def _pdf_blocks(file_path: str, pictures_dir: Path, max_pages: int | None) -> list[list[dict]]:
    saver = _PictureSaver(pictures_dir)
    with pdfplumber.open(file_path) as pdf:
        return [_pdf_page_blocks(page, saver) for page in pdf.pages[:max_pages]]


def _inside(obj: dict, box: tuple) -> bool:
    x = (obj["x0"] + obj["x1"]) / 2
    y = (obj["top"] + obj["bottom"]) / 2
    return box[0] - 2 <= x <= box[2] + 2 and box[1] - 2 <= y <= box[3] + 2


def _pdf_page_blocks(page, saver: _PictureSaver) -> list[dict]:
    left, top = page.bbox[0], page.bbox[1]

    def frac(x0, y0, x1, y1) -> list[float]:
        return [
            round(min(max((x0 - left) / page.width, 0), 1), 4),
            round(min(max((y0 - top) / page.height, 0), 1), 4),
            round(min(max((x1 - left) / page.width, 0), 1), 4),
            round(min(max((y1 - top) / page.height, 0), 1), 4),
        ]

    found: list[tuple[float, float, dict]] = []  # (top, x0, block), sorted into reading order at the end
    taken: list[tuple] = []  # boxes whose text belongs to a table or picture, not a paragraph

    for table in page.find_tables():
        rows = [_dedupe_cells([(c or "").replace("\n", " ").strip() for c in row]) for row in table.extract()]
        rows = [row for row in rows if any(row)]
        if len(rows) < 2 or max(len(row) for row in rows) < 2:  # a ruled box around text, not a table
            continue
        taken.append(table.bbox)
        found.append((table.bbox[1], table.bbox[0], _block(ContentType.TABLE, _rows_text(rows), frac(*table.bbox), rows=rows)))

    words = page.extract_words()
    for image in page.images:
        box = (max(image["x0"], left), max(image["top"], top), min(image["x1"], left + page.width), min(image["bottom"], top + page.height))
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        if (box[2] - box[0]) * (box[3] - box[1]) < MIN_PICTURE_AREA * page.width * page.height:
            continue
        taken.append(box)
        labels = " ".join(w["text"] for w in words if _inside(w, box))
        picture = None
        try:
            picture = saver.save(page.crop(box).to_image(resolution=110).original)
        except Exception:
            logger.debug("Could not render picture", exc_info=True)
        found.append((box[1], box[0], _block(ContentType.IMAGE, labels, frac(*box), picture=picture)))

    lines = [line for line in page.extract_text_lines(return_chars=True) if not any(_inside(line, b) for b in taken)]
    for para in _group_lines(lines):
        box = (min(l["x0"] for l in para), para[0]["top"], max(l["x1"] for l in para), max(l["bottom"] for l in para))
        text = "\n".join(l["text"] for l in para)
        found.append((box[1], box[0], _block(ContentType.PARAGRAPH, text, frac(*box))))

    ordered = [block for _, _, block in sorted(found, key=lambda f: (round(f[0]), f[1]))]
    # Name a picture by its caption ("Figure 2: ...") when one sits right below it.
    for picture, after in zip(ordered, ordered[1:]):
        if picture["type"] == ContentType.IMAGE.value and not picture["text"] and _CAPTION.match(after["text"]):
            picture["text"] = after["text"].splitlines()[0]
    return ordered


def _font_size(line: dict) -> float:
    sizes = [c.get("size", 0) for c in line.get("chars", []) if c.get("text", "").strip()]
    return median(sizes) if sizes else 0.0


def _group_lines(lines: list[dict]) -> list[list[dict]]:
    """Group text lines into paragraphs: a wide gap, a font size change, or a new column splits them.

    "Wide" is relative to this page's usual gap between lines of one paragraph,
    so both tightly and loosely spaced documents split where the author left space.
    """
    gaps = [b["top"] - a["bottom"] for a, b in zip(lines, lines[1:])]
    usual = [g for g, a in zip(gaps, lines) if 0 <= g <= a["bottom"] - a["top"]]
    usual_gap = median(usual) if usual else 3.0
    max_gap = max(usual_gap * PARAGRAPH_GAP_FACTOR, usual_gap + PARAGRAPH_MIN_EXTRA)

    paragraphs: list[list[dict]] = []
    for line in lines:
        if paragraphs:
            prev = paragraphs[-1][-1]
            gap = line["top"] - prev["bottom"]
            overlaps = line["x0"] < prev["x1"] and prev["x0"] < line["x1"]
            same_size = abs(_font_size(line) - _font_size(prev)) < FONT_SIZE_JUMP
            if -1 <= gap <= max_gap and overlaps and same_size:
                paragraphs[-1].append(line)
                continue
        paragraphs.append([line])
    return paragraphs


# --- Word ----------------------------------------------------------------------------------


def _docx_pictures(paragraph: Paragraph, saver: _PictureSaver) -> list[dict]:
    found = []
    descriptions = paragraph._p.xpath(".//wp:docPr/@descr")
    for i, rel_id in enumerate(paragraph._p.xpath(".//a:blip/@r:embed")):
        part = paragraph.part.related_parts.get(rel_id)
        picture = saver.save_blob(part.blob) if part is not None else None
        text = descriptions[i] if i < len(descriptions) else ""
        found.append(_block(ContentType.IMAGE, text, picture=picture))
    return found


def _is_list_item(paragraph: Paragraph) -> bool:
    return "List" in (paragraph.style.name if paragraph.style is not None else "") or bool(paragraph._p.xpath("./w:pPr/w:numPr"))


def _docx_blocks(file_path: str, pictures_dir: Path) -> list[dict]:
    saver = _PictureSaver(pictures_dir)
    found: list[dict] = []
    in_list = False
    for item in open_docx(file_path).iter_inner_content():
        if isinstance(item, DocxTable):
            rows = [_dedupe_cells([cell.text.strip().replace("\n", " ") for cell in row.cells]) for row in item.rows]
            rows = [row for row in rows if any(row)]
            if rows:
                found.append(_block(ContentType.TABLE, _rows_text(rows), rows=rows))
            in_list = False
            continue
        found.extend(_docx_pictures(item, saver))
        text = item.text.strip()
        if not text:
            in_list = False
            continue
        is_item = _is_list_item(item)
        if is_item and in_list and found and found[-1]["type"] == ContentType.PARAGRAPH.value:
            found[-1]["text"] += "\n" + text  # keep a bulleted list together
        else:
            found.append(_block(ContentType.PARAGRAPH, text))
        in_list = is_item
    return found


# --- PowerPoint ----------------------------------------------------------------------------


def _slide_shapes(shapes, origin=(0, 0)):
    """(top, left, shape) for every shape, groups flattened, in reading order."""
    placed = []
    for shape in shapes:
        top, left = (shape.top or 0) + origin[0], (shape.left or 0) + origin[1]
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            placed.extend(_slide_shapes(shape.shapes, (top, left)))
        else:
            placed.append((top, left, shape))
    return sorted(placed, key=lambda p: (p[0], p[1]))


def _shape_block(shape, saver: _PictureSaver) -> dict | None:
    if isinstance(shape, Picture):
        try:
            blob = shape.image.blob
        except Exception:  # linked, not embedded
            blob = None
        return _block(ContentType.IMAGE, "", picture=saver.save_blob(blob) if blob else None)
    if getattr(shape, "has_chart", False) and shape.has_chart:
        chart = shape.chart
        title = chart.chart_title.text_frame.text if chart.has_title and chart.chart_title.has_text_frame else ""
        return _block(ContentType.IMAGE, title or "Chart")
    if getattr(shape, "has_table", False) and shape.has_table:
        rows = [_dedupe_cells([cell.text.strip().replace("\n", " ") for cell in row.cells]) for row in shape.table.rows]
        rows = [row for row in rows if any(row)]
        return _block(ContentType.TABLE, _rows_text(rows), rows=rows) if rows else None
    if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
        text = "\n".join(p.text.strip() for p in shape.text_frame.paragraphs if p.text.strip())
        return _block(ContentType.PARAGRAPH, text) if text else None
    return None


def _pptx_blocks(file_path: str, pictures_dir: Path, max_pages: int | None) -> list[list[dict]]:
    saver = _PictureSaver(pictures_dir)
    slides = list(Presentation(file_path).slides)[:max_pages]
    return [[b for _, _, shape in _slide_shapes(slide.shapes) if (b := _shape_block(shape, saver))] for slide in slides]


# --- text ----------------------------------------------------------------------------------


def _txt_blocks(file_path: str) -> list[dict]:

    [(text, _)] = text_parser.parse_txt(file_path)  # same decoding as ingestion
    found = []
    for part in re.split(r"\n\s*\n", text):
        part = part.strip("\n")
        if not part.strip():
            continue
        if content_type.classify(part) is ContentType.TABLE:
            rows = [[c for c in _CELL_SPLIT.split(line.strip()) if c] for line in part.splitlines() if line.strip()]
            found.append(_block(ContentType.TABLE, part, rows=rows))
        else:
            found.append(_block(ContentType.PARAGRAPH, part))
    return found
