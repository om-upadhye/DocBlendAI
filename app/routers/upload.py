"""Module 1 — Document Upload.

Responsibility: accept a PDF upload, save it under settings.upload_dir, and
record a Document row. Format detection is delegated to Module 2.

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
from app.modules import chunker, format_detection

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
    # TODO (build step 2): embed chunks and store them in ChromaDB via vector_store.add_chunks.
    logger.info("Uploaded %s (%s): %d pages, %d chunks", file.filename, doc_id, pages, len(chunks))

    db.add(DocumentORM(**document.model_dump()))
    db.commit()
    return document
