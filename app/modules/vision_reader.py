"""Supports Modules 2 and 3 — reading hard pages with a vision model, with an honest confidence.

Responsibility: handwritten notes and photographed pages often defeat OCR (cursive, highlighter,
pencil, stamps or a rotated receipt on the same page), and OCR engines stay confident about
garbage. Such pages are read by a Gemini vision model, which reads whole words in context:
- the model transcribes only the study notes, sets aside stamps / receipts / phone screen UI,
  and marks what it cannot read: [word?] for a best guess, [?] for unreadable
- the transcription's confidence comes from agreement with an independent reader: each word is
  checked against the words the page's OCR found. Words both readers saw count as confirmed;
  words only the vision model saw count as inferred; [word?] / [?] count as doubtful / unread.
  Vision models fail by writing fluent, plausible text that is not on the page, so their own
  fluency is never taken as confidence.

The model is settings.vision_model (best reading), falling back to settings.vision_fallback_model
when its quota is used up or it fails.

Uses from schemas.py: nothing directly; returns (text, raw_conf) like the other extractors.
"""

import io
import logging
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher, get_close_matches
from functools import lru_cache

from PIL import Image

from app.config import settings

logger = logging.getLogger(__name__)

PROMPT = """You are transcribing a photographed page of study notes for a search system.
Rules:
- Transcribe ONLY the study notes (handwritten or printed), in reading order, keeping headings, numbered
  steps, lists and line breaks. Keep margin notes, after the main notes, under "[Margin notes]".
- Do not transcribe phone screen UI (status bar, buttons), rubber stamps, or rotated / upside-down
  printed text that is not part of the notes (receipts, forms). Name them on ONE line starting "IGNORED:".
- Highlighted words are important: keep them.
- Never invent or complete text. If a word is partly readable, write your best reading in square
  brackets with a question mark, e.g. [architecture?]. If a word cannot be read, write [?].
- Keep the writer's abbreviations; do not expand them or add explanations.
Last line, exactly: LEGIBILITY: <0-100> (your honest estimate of how much of the notes you read confidently)."""

# Confidence of a word by how it was read (see module docstring).
CONFIRMED, INFERRED, DOUBTFUL, UNREAD = 0.95, 0.6, 0.35, 0.0
MATCH_CUTOFF = 0.72  # how close an OCR word must be to count as the same word (OCR misspells a lot)
MAX_IMAGE_SIDE = 2000
RETRYABLE = {429, 500, 503}

_UNCERTAIN = re.compile(r"\[([^\]]*?)\?\]")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'&.-]*|\d+")


class VisionUnavailableError(RuntimeError):
    """No vision model could read the page (no key, quota used up, or service errors)."""


@dataclass
class VisionRead:
    text: str
    raw_conf: float
    legibility: float | None
    model: str
    ignored: str = ""
    words: dict = field(default_factory=dict)  # counts: confirmed / inferred / doubtful / unread


@lru_cache
def _client(api_key: str):
    from google import genai

    return genai.Client(api_key=api_key)


def _image_bytes(image: Image.Image) -> bytes:
    img = image.convert("RGB")
    img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def _call(model: str, image: bytes, prompt: str) -> str:
    """One vision request (retried briefly on overload). Raises google.genai errors.APIError."""
    from google.genai import errors, types

    config = types.GenerateContentConfig(
        temperature=0.0, automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
    )
    for attempt in range(2):
        try:
            resp = _client(settings.gemini_api_key).models.generate_content(
                model=model, contents=[types.Part.from_bytes(data=image, mime_type="image/jpeg"), prompt], config=config
            )
            return (resp.text or "").strip()
        except errors.APIError as e:
            if e.code in (500, 503) and attempt == 0:
                time.sleep(2)
                continue
            raise
    return ""


def ask_with_images(prompt: str, images: list[Image.Image]) -> tuple[str, str]:
    """Send a prompt with page images to the vision model (fallback model on failure). Returns (reply, model)."""
    if not settings.gemini_api_key:
        raise VisionUnavailableError("GEMINI_API_KEY is not set")
    from google.genai import errors, types

    parts = [types.Part.from_bytes(data=_image_bytes(img), mime_type="image/jpeg") for img in images]
    config = types.GenerateContentConfig(
        temperature=0.0, automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
    )
    last: Exception | None = None
    for model in _models():
        try:
            resp = _client(settings.gemini_api_key).models.generate_content(model=model, contents=[*parts, prompt], config=config)
            if resp.text:
                return resp.text.strip(), model
        except errors.APIError as e:
            last = e
            logger.warning("Vision model %s failed (%s); trying the next one", model, e.code)
    raise VisionUnavailableError(f"no vision model answered: {last}")


def _models() -> list[str]:
    return [m for m in (settings.vision_model, settings.vision_fallback_model) if m]


def parse_reply(reply: str) -> tuple[str, float | None, str]:
    """(notes text, legibility 0-1 or None, ignored note) from the model's reply."""
    legibility, ignored, keep = None, [], []
    for line in reply.splitlines():
        stripped = line.strip().strip("*").strip()
        if m := re.match(r"LEGIBILITY:\s*(\d{1,3})", stripped, re.IGNORECASE):
            legibility = min(100, int(m.group(1))) / 100
        elif stripped.upper().startswith("IGNORED:"):
            ignored.append(stripped[8:].strip())
        elif stripped != "---":
            keep.append(line.rstrip())
    text = "\n".join(keep).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text, legibility, " ".join(ignored)


def agreement(text: str, ocr_words: list[str]) -> tuple[float, dict]:
    """Confidence of a transcription from agreement with OCR's words (see module docstring)."""
    vocab = sorted({w.lower() for w in ocr_words if len(w) > 1})
    counts = {"confirmed": 0, "inferred": 0, "doubtful": 0, "unread": 0}
    score = chars = 0.0

    def add(kind: str, value: float, weight: int) -> None:
        nonlocal score, chars
        counts[kind] += 1
        score += value * weight
        chars += weight

    for m in _UNCERTAIN.finditer(text):  # [word?] and [?]
        guess = m.group(1).strip()
        add("doubtful" if guess else "unread", DOUBTFUL if guess else UNREAD, max(3, len(guess)))
    plain = _UNCERTAIN.sub(" ", text)
    for word in _WORD.findall(plain):
        w = word.lower().strip(".-'")
        if len(w) < 2:
            continue
        exact = w in vocab
        close = exact or bool(get_close_matches(w, vocab, n=1, cutoff=MATCH_CUTOFF)) or _inside_ocr(w, vocab)
        add("confirmed" if close else "inferred", CONFIRMED if close else INFERRED, len(w))
    return (round(score / chars, 4) if chars else 0.0), counts


def _inside_ocr(word: str, vocab: list[str]) -> bool:
    """OCR often glues words together ('memoryIdableak'): a long word found inside one counts."""
    if len(word) < 5:
        return False
    return any(len(v) > len(word) and SequenceMatcher(None, word, v).find_longest_match(0, len(word), 0, len(v)).size >= len(word) - 1 for v in vocab)


def read_page(image: Image.Image, ocr_lines: list[dict]) -> VisionRead:
    """Transcribe one page image. Raises VisionUnavailableError if no model could read it."""
    if not settings.gemini_api_key:
        raise VisionUnavailableError("GEMINI_API_KEY is not set")
    from google.genai import errors

    data = _image_bytes(image)
    last: Exception | None = None
    for model in _models():
        try:
            reply = _call(model, data, PROMPT)
        except errors.APIError as e:
            last = e
            logger.warning("Vision model %s could not read the page (%s); trying the next one", model, e.code)
            continue
        text, legibility, ignored = parse_reply(reply)
        if not text:
            last = VisionUnavailableError(f"{model} returned no text")
            continue
        ocr_words = [w for line in ocr_lines for w in _WORD.findall(line.get("text", ""))]
        conf, counts = agreement(text, ocr_words)
        if legibility is not None:  # the model's own estimate can only lower the score
            conf = min(conf, round(0.5 + legibility / 2, 4))
        logger.info("Vision read with %s: confidence %.2f, legibility %s, words %s", model, conf, legibility, counts)
        return VisionRead(text=text, raw_conf=conf, legibility=legibility, model=model, ignored=ignored, words=counts)
    raise VisionUnavailableError(f"no vision model could read the page: {last}")


def should_read(format_type: str, ocr_conf: float) -> bool:
    """Which pages go to the vision model (settings.vision_read: auto | always | off)."""
    mode = settings.vision_read
    if mode == "off" or not settings.gemini_api_key:
        return False
    if mode == "always":
        return format_type in ("scanned", "handwritten")
    # auto: every handwritten page; printed scans only when OCR found them hard
    return format_type == "handwritten" or (format_type == "scanned" and ocr_conf < settings.vision_min_ocr_conf)
