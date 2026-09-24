"""Module 1 — Document Upload.

Responsibility: accept a PDF upload, save it under settings.upload_dir, run
it through detection -> extraction (parse/OCR/HTR) -> chunking ->
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
from pdfplumber.utils.exceptions import PdfminerException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db
from app.db.models import DocumentORM
from app.models.schemas import Document, FormatType
from app.modules import (
    chunker,
    confidence_capture,
    content_type,
    embedder,
    format_detection,
    htr_extractor,
    ocr_extractor,
    vector_store,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["upload"])


# Plain `def` (not async): PDF parsing, OCR, and HTR are blocking, so FastAPI runs this in its threadpool.
@router.post("/upload", response_model=Document, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    format_hint: FormatType | None = Form(
        None, description="Skip automatic detection and force this format (e.g. if detection guesses wrong)."
    ),
    db: Session = Depends(get_db),
) -> Document:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF files are supported")

    doc_id = uuid.uuid4().hex
    # Keep the original name in the stored path so the UI can show it (the Document entity has no name field).
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(file.filename).stem)[:80] or "document"
    path = settings.upload_dir / f"{doc_id}_{safe_name}.pdf"
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
    return [Document.model_validate(row) for row in db.query(DocumentORM).all()]


def _ingest(doc_id: str, path: Path, format_hint: FormatType | None, db: Session) -> Document:
    """Detect -> extract -> chunk -> calibrate -> label -> embed -> store. Raises HTTPException on expected failures."""
    try:
        pages = format_detection.page_count(str(path))
        format_type = format_hint or format_detection.detect_format(str(path))
    except PdfminerException:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "File is not a readable PDF")
    except (ocr_extractor.OCRUnavailableError, htr_extractor.HTRUnavailableError) as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))

    document = Document(doc_id=doc_id, file_path=str(path), format_type=format_type, page_count=pages)
    try:
        extracted = format_detection.extract(document)
    except (ocr_extractor.OCRUnavailableError, htr_extractor.HTRUnavailableError) as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))

    chunks = chunker.chunk_pages(doc_id, extracted)
    if not chunks:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No readable text found in this PDF")
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

    mean_conf = sum(c.calibrated_conf for c in chunks) / len(chunks)
    logger.info(
        "Ingested %s: %s, %d pages, %d chunks, mean calibrated confidence %.2f",
        doc_id, format_type.value, pages, len(chunks), mean_conf,
    )
    return document
