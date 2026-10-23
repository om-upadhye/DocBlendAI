"""Module 1 — Document Upload.

Responsibility: accept an upload (PDF, image, Word, PowerPoint, or text; see
file_types.py), save it under settings.upload_dir, run it through
detection -> extraction (parse/OCR/HTR) -> chunking ->
calibration -> content-type labeling -> embedding -> ChromaDB, and record a
Document row.

Uses from schemas.py: Document, FormatType.
"""

import ctypes
import gc
import logging
import re
import shutil
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from pdfplumber.utils.exceptions import PdfminerException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import site
from app.config import settings
from app.db.database import get_db
from app.db.models import DocumentORM
from app.models.schemas import ContentType, Document, FormatType
from app.modules import (
    chunker,
    confidence_capture,
    content_type,
    embedder,
    exporters,
    file_types,
    format_detection,
    htr_extractor,
    layout_analysis,
    ocr_extractor,
    page_store,
    vector_store,
    vision_reader,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["upload"])


_reading = threading.Lock()


def _release_memory() -> None:
    """Give the page images and model buffers of the last upload back to the system.

    Python frees objects, but glibc keeps the freed memory in the process for reuse; on a 512 MB
    server that leftover plus the next upload is what runs out. malloc_trim hands it back (Linux only).
    """
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except OSError:  # not Linux / not glibc
        pass


# Plain `def` (not async): PDF parsing, OCR, and HTR are blocking, so FastAPI runs this in its threadpool.
@router.post("/upload", response_model=Document, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    format_hint: FormatType | None = Form(
        None,
        description=(
            "Skip automatic detection and force this format (e.g. if detection guesses wrong). "
            "Ignored for Word/PowerPoint/text files (always typed), and 'typed' is ignored for images."
        ),
    ),
    db: Session = Depends(get_db),
    session_id: str | None = Depends(site.session_header),
) -> Document:
    filename = file.filename or ""
    if file_types.kind_of(filename) is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported file type. Upload one of: {file_types.supported_extensions()}",
        )
    if settings.max_upload_mb and (file.size or 0) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"File is too large (limit {settings.max_upload_mb} MB)")
    if session_id:
        site.touch(db, session_id)  # a long OCR run must not let the session expire under it

    doc_id = uuid.uuid4().hex
    # Keep the original name in the stored path so the UI can show it (the Document entity has no name field).
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).stem)[:80] or "document"
    path = settings.upload_dir / f"{doc_id}_{safe_name}{Path(filename).suffix.lower()}"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    try:
        # One document is read at a time: reading a page needs ~150-250 MB, so two at once would push
        # a 512 MB server over its limit and the host would restart it mid-upload (a 502 for the visitor).
        # Others wait their turn; their session stays alive meanwhile.
        with _reading:
            if session_id:
                site.touch(db, session_id)
            document = _ingest(doc_id, path, format_hint, db)
        site.claim(db, session_id, doc_id)
    except Exception:
        # Any failure (rejection, service error, or bug) leaves no stray upload behind.
        path.unlink(missing_ok=True)
        raise
    finally:
        format_detection.forget(str(path))
        _release_memory()
    logger.info("Uploaded %s as %s", file.filename, doc_id)
    return document


@router.get("/documents", response_model=list[Document])
def list_documents(
    db: Session = Depends(get_db), session_id: str | None = Depends(site.session_header)
) -> list[Document]:
    """All documents (on the public demo: this session's), oldest upload first (SQLite rowid follows insertion order)."""
    rows = db.query(DocumentORM)
    visible = site.visible_doc_ids(db, session_id)
    if visible is not None:
        rows = rows.filter(DocumentORM.doc_id.in_(visible))
    return [Document.model_validate(row) for row in rows.order_by(text("rowid")).all()]


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    doc_id: str, db: Session = Depends(get_db), session_id: str | None = Depends(site.session_header)
) -> None:
    """Remove a document everywhere: its row, its chunks in ChromaDB, and the uploaded file.

    Past answers stay in the history; their sources simply no longer list this document.
    """
    row = db.get(DocumentORM, doc_id)
    visible = site.visible_doc_ids(db, session_id)
    if row is None or (visible is not None and doc_id not in visible):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    site.remove_document(db, row)
    logger.info("Deleted document %s", doc_id)


# Browsers can show these inline; Word/PowerPoint files are offered as downloads.
_MEDIA_TYPES = {
    ".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".tif": "image/tiff", ".tiff": "image/tiff", ".bmp": "image/bmp", ".webp": "image/webp",
    ".txt": "text/plain; charset=utf-8",
}


@router.get("/documents/{doc_id}/file", response_class=FileResponse)
def document_file(doc_id: str, db: Session = Depends(get_db)) -> FileResponse:
    """The original upload, for the preview next to the chat (the random doc_id acts as the access key)."""
    row = db.get(DocumentORM, doc_id)
    if row is None or not Path(row.file_path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    path = Path(row.file_path)
    media_type = _MEDIA_TYPES.get(path.suffix.lower())
    return FileResponse(
        path,
        media_type=media_type or "application/octet-stream",
        filename=path.name.removeprefix(f"{doc_id}_"),
        content_disposition_type="inline" if media_type else "attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


class LineView(BaseModel):
    text: str
    conf: float = Field(description="Calibrated recognition confidence of this line (0-1)")
    box: list[float] = Field(description="[x0, y0, x1, y1] as fractions of the page image size")


class BlockView(BaseModel):
    """A paragraph, table, or picture on a typed page (API-only, for the document viewer)."""

    type: ContentType
    text: str
    box: list[float] | None = Field(description="[x0, y0, x1, y1] as page fractions; only on PDF pages")
    rows: list[list[str]] | None = Field(None, description="Table cells, row by row (tables only)")
    picture_url: str | None = Field(None, description="The picture itself, if the browser can show it (pictures only)")


class RegionView(BaseModel):
    """A layout region of a scanned or handwritten page (API-only; see layout_analysis.py)."""

    type: str = Field(description="title, text, table, figure, caption, formula, header, footer, or reference")
    box: list[float] = Field(description="[x0, y0, x1, y1] as fractions of the page image size")
    text: str
    conf: float = Field(description="Calibrated recognition confidence of the region's text (0-1)")
    rows: list[list[str]] | None = Field(None, description="Table cells, row by row (tables only)")


class PageView(BaseModel):
    """What recognition read on one page (API-only, for the document viewer).

    Scanned and handwritten pages list recognised lines and layout regions; typed pages list blocks.
    """

    page: int
    text: str
    conf: float
    image_url: str | None
    lines: list[LineView]
    regions: list[RegionView] = []
    blocks: list[BlockView]
    layout_text: str = Field("", description="The page as monospace text with its spacing and columns kept")
    vision: dict | None = Field(
        None,
        description="Set when a vision model read this page (vision_reader.py): model, confidence (agreement "
        "with OCR), legibility (the model's own estimate), word counts, and what it set aside",
    )


@router.get("/documents/{doc_id}/pages", response_model=list[PageView])
def document_pages(doc_id: str, db: Session = Depends(get_db)) -> list[PageView]:
    """Each page's text, its recognised lines (scans) or blocks (typed), and a page image link."""
    row = db.get(DocumentORM, doc_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    if row.format_type == FormatType.TYPED:
        page_store.ensure_blocks(doc_id, row.file_path)  # typed uploads from before blocks existed
    pages = page_store.load(doc_id)
    if pages is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No page view saved for this document; upload it again")
    return [
        PageView(
            page=p["page"],
            text=p["text"],
            conf=p["conf"],
            image_url=f"/documents/{doc_id}/pages/{p['page']}/image" if p["image"] else None,
            lines=p["lines"],
            regions=p.get("regions", []),
            layout_text=p.get("layout_text") or p["text"],
            vision=p.get("vision"),
            blocks=[
                BlockView(
                    **{k: v for k, v in b.items() if k != "picture"},
                    picture_url=f"/documents/{doc_id}/pictures/{b['picture']}" if b.get("picture") else None,
                )
                for b in p.get("blocks", [])
            ],
        )
        for p in pages
    ]


@router.get("/documents/{doc_id}/pages/{page}/image", response_class=FileResponse)
def document_page_image(doc_id: str, page: int) -> FileResponse:
    path = page_store.image_path(doc_id, page)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No image for this page")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/documents/{doc_id}/pictures/{name}", response_class=FileResponse)
def document_picture(doc_id: str, name: str) -> FileResponse:
    """A picture found in a typed document (see BlockView.picture_url)."""
    path = page_store.picture_path(doc_id, name)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such picture")
    return FileResponse(path, media_type="image/png")


# Download file name after the upload's own name, e.g. notes_layout.txt, notes.md.
_EXPORT_FILES = {"txt": "{}.txt", "layout": "{}_layout.txt", "md": "{}.md", "json": "{}.json"}
_EXPORT_TYPES = {
    "txt": "text/plain; charset=utf-8", "layout": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8", "json": "application/json",
}


@router.get("/documents/{doc_id}/export")
def export_document(
    doc_id: str,
    format: str = Query("layout", pattern="^(txt|layout|md|csv|json)$", description=", ".join(exporters.FORMATS)),
    db: Session = Depends(get_db),
) -> Response:
    """Download what was read: txt, layout (spacing kept), md, csv (tables), or json.

    Like /file, the random doc_id is the access key, so links work in a browser or the app.
    """
    row = db.get(DocumentORM, doc_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    if row.format_type == FormatType.TYPED:
        page_store.ensure_blocks(doc_id, row.file_path)
    pages = page_store.load(doc_id)
    if pages is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No page view saved for this document; upload it again")
    stem = Path(row.file_path).stem.removeprefix(f"{doc_id}_") or "document"
    if format == "csv":
        try:
            content, media_type, ext = exporters.to_csv(pages)
        except exporters.ExportError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
        filename = f"{stem}_tables.{ext}"
    else:
        if format == "md":
            content = exporters.to_md(pages, stem)
        elif format == "json":
            # The server's file path is internal: the JSON names the document instead.
            info = Document.model_validate(row).model_dump(mode="json", exclude={"file_path"})
            content = exporters.to_json(pages, {**info, "name": Path(row.file_path).name.removeprefix(f"{doc_id}_")})
        else:
            content = exporters.to_layout(pages) if format == "layout" else exporters.to_txt(pages)
        media_type = _EXPORT_TYPES[format]
        filename = _EXPORT_FILES[format].format(stem)
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-Content-Type-Options": "nosniff"},
    )


def _vision_read(layout: list[dict], extracted: list, blocks: list | None, format_type: FormatType) -> set[int]:
    """Read qualifying pages with the vision model (3 at a time). Returns the page indexes it replaced.

    Any failure (no key, quota, network) keeps the OCR text for that page: uploads never fail over it.
    """
    from concurrent.futures import ThreadPoolExecutor

    todo = [
        i for i, record in enumerate(layout)
        if i < len(extracted)
        and vision_reader.should_read(format_type.value, confidence_capture.calibrate(extracted[i][1], format_type))
    ]
    if not todo:
        return set()

    def read(i: int):
        try:
            return i, vision_reader.read_page(layout[i]["image"], layout[i]["lines"])
        except Exception as e:  # keep OCR's reading for this page
            logger.warning("Vision reading of page %d failed, keeping OCR text: %s", i + 1, e)
            return i, None

    done: set[int] = set()
    with ThreadPoolExecutor(max_workers=3) as pool:
        for i, read_ in pool.map(read, todo):
            if read_ is None:
                continue
            extracted[i] = (read_.text, read_.raw_conf)
            if blocks is not None and i < len(blocks):
                blocks[i] = None  # chunk the transcription as running text
            layout[i]["layout_text"] = read_.text
            layout[i]["vision"] = {
                "model": read_.model, "confidence": read_.raw_conf, "legibility": read_.legibility,
                "words": read_.words, "ignored": read_.ignored,
            }
            done.add(i)
    return done


def _ingest(doc_id: str, path: Path, format_hint: FormatType | None, db: Session) -> Document:
    """Detect -> extract -> chunk -> calibrate -> label -> embed -> store. Raises HTTPException on expected failures."""
    unreadable = f"File is not a readable {path.suffix} file (damaged, or not what its extension says)"
    try:
        pages = format_detection.page_count(str(path))
        format_type = format_detection.resolve_format(str(path), format_hint)
    except (PdfminerException, file_types.UnreadableFileError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, unreadable)
    except (ocr_extractor.OCRUnavailableError, htr_extractor.HTRUnavailableError) as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    if settings.max_pages and pages > settings.max_pages:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"Too many pages ({pages}); this server accepts up to {settings.max_pages}"
        )

    document = Document(doc_id=doc_id, file_path=str(path), format_type=format_type, page_count=pages)
    layout: list[dict] = []  # page images + line boxes, filled by OCR/HTR, for the viewer
    try:
        extracted = format_detection.extract(document, layout)
    except file_types.UnreadableFileError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, unreadable)
    except (ocr_extractor.OCRUnavailableError, htr_extractor.HTRUnavailableError) as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))

    # Scanned / handwritten pages: regions, tables, reading order, spacing (layout_analysis.py).
    # The page text is rebuilt in reading order, and tables become their own chunks.
    blocks = None
    if layout:
        blocks = []
        for i, record in enumerate(layout):
            analysis = layout_analysis.analyze_page(record["image"], record["lines"])
            record["regions"], record["layout_text"] = analysis["regions"], analysis["layout_text"]
            record["lines"] = analysis["lines"]  # table text re-read with a table-friendly engine
            if analysis["text"] and i < len(extracted):
                extracted[i] = (analysis["text"], extracted[i][1])
            blocks.append(layout_analysis.qa_blocks(analysis["regions"]))

    # Hard pages (handwriting, poor scans) are read again by a vision model; its transcription
    # replaces the OCR text for answering, with a confidence from agreement with OCR (vision_reader.py).
    vision_pages = _vision_read(layout, extracted, blocks, format_type)

    page_of: list[int] = []
    chunks = chunker.chunk_pages(doc_id, extracted, blocks=blocks, pages_out=page_of)
    if not chunks:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No readable text found in this file")
    chunks = confidence_capture.apply_calibration(chunks, format_type)
    # A vision page's confidence is already an accuracy estimate (agreement), not an OCR score to calibrate.
    chunks = [c.model_copy(update={"calibrated_conf": c.raw_conf}) if page_of[n] in vision_pages else c for n, c in enumerate(chunks)]
    chunks = content_type.label_chunks(chunks)

    try:
        chunks = embedder.embed_chunks(chunks)
    except embedder.EmbeddingError as e:
        logger.error("Embedding failed for %s: %s", doc_id, e)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Embedding service failed; try again later")
    vector_store.add_chunks(doc_id, chunks)

    try:
        db.add(DocumentORM(**document.model_dump()))
        db.commit()
    except Exception:
        # Keep ChromaDB and SQLite consistent: no vectors without a Document row.
        vector_store.delete_document(doc_id)
        raise

    # The viewer shows calibrated confidence, the same scale the reliability labels use.
    calibrate = lambda conf: confidence_capture.calibrate(conf, format_type)  # noqa: E731
    for record in layout:
        for line in record["lines"]:
            line["conf"] = round(calibrate(line["conf"]), 4)
            for word in line.get("words", []):
                word["conf"] = round(calibrate(word["conf"]), 4)
        for region in record.get("regions", []):
            region["conf"] = round(calibrate(region["conf"]), 4)
    page_store.save(
        doc_id, str(path), [(t, c if i in vision_pages else calibrate(c)) for i, (t, c) in enumerate(extracted)],
        layout, typed=format_type is FormatType.TYPED,
    )

    mean_conf = sum(c.calibrated_conf for c in chunks) / len(chunks)
    logger.info(
        "Ingested %s: %s, %d pages, %d chunks, mean calibrated confidence %.2f",
        doc_id, format_type.value, pages, len(chunks), mean_conf,
    )
    return document
