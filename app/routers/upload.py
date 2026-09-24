"""Module 1 — Document Upload.

Responsibility: accept a PDF upload, save it under settings.upload_dir, run
it through extraction -> chunking -> embedding -> ChromaDB, and record a
Document row. Format detection is delegated to Module 2.

Uses from schemas.py: Document, FormatType.
"""

import logging
import shutil
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pdfplumber.utils.exceptions import PdfminerException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db
from app.db.models import DocumentORM
from app.models.schemas import Document, FormatType
from app.modules import chunker, embedder, format_detection, vector_store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["upload"])


# Plain `def` (not async): PDF parsing is blocking, so FastAPI runs this in its threadpool.
@router.post("/upload", response_model=Document, status_code=status.HTTP_201_CREATED)
def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)) -> Document:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF files are supported")

    doc_id = uuid.uuid4().hex
    path = settings.upload_dir / f"{doc_id}.pdf"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    try:
        format_type = format_detection.detect_format(str(path))
        pages = format_detection.page_count(str(path))
    except PdfminerException:
        path.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "File is not a readable PDF")

    if format_type is not FormatType.TYPED:
        # TODO (build step 4): route scanned/handwritten PDFs to OCR/HTR instead of rejecting.
        path.unlink(missing_ok=True)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "No text layer found. Only typed PDFs are supported until OCR/HTR are added.",
        )

    document = Document(doc_id=doc_id, file_path=str(path), format_type=format_type, page_count=pages)
    chunks = chunker.chunk_pages(doc_id, format_detection.extract(document))
    try:
        chunks = embedder.embed_chunks(chunks)
    except embedder.EmbeddingError as e:
        path.unlink(missing_ok=True)
        logger.error("Embedding failed for %s: %s", doc_id, e)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Embedding service failed; try again later")
    vector_store.add_chunks(doc_id, chunks)

    try:
        db.add(DocumentORM(**document.model_dump()))
        db.commit()
    except Exception:
        # Keep ChromaDB and SQLite consistent: no vectors without a Document row.
        vector_store.delete_document(doc_id)
        path.unlink(missing_ok=True)
        raise

    logger.info("Uploaded %s (%s): %d pages, %d chunks stored", file.filename, doc_id, pages, len(chunks))
    return document
