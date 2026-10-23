"""Vision reading of hard pages: honest confidence from agreement, ingestion, and the answer recheck."""

import json

import pytest

from app.config import settings
from app.models.schemas import ReliabilityLabel
from app.modules import llm_answer, ocr_extractor, vector_store, vision_reader

REPLY = """ADD steps:
1) Choose an element of design
2) Identify Architectural Drivers
- portability & [security?] and [?]
IGNORED: phone status bar, bank stamp
LEGIBILITY: 80"""


def test_parse_reply_separates_notes_legibility_and_ignored() -> None:
    text, legibility, ignored = vision_reader.parse_reply(REPLY)
    assert text.splitlines()[0] == "ADD steps:" and "IGNORED" not in text and "LEGIBILITY" not in text
    assert legibility == 0.8 and ignored == "phone status bar, bank stamp"


def test_agreement_confirms_words_ocr_also_saw_and_doubts_the_rest() -> None:
    ocr = "ADD stops Choose an elemnt of desgn Identfy Architectral Drivers portability".split()
    conf, counts = vision_reader.agreement("ADD steps Choose an element of design Identify Architectural Drivers portability", ocr)
    assert counts["inferred"] == 0 and conf == pytest.approx(vision_reader.CONFIRMED)

    conf_unseen, counts = vision_reader.agreement("Quantum chromodynamics lattice", ocr)  # OCR saw none of it
    assert counts["confirmed"] == 0 and conf_unseen == pytest.approx(vision_reader.INFERRED)

    conf_marked, counts = vision_reader.agreement("portability [securty?] [?]", ocr)
    assert counts == {"confirmed": 1, "inferred": 0, "doubtful": 1, "unread": 1} and conf_marked < 0.7  # far below fully confirmed (0.95)


def test_glued_ocr_words_still_confirm() -> None:
    _, counts = vision_reader.agreement("memory leak", ["memoryIdableak"])
    assert counts["confirmed"] == 1


def test_should_read_auto_mode(monkeypatch) -> None:
    monkeypatch.setattr(settings, "vision_read", "auto")
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    assert vision_reader.should_read("handwritten", 0.99)
    assert vision_reader.should_read("scanned", 0.7) and not vision_reader.should_read("scanned", 0.95)
    assert not vision_reader.should_read("typed", 0.1)
    monkeypatch.setattr(settings, "gemini_api_key", "")
    assert not vision_reader.should_read("handwritten", 0.1)


def test_model_falls_back_when_the_first_is_out_of_quota(monkeypatch) -> None:
    from google.genai import errors

    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    calls = []

    def _call(model, image, prompt):
        calls.append(model)
        if model == settings.vision_model:
            raise errors.APIError(429, {"error": {"message": "quota"}})
        return REPLY

    monkeypatch.setattr(vision_reader, "_call", _call)
    from PIL import Image

    read = vision_reader.read_page(Image.new("L", (100, 100), 255), [{"text": "ADD steps Choose an element"}])
    assert calls == [settings.vision_model, settings.vision_fallback_model] and read.model == settings.vision_fallback_model
    assert read.raw_conf <= 0.5 + 0.8 / 2  # never above what the model itself claims to have read


# --- ingestion -------------------------------------------------------------------------------


@pytest.fixture
def garbled_scan(monkeypatch):
    """OCR reads the page as confident garbage; the vision model reads it properly."""
    def _ocr_image(image, lines_out=None):
        if lines_out is not None:
            lines_out.append({"text": "ADD stps Chose an elemnt", "conf": 0.8, "box": [0.1, 0.1, 0.9, 0.2]})
        return "ADD stps Chose an elemnt", 0.8

    monkeypatch.setattr(ocr_extractor, "ocr_image", _ocr_image)
    monkeypatch.setattr(settings, "vision_read", "always")
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(vision_reader, "_call", lambda model, image, prompt: REPLY)


def test_vision_text_replaces_ocr_with_an_agreement_confidence(client, pdf_file, garbled_scan) -> None:
    with pdf_file([""]).open("rb") as f:
        resp = client.post("/upload", files={"file": ("notes.pdf", f, "application/pdf")}, data={"format_hint": "scanned"})
    assert resp.status_code == 201, resp.text
    doc_id = resp.json()["doc_id"]

    [page] = client.get(f"/documents/{doc_id}/pages").json()
    assert page["text"].startswith("ADD steps:") and "IGNORED" not in page["text"]
    chunk = vector_store.get_chunks([f"{doc_id}:0"])[f"{doc_id}:0"]
    assert "Identify Architectural Drivers" in chunk.text
    # Most words were not confirmed by OCR and two are marked unsure: clearly below "Certain".
    assert chunk.calibrated_conf == chunk.raw_conf < 0.85


def test_vision_failure_keeps_the_ocr_text(client, pdf_file, garbled_scan, monkeypatch) -> None:
    def _down(model, image, prompt):
        raise vision_reader.VisionUnavailableError("offline")

    monkeypatch.setattr(vision_reader, "read_page", lambda image, lines: (_ for _ in ()).throw(vision_reader.VisionUnavailableError("offline")))
    with pdf_file([""]).open("rb") as f:
        resp = client.post("/upload", files={"file": ("notes.pdf", f, "application/pdf")}, data={"format_hint": "scanned"})
    assert resp.status_code == 201
    [page] = client.get(f"/documents/{resp.json()['doc_id']}/pages").json()
    assert page["text"] == "ADD stps Chose an elemnt"


# --- answer recheck against the page image ---------------------------------------------------


def test_uncertain_answer_is_rechecked_against_the_page(client, pdf_file, garbled_scan, monkeypatch) -> None:
    with pdf_file([""]).open("rb") as f:
        doc_id = client.post("/upload", files={"file": ("notes.pdf", f, "application/pdf")}, data={"format_hint": "scanned"}).json()["doc_id"]
    monkeypatch.setattr(settings, "visual_recheck", True)
    monkeypatch.setattr(llm_answer, "_generate", lambda prompt: llm_answer.NOT_FOUND)  # text pass gives up
    seen = {}

    def _ask(prompt, images):
        seen["images"] = len(images)
        return "The first ADD step is to choose an element of the design.\nSUPPORT: FULL", "vision-model"

    monkeypatch.setattr(vision_reader, "ask_with_images", _ask)
    resp = client.post("/ask", json={"query_id": "q1", "question_text": "What is the first ADD step?", "user_id": "u", "doc_ids": [doc_id]})

    answer = resp.json()
    assert seen["images"] == 1
    assert answer["answer_text"].startswith("The first ADD step") and llm_answer.RECHECKED_NOTE in answer["answer_text"]
    assert answer["reliability_label"] == ReliabilityLabel.MODERATE.value  # one reader only: never Certain


def test_recheck_that_finds_nothing_keeps_the_original_answer(client, pdf_file, garbled_scan, monkeypatch) -> None:
    with pdf_file([""]).open("rb") as f:
        doc_id = client.post("/upload", files={"file": ("notes.pdf", f, "application/pdf")}, data={"format_hint": "scanned"}).json()["doc_id"]
    monkeypatch.setattr(settings, "visual_recheck", True)
    monkeypatch.setattr(llm_answer, "_generate", lambda prompt: llm_answer.NOT_FOUND)
    monkeypatch.setattr(vision_reader, "ask_with_images", lambda prompt, images: (llm_answer.NOT_FOUND, "vision-model"))
    resp = client.post("/ask", json={"query_id": "q2", "question_text": "Who won the 1998 world cup?", "user_id": "u", "doc_ids": [doc_id]})
    assert resp.json()["answer_text"] == llm_answer.NOT_FOUND_ANSWER
    assert resp.json()["reliability_label"] == ReliabilityLabel.UNCERTAIN.value
