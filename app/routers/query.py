"""Question-answering routes — entry point to Modules 5, 6, 7.

Responsibility: accept a user question, run retrieval -> reliability
classification -> LLM answer generation, and let clients fetch a stored answer.

Uses from schemas.py: Query, Answer.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db
from app.db.models import AnswerORM, QueryORM, RetrievalResultORM
from app.models.schemas import Answer, Query
from app.modules import embedder, llm_answer, reliability, retrieval

logger = logging.getLogger(__name__)

router = APIRouter(tags=["query"])


# Plain `def`: embedding and generation are blocking network calls, so FastAPI runs this in its threadpool.
@router.post("/ask", response_model=Answer)
def ask(query: Query, db: Session = Depends(get_db)) -> Answer:
    if db.get(QueryORM, query.query_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"query_id {query.query_id!r} already exists")

    try:
        hits = retrieval.retrieve(query, settings.top_k)
        results = [r for _, r in hits]
        label = reliability.classify_reliability(results)
        answer = llm_answer.generate_answer(query, [c for c, _ in hits], label)
    except (embedder.EmbeddingError, llm_answer.LLMError) as e:
        logger.error("Answering %s failed: %s", query.query_id, e)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Gemini service failed; try again later")

    db.add(QueryORM(**query.model_dump()))
    db.add(AnswerORM(**answer.model_dump(), query_id=query.query_id))
    db.add_all(RetrievalResultORM(**r.model_dump(), query_id=query.query_id) for r in results)
    db.commit()

    logger.info("Answered %s: %s from %d chunks", query.query_id, answer.reliability_label.value, len(results))
    return answer


@router.get("/answer/{answer_id}", response_model=Answer)
def get_answer(answer_id: str, db: Session = Depends(get_db)) -> Answer:
    row = db.get(AnswerORM, answer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Answer not found")
    return Answer.model_validate(row)
