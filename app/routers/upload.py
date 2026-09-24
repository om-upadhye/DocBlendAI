"""Module 1 — Document Upload.

Responsibility: accept a PDF upload, save it under settings.upload_dir, and
record a Document row. Format detection is delegated to Module 2.

Uses from schemas.py: Document.
"""

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.models.schemas import Document

router = APIRouter(tags=["upload"])


@router.post("/upload", response_model=Document, status_code=status.HTTP_201_CREATED)
async def upload_document(file: UploadFile = File(...)) -> Document:
    # TODO (build step 1): save file, call format_detection.detect_format, persist DocumentORM.
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Upload not implemented yet")
