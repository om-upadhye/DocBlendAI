"""Question-answering routes — entry point to Modules 5, 6, 7.

Responsibility: accept a user question, run retrieval -> reliability
classification -> LLM answer generation, and let clients fetch a stored answer.

Uses from schemas.py: Query, Answer.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field
from sqlalchemy.orm import Session

from app import site
from app.config import settings
from app.db.database import get_db
from app.db.models import AnswerORM, DocumentORM, QueryORM, RetrievalResultORM
from app.models.schemas import Answer, ContentType, Query, ReliabilityLabel, RetrievalResult
from app.modules import embedder, llm_answer, page_store, reliability, retrieval, vector_store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["query"])


class AskRequest(Query):
    """A Query plus which documents to answer from.

    API-only (the synopsis Query entity stays unchanged): doc_ids restricts
    retrieval to those documents, so a question about a newly uploaded file is
    not answered from older ones. Omit it to search every document.
    """

    doc_ids: list[str] | None = Field(
        default=None, description="Answer only from these documents; omit to search all documents."
    )


# Plain `def`: embedding and generation are blocking network calls, so FastAPI runs this in its threadpool.
@router.post("/ask", response_model=Answer)
def ask(
    request: AskRequest, db: Session = Depends(get_db), session_id: str | None = Depends(site.session_header)
) -> Answer:
    query = Query(**request.model_dump(exclude={"doc_ids"}))
    visible = site.visible_doc_ids(db, session_id)
    if visible is not None:  # public demo: only this session's own documents
        if request.doc_ids is None:
            request.doc_ids = sorted(visible)
        if not request.doc_ids:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Upload a document first")
    if db.get(QueryORM, query.query_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"query_id {query.query_id!r} already exists")
    if request.doc_ids is not None:
        if not request.doc_ids:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Select at least one document to ask about")
        known = {row.doc_id for row in db.query(DocumentORM.doc_id).filter(DocumentORM.doc_id.in_(request.doc_ids))}
        unknown = sorted(set(request.doc_ids) - (known if visible is None else known & visible))
        if unknown:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown document(s): {', '.join(unknown)}")

    try:
        hits = retrieval.retrieve(query, settings.top_k, request.doc_ids)
        results = [r for _, r in hits]
        label = reliability.classify_reliability(results)
        answer = llm_answer.generate_answer(query, [c for c, _ in hits], label)
        if settings.visual_recheck and answer.reliability_label in UNSURE and hits:
            answer = _recheck(query, hits) or answer
    except (embedder.EmbeddingError, llm_answer.LLMError) as e:
        logger.error("Answering %s failed: %s", query.query_id, e)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Gemini service failed; try again later")

    db.add(QueryORM(**query.model_dump()))
    db.add(AnswerORM(**answer.model_dump(), query_id=query.query_id))
    db.add_all(RetrievalResultORM(**r.model_dump(), query_id=query.query_id) for r in results)
    db.commit()
    site.count_question(db)

    logger.info("Answered %s: %s from %d chunks", query.query_id, answer.reliability_label.value, len(results))
    return answer


UNSURE = (ReliabilityLabel.UNCERTAIN, ReliabilityLabel.UNREADABLE)


def _recheck(query: Query, hits: list) -> Answer | None:
    """Uncertain answer from scanned / handwritten notes: look at the pages of the best passages again."""
    from PIL import Image

    by_doc: dict[str, list[str]] = {}
    for chunk, _ in hits:
        by_doc.setdefault(chunk.chunk_id.rsplit(":", 1)[0], []).append(chunk.text)
    paths = []
    for doc_id, texts in by_doc.items():
        paths += page_store.page_images_for(doc_id, texts, limit=2 - len(paths))
        if len(paths) >= 2:
            break
    if not paths:  # typed documents: no page images, nothing more to see
        return None
    images = [Image.open(p) for p in paths]
    try:
        better = llm_answer.recheck_with_pages(query, [c for c, _ in hits], images)
    finally:
        for img in images:
            img.close()
    if better:
        logger.info("Answer for %s recovered from %d page image(s)", query.query_id, len(paths))
    return better


@router.get("/answer/{answer_id}", response_model=Answer)
def get_answer(answer_id: str, db: Session = Depends(get_db)) -> Answer:
    row = db.get(AnswerORM, answer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Answer not found")
    return Answer.model_validate(row)


class AnswerSource(RetrievalResult):
    """A retrieved chunk behind an answer: its scores plus the text itself.

    API-only view (not a synopsis entity): lets users see why an answer got
    its reliability label.
    """

    doc_id: str
    content_type: ContentType
    text: str


@router.get("/answer/{answer_id}/sources", response_model=list[AnswerSource])
def get_answer_sources(answer_id: str, db: Session = Depends(get_db)) -> list[AnswerSource]:
    """Retrieved chunks for an answer, best combined_score first."""
    row = db.get(AnswerORM, answer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Answer not found")
    results = (
        db.query(RetrievalResultORM)
        .filter_by(query_id=row.query_id)
        .order_by(RetrievalResultORM.combined_score.desc())
        .all()
    )
    chunks = vector_store.get_chunks([r.chunk_id for r in results])
    sources = []
    for r in results:
        chunk = chunks.get(r.chunk_id)
        if chunk is None:  # document deleted since the question was asked
            continue
        sources.append(
            AnswerSource(
                **RetrievalResult.model_validate(r).model_dump(),
                doc_id=r.chunk_id.rsplit(":", 1)[0],
                content_type=chunk.content_type,
                text=chunk.text,
            )
        )
    return sources
