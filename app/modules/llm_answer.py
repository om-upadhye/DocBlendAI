"""Module 7 — LLM Answer Generation.

Responsibility: prompt an LLM with the question and retrieved chunk text,
and return the answer tagged with its reliability label.

Two providers (settings.llm_provider), as the synopsis names:
- Gemini (google-genai SDK), the default.
- Qwen2.5 (QwenLM/Qwen2.5), an open-weight model run locally through Ollama
  (ollama/ollama). No API key or quota. With the Gemini provider it is also
  the fallback when Gemini is unavailable (settings.llm_fallback_to_ollama).

Uses from schemas.py: Query, RecognizedChunk, ReliabilityLabel, Answer.
"""

import logging
import time
import uuid
from functools import lru_cache

import httpx
from google import genai
from google.genai import errors, types

from app.config import settings
from app.models.schemas import Answer, Query, RecognizedChunk, ReliabilityLabel
from app.modules.reliability import worse_of

logger = logging.getLogger(__name__)

NOT_FOUND = "NOT_FOUND"
NOT_FOUND_ANSWER = "I couldn't find the answer to that in the uploaded documents."
NO_DOCUMENTS_ANSWER = "No documents have been uploaded yet, so there is nothing to answer from."

SYSTEM_INSTRUCTION = (
    "You answer questions about academic documents. Use only the numbered context "
    "passages provided; never use outside knowledge. Be concise and precise. The user "
    "cannot see the passages, so answer directly without mentioning them, the context, "
    "or passage numbers. Passages marked as recognized text may contain OCR or "
    "handwriting errors: do not guess at garbled words. If the "
    f"passages do not contain the answer, reply with exactly {NOT_FOUND}."
)

# Passages below this confidence are flagged to the model as possibly misrecognized.
LOW_CONFIDENCE = 0.95

# A local model on a CPU laptop can take a minute or more for one answer.
OLLAMA_TIMEOUT_SECONDS = 300

# Gemini returns these under load (503) or rate limiting (429); worth a short retry.
RETRYABLE_CODES = {429, 500, 503}
MAX_ATTEMPTS = 3


class LLMError(RuntimeError):
    """Answer generation failed: missing API key, a Gemini API error, or Ollama unreachable."""


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
    """Answer with the configured provider (falling back from Gemini to Ollama if enabled)."""
    if settings.llm_provider == "ollama":
        return _generate_ollama(prompt)
    try:
        return _generate_gemini(prompt)
    except LLMError as e:
        if not settings.llm_fallback_to_ollama:
            raise
        logger.warning("%s; answering with %s via Ollama instead", e, settings.ollama_model)
        try:
            return _generate_ollama(prompt)
        except LLMError as fallback_error:
            raise LLMError(f"{e} (Ollama fallback also failed: {fallback_error})") from e


def _generate_ollama(prompt: str) -> str:
    """Answer with a local open model (Qwen2.5 by default) through Ollama's chat API."""
    try:
        resp = httpx.post(
            f"{settings.ollama_url.rstrip('/')}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.2},
            },
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as e:
        raise LLMError(f"Ollama is not reachable at {settings.ollama_url} (is it installed and running?): {e}") from e
    if resp.status_code == 404:
        raise LLMError(f"Ollama has no model {settings.ollama_model!r}; run: ollama pull {settings.ollama_model}")
    if resp.status_code != 200:
        raise LLMError(f"Ollama generation failed ({resp.status_code}): {resp.text[:200]}")
    text = (resp.json().get("message") or {}).get("content", "").strip()
    if not text:
        raise LLMError("Ollama returned an empty response")
    return text


def _generate_gemini(prompt: str) -> str:
    if not settings.gemini_api_key:
        raise LLMError("GEMINI_API_KEY is not set (see .env.example)")

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0.2,
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
    # Smaller local models sometimes add punctuation or quotes around the marker.
    if text.strip(" .\"'`*").upper() == NOT_FOUND:
        text = NOT_FOUND_ANSWER
        reliability_label = worse_of(reliability_label, ReliabilityLabel.UNCERTAIN)
    return Answer(answer_id=answer_id, answer_text=text, reliability_label=reliability_label)
