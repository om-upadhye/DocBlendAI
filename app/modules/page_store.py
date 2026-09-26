"""Supports Modules 1-2 — page images and recognised lines for the document viewer.

Responsibility: at upload, keep what the recognition step saw so users can
check it later, PaddleOCR-demo style: each page image with every recognised
line boxed and scored.

Stored per document under settings.upload_dir / "<doc_id>_pages":
- page_<n>.jpg: the page image recognition read (after orientation fix),
  reduced to at most MAX_SIDE px; typed PDFs get a plain render
- layout.json: [{"page", "text", "conf", "image", "lines": [{"text", "conf", "box"}]}]
  with boxes as fractions of the page size, so they fit any display size

Word, PowerPoint, and text files have no page images; their pages carry text only.

Uses from schemas.py: nothing directly.
"""

import json
import logging
import shutil
from contextlib import closing
from pathlib import Path

from app.config import settings
from app.modules.file_types import FileKind, kind_of
from app.modules.pdf_render import render_pages

logger = logging.getLogger(__name__)

MAX_SIDE = 1600
TYPED_PREVIEW_DPI = 100
MAX_PREVIEW_PAGES = 100  # typed PDFs: previews for at most this many pages


def pages_dir(doc_id: str) -> Path:
    return settings.upload_dir / f"{doc_id}_pages"


def save(doc_id: str, file_path: str, extracted: list[tuple[str, float]], layout: list[dict]) -> None:
    """Store page images + layout. Never fails the upload: problems are only logged."""
    try:
        directory = pages_dir(doc_id)
        directory.mkdir(parents=True, exist_ok=True)
        images = [record["image"] for record in layout]
        if not images and kind_of(file_path) is FileKind.PDF:  # typed PDF: plain previews, no boxes
            with closing(render_pages(file_path, TYPED_PREVIEW_DPI, MAX_PREVIEW_PAGES)) as pages:
                images = list(pages)

        pages = []
        for i, (text, conf) in enumerate(extracted):
            name = None
            if i < len(images):
                image = images[i].convert("L")
                image.thumbnail((MAX_SIDE, MAX_SIDE))
                name = f"page_{i + 1}.jpg"
                image.save(directory / name, quality=80)
            lines = layout[i]["lines"] if i < len(layout) else []
            pages.append({"page": i + 1, "text": text, "conf": round(conf, 4), "image": name, "lines": lines})
        (directory / "layout.json").write_text(json.dumps(pages), encoding="utf-8")
    except Exception:  # the viewer is a convenience; the document itself was ingested fine
        logger.exception("Could not save page view for %s", doc_id)


def load(doc_id: str) -> list[dict] | None:
    """The saved pages, or None if this document has no page view (e.g. uploaded before it existed)."""
    path = pages_dir(doc_id) / "layout.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def image_path(doc_id: str, page: int) -> Path | None:
    path = pages_dir(doc_id) / f"page_{page}.jpg"
    return path if path.is_file() else None


def delete(doc_id: str) -> None:
    shutil.rmtree(pages_dir(doc_id), ignore_errors=True)
