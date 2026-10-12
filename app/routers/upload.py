"""Module 1 — Document Upload.

Responsibility: accept an upload (PDF, image, Word, PowerPoint, or text; see
file_types.py), save it under settings.upload_dir, run it through
detection -> extraction (parse/OCR/HTR) -> chunking ->
calibration -> content-type labeling -> embedding -> ChromaDB, and record a
Document row.

Uses from schemas.py: Document, FormatType.
"""

import logging
import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pdfplumber.utils.exceptions import PdfminerException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db
from app.db.models import DocumentORM
from app.models.schemas import ContentType, Document, FormatType
from app.modules import (
    chunker,
    confidence_capture,
    content_type,
    embedder,
    file_types,
    format_detection,
    htr_extractor,
    ocr_extractor,
    page_store,
    vector_store,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["upload"])


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
) -> Document:
    filename = file.filename or ""
    if file_types.kind_of(filename) is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported file type. Upload one of: {file_types.supported_extensions()}",
        )

    doc_id = uuid.uuid4().hex
    # Keep the original name in the stored path so the UI can show it (the Document entity has no name field).
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).stem)[:80] or "document"
    path = settings.upload_dir / f"{doc_id}_{safe_name}{Path(filename).suffix.lower()}"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    try:
        document = _ingest(doc_id, path, format_hint, db)
    except Exception:
        # Any failure (rejection, service error, or bug) leaves no stray upload behind.
        path.unlink(missing_ok=True)
        raise
    logger.info("Uploaded %s as %s", file.filename, doc_id)
    return document


@router.get("/documents", response_model=list[Document])
def list_documents(db: Session = Depends(get_db)) -> list[Document]:
    """All documents, oldest upload first (SQLite rowid follows insertion order)."""
    return [Document.model_validate(row) for row in db.query(DocumentORM).order_by(text("rowid")).all()]


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(doc_id: str, db: Session = Depends(get_db)) -> None:
    """Remove a document everywhere: its row, its chunks in ChromaDB, and the uploaded file.

    Past answers stay in the history; their sources simply no longer list this document.
    """
    row = db.get(DocumentORM, doc_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    vector_store.delete_document(doc_id)
    Path(row.file_path).unlink(missing_ok=True)
    page_store.delete(doc_id)
    db.delete(row)
    db.commit()
    logger.info("Deleted document %s", doc_id)


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


class PageView(BaseModel):
    """What recognition read on one page (API-only, for the document viewer).

    Scanned and handwritten pages list recognised lines; typed pages list blocks.
    """

    page: int
    text: str
    conf: float
    image_url: str | None
    lines: list[LineView]
    blocks: list[BlockView]


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

    document = Document(doc_id=doc_id, file_path=str(path), format_type=format_type, page_count=pages)
    layout: list[dict] = []  # page images + line boxes, filled by OCR/HTR, for the viewer
    try:
        extracted = format_detection.extract(document, layout)
    except file_types.UnreadableFileError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, unreadable)
    except (ocr_extractor.OCRUnavailableError, htr_extractor.HTRUnavailableError) as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))

    chunks = chunker.chunk_pages(doc_id, extracted)
    if not chunks:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No readable text found in this file")
    chunks = confidence_capture.apply_calibration(chunks, format_type)
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
    page_store.save(
        doc_id, str(path), [(t, calibrate(c)) for t, c in extracted], layout, typed=format_type is FormatType.TYPED
    )

    mean_conf = sum(c.calibrated_conf for c in chunks) / len(chunks)
    logger.info(
        "Ingested %s: %s, %d pages, %d chunks, mean calibrated confidence %.2f",
        doc_id, format_type.value, pages, len(chunks), mean_conf,
    )
    return document
