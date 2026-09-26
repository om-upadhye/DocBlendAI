"""Module 7 — LLM Answer Generation.

Responsibility: prompt Gemini with the question and retrieved chunk text,
and return the answer tagged with its reliability label.

Uses from schemas.py: Query, RecognizedChunk, ReliabilityLabel, Answer.
"""

import time
import uuid
from functools import lru_cache

from google import genai
from google.genai import errors, types

from app.config import settings
from app.models.schemas import Answer, Query, RecognizedChunk, ReliabilityLabel
from app.modules.reliability import worse_of

NOT_FOUND = "NOT_FOUND"
NOT_FOUND_ANSWER = "I couldn't find the answer to that in the uploaded documents."
NO_DOCUMENTS_ANSWER = "No documents have been uploaded yet, so there is nothing to answer from."

SYSTEM_INSTRUCTION = (
    "You answer questions about academic documents. Use only the numbered context "
    "passages provided; never use outside knowledge. Be concise and precise. The user "
    "cannot see the passages, so answer directly without mentioning them, the context, "
    "or passage numbers. Passages marked as recognized text come from OCR or handwriting "
    "recognition and contain misread words: answer from the parts that are clearly "
    "readable, and read an obvious misspelling as the intended word when the "
    "surrounding text makes it unambiguous (e.g. 'At system' next to 'AI planning' "
    "means 'AI system'), but never guess at garbled words or add content that is not "
    f"there. If the passages do not contain the answer, reply with exactly {NOT_FOUND}."
)

# Passages below this confidence are flagged to the model as possibly misrecognized.
LOW_CONFIDENCE = 0.95

# Gemini returns these under load (503) or rate limiting (429); worth a short retry.
RETRYABLE_CODES = {429, 500, 503}
MAX_ATTEMPTS = 3


class LLMError(RuntimeError):
    """Answer generation failed: missing API key or a Gemini API error."""


@lru_cache
def _client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def _passage_header(i: int, chunk: RecognizedChunk) -> str:
    notes = [chunk.content_type.value]
    conf = chunk.calibrated_conf if chunk.calibrated_conf is not None else chunk.raw_conf
    if conf < LOW_CONFIDENCE:
        notes.append(f"recognized text, confidence {conf:.2f}: may contain recognition errors")
    return f"[{i}] ({'; '.join(notes)})"


def build_prompt(question: str, chunks: list[RecognizedChunk]) -> str:
    context = "\n\n".join(f"{_passage_header(i, c)}\n{c.text}" for i, c in enumerate(chunks, 1))
    return f"Context passages:\n{context}\n\nQuestion: {question}"


def _generate(prompt: str) -> str:
    if not settings.gemini_api_key:
        raise LLMError("GEMINI_API_KEY is not set (see .env.example)")

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0.0,  # deterministic: the same question on the same text gives the same answer
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = _client(settings.gemini_api_key).models.generate_content(
                model=settings.llm_model, contents=prompt, config=config
            )
            break
        except errors.APIError as e:
            if e.code in RETRYABLE_CODES and attempt < MAX_ATTEMPTS - 1:
                time.sleep(2**attempt)
                continue
            raise LLMError(f"Gemini generation failed: {e}") from e

    if not resp.text:
        raise LLMError("Gemini returned an empty response (possibly blocked)")
    return resp.text.strip()


def generate_answer(
    query: Query,
    chunks: list[RecognizedChunk],
    reliability_label: ReliabilityLabel,
) -> Answer:
    """Generate a grounded answer from the retrieved chunks.

    If the model finds no answer in the chunks, the label is lowered to at
    least Uncertain, whatever retrieval scores suggested.
    """
    answer_id = uuid.uuid4().hex
    if not chunks:
        return Answer(answer_id=answer_id, answer_text=NO_DOCUMENTS_ANSWER, reliability_label=reliability_label)

    text = _generate(build_prompt(query.question_text, chunks))
    if text == NOT_FOUND:
        text = NOT_FOUND_ANSWER
        reliability_label = worse_of(reliability_label, ReliabilityLabel.UNCERTAIN)
    return Answer(answer_id=answer_id, answer_text=text, reliability_label=reliability_label)
