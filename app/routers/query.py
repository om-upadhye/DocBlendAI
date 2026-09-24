"""Question-answering routes — entry point to Modules 5, 6, 7.

Responsibility: accept a user question, run retrieval -> reliability
classification -> LLM answer generation, and let clients fetch a stored answer.

Uses from schemas.py: Query, Answer.
"""

from fastapi import APIRouter, HTTPException, status

from app.models.schemas import Answer, Query

router = APIRouter(tags=["query"])


@router.post("/ask", response_model=Answer)
async def ask(query: Query) -> Answer:
    # TODO (build step 3): retrieval.retrieve -> reliability.classify_reliability -> llm_answer.generate_answer.
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Ask not implemented yet")


@router.get("/answer/{answer_id}", response_model=Answer)
async def get_answer(answer_id: str) -> Answer:
    # TODO (build step 3): load AnswerORM by id, 404 if missing.
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Answer lookup not implemented yet")
