"""Tests for the open-source integrations: OpenCV rule removal, docTR line detection and OCR,
TrOCR temperature scaling, Qwen2.5 via Ollama, and the OHRBench-style noise injection.

All offline: docTR models and Ollama are faked (see conftest.offline_engines).
"""

import random
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.config import settings
from app.models.schemas import Query, ReliabilityLabel
from app.modules import confidence_capture, htr_extractor, line_segmentation, llm_answer, ocr_extractor
from evaluation.noise_robustness import inject_ocr_noise
from tests.eval_metrics import cer

# --- OpenCV ruled-line removal -------------------------------------------------------------


def _ruled_page(words_on: list[int], size=(800, 1000), spacing=50, rule_fill=150) -> Image.Image:
    """A notebook page: thin gray rules every `spacing` px, a margin line, and word
    blobs (dark strokes) written just above the rules listed in words_on."""
    page = Image.new("L", size, 250)
    draw = ImageDraw.Draw(page)
    for y in range(spacing, size[1], spacing):
        draw.line((0, y, size[0], y), fill=rule_fill, width=2)
    draw.line((90, 0, 90, size[1]), fill=140, width=2)  # margin
    for rule in words_on:
        y = rule * spacing
        for x in range(120, 600, 70):  # "words": short blocks with a stroke crossing the rule
            draw.rectangle((x, y - 30, x + 45, y - 8), fill=30)
            draw.line((x + 20, y - 30, x + 20, y + 10), fill=30, width=4)
    return page


def test_remove_ruled_lines_erases_rules_and_margin() -> None:
    cleaned = np.asarray(line_segmentation.remove_ruled_lines(_ruled_page([])))
    assert cleaned.min() > 200  # nothing dark left on an unwritten ruled page


def test_remove_ruled_lines_keeps_writing_and_crossing_strokes() -> None:
    page = _ruled_page([4])
    cleaned = np.asarray(line_segmentation.remove_ruled_lines(page))
    assert cleaned[200 - 20, 130] < 80  # inside a word blob, above the rule
    assert cleaned[200 + 1, 140] < 100  # the stroke that crosses the rule stays joined
    assert cleaned[200, 700] > 200  # the rule itself, away from writing, is gone


def test_remove_ruled_lines_on_a_slightly_tilted_scan() -> None:
    """A rule that climbs a few pixels across the page is still thin, so it still goes."""
    page = _ruled_page([]).rotate(0.5, fillcolor=250)
    cleaned = np.asarray(line_segmentation.remove_ruled_lines(page))
    assert cleaned[20:-20, 20:-20].min() > 200


def test_remove_ruled_lines_keeps_thick_bars() -> None:
    """Heavy horizontal ink (a filled bar) is content, not a rule."""
    page = Image.new("L", (800, 1000), 255)
    ImageDraw.Draw(page).rectangle((80, 100, 700, 130), fill=20)
    assert np.asarray(line_segmentation.remove_ruled_lines(page))[115, 400] < 60


def test_rule_removal_keeps_rules_out_of_the_line_images_trocr_reads() -> None:
    """The failure the team hit on real notebook scans, and the fix: without removal, the rule
    under each written line is inside its crop, so the crop spans the whole page width and
    TrOCR reads the rule as strokes."""
    page = _ruled_page([3, 6, 9], rule_fill=100)  # blue rules in a grayscale scan
    raw = htr_extractor.segment_lines(page)
    fixed = htr_extractor.segment_lines(line_segmentation.remove_ruled_lines(page))
    assert all(img.width == page.width for img in raw)  # rule edge to edge
    assert len(fixed) == 3
    assert all(img.width < 520 for img in fixed)  # just the writing (x = 120..575)


def test_find_lines_uses_rule_removal(monkeypatch) -> None:
    lines = htr_extractor.find_lines(_ruled_page([3, 6, 9]))
    assert len(lines) == 3


# --- docTR line detection -------------------------------------------------------------------


def test_group_into_lines_joins_words_top_to_bottom() -> None:
    boxes = [
        (300, 210, 380, 250),  # line 2, second word
        (100, 100, 180, 140),  # line 1
        (200, 105, 280, 138),  # line 1 (slightly different height)
        (100, 205, 190, 252),  # line 2, first word
    ]
    assert line_segmentation.group_into_lines(boxes) == [(100, 100, 280, 140), (100, 205, 380, 252)]


def test_group_into_lines_splits_at_wide_gaps() -> None:
    # Two columns: gap of 500 px on 40 px-tall words.
    boxes = [(50, 100, 150, 140), (160, 100, 250, 140), (750, 100, 850, 140)]
    assert line_segmentation.group_into_lines(boxes) == [(50, 100, 250, 140), (750, 100, 850, 140)]


def test_group_into_lines_empty() -> None:
    assert line_segmentation.group_into_lines([]) == []


def test_detect_lines_crops_detected_lines(monkeypatch) -> None:
    words = np.array([
        [0.1, 0.10, 0.3, 0.14, 0.9],
        [0.35, 0.10, 0.6, 0.14, 0.9],
        [0.1, 0.30, 0.5, 0.34, 0.8],
        [0.7, 0.70, 0.72, 0.71, 0.1],  # low-score speck: dropped
    ])
    monkeypatch.setattr(line_segmentation, "_detector", lambda: lambda pages: [{"words": words}])
    crops = line_segmentation.detect_lines(Image.new("L", (1000, 1000), 255))
    assert len(crops) == 2
    assert crops[0].width > crops[1].width  # first line spans 0.1-0.6, second 0.1-0.5


def test_find_lines_falls_back_to_projection_without_doctr(monkeypatch) -> None:
    monkeypatch.setattr(settings, "htr_segmenter", "doctr")

    def _unavailable():
        raise line_segmentation.LineDetectorUnavailableError("no docTR")

    monkeypatch.setattr(line_segmentation, "_detector", _unavailable)
    assert len(htr_extractor.find_lines(_ruled_page([3, 6]))) == 2


# --- TrOCR temperature scaling (Ayllon et al., ICDAR 2024) ------------------------------------


def _overconfident_samples(true_temperature: float, n_lines=40, tokens=12, vocab=30, seed=0):
    """Logits whose true tokens are drawn from softmax(logits / true_temperature):
    the raw softmax is overconfident by exactly that temperature."""
    rng = np.random.default_rng(seed)
    samples = []
    for _ in range(n_lines):
        logits = rng.normal(0, 4, size=(tokens, vocab))
        z = logits / true_temperature
        p = np.exp(z - z.max(axis=1, keepdims=True))
        p /= p.sum(axis=1, keepdims=True)
        targets = np.array([rng.choice(vocab, p=row) for row in p])
        samples.append((logits, targets))
    return samples


def test_fit_temperature_recovers_overconfidence() -> None:
    samples = _overconfident_samples(2.0)
    t = confidence_capture.fit_temperature(samples)
    assert 1.6 <= t <= 2.5
    assert confidence_capture._nll(samples, t) < confidence_capture._nll(samples, 1.0)


def test_fit_temperature_keeps_calibrated_model_near_one() -> None:
    assert 0.8 <= confidence_capture.fit_temperature(_overconfident_samples(1.0)) <= 1.25


def test_fit_temperature_needs_samples() -> None:
    with pytest.raises(ValueError):
        confidence_capture.fit_temperature([])


# --- docTR OCR engine -------------------------------------------------------------------------


def _word(value, conf):
    return SimpleNamespace(value=value, confidence=conf)


def _doctr_result(blocks):
    lines = lambda block: [SimpleNamespace(words=[_word(*w) for w in line]) for line in block]  # noqa: E731
    return SimpleNamespace(pages=[SimpleNamespace(blocks=[SimpleNamespace(lines=lines(b)) for b in blocks])])


def test_doctr_ocr_rebuilds_text_with_length_weighted_confidence(monkeypatch) -> None:
    result = _doctr_result([[[("Hello", 1.0), ("world", 0.5)]], [[("ab", 0.0)]]])
    monkeypatch.setattr(ocr_extractor, "_doctr_predictor", lambda: lambda pages: result)
    monkeypatch.setattr(settings, "ocr_engine", "doctr")

    text, conf = ocr_extractor.ocr_image(Image.new("L", (100, 100), 255))

    assert text == "Hello world\n\nab"
    assert conf == pytest.approx((5 * 1.0 + 5 * 0.5 + 2 * 0.0) / 12)


def test_doctr_blank_page(monkeypatch) -> None:
    monkeypatch.setattr(ocr_extractor, "_doctr_predictor", lambda: lambda pages: _doctr_result([]))
    monkeypatch.setattr(settings, "ocr_engine", "doctr")
    assert ocr_extractor.ocr_image(Image.new("L", (100, 100), 255)) == ("", 0.0)


def test_auto_engine_uses_doctr_when_tesseract_is_missing(monkeypatch) -> None:
    def _missing(configured):
        raise ocr_extractor.OCRUnavailableError("no tesseract")

    monkeypatch.setattr(settings, "ocr_engine", "auto")
    monkeypatch.setattr(ocr_extractor, "_tesseract_cmd", _missing)
    monkeypatch.setattr(ocr_extractor, "_doctr_ocr", lambda image: ("from doctr", 0.9))
    assert ocr_extractor.ocr_image(Image.new("L", (10, 10), 255)) == ("from doctr", 0.9)


def test_auto_engine_prefers_tesseract_when_installed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ocr_engine", "auto")
    monkeypatch.setattr(ocr_extractor, "_tesseract_cmd", lambda configured: "tesseract")
    monkeypatch.setattr(ocr_extractor, "_tesseract_ocr", lambda image: ("from tesseract", 0.8))
    assert ocr_extractor.ocr_image(Image.new("L", (10, 10), 255)) == ("from tesseract", 0.8)


# --- Qwen2.5 via Ollama (Module 7) -------------------------------------------------------------


class _FakeOllama:
    def __init__(self, status=200, content="Qwen says hi.", error: Exception | None = None):
        self.status, self.content, self.error, self.requests = status, content, error, []

    def post(self, url, json, timeout):
        self.requests.append((url, json))
        if self.error:
            raise self.error
        body = {"message": {"role": "assistant", "content": self.content}}
        return SimpleNamespace(status_code=self.status, json=lambda: body, text="model not found")


def _use_ollama(monkeypatch, fake: _FakeOllama) -> _FakeOllama:
    monkeypatch.setattr(llm_answer.httpx, "post", fake.post)
    return fake


def test_ollama_provider_sends_system_and_prompt(monkeypatch) -> None:
    fake = _use_ollama(monkeypatch, _FakeOllama())
    monkeypatch.setattr(settings, "llm_provider", "ollama")

    assert llm_answer._generate("the prompt") == "Qwen says hi."
    url, body = fake.requests[0]
    assert url.endswith("/api/chat")
    assert body["model"] == settings.ollama_model
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["messages"][1]["content"] == "the prompt"
    assert body["stream"] is False


def test_ollama_missing_model_says_how_to_pull(monkeypatch) -> None:
    _use_ollama(monkeypatch, _FakeOllama(status=404))
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    with pytest.raises(llm_answer.LLMError, match="ollama pull"):
        llm_answer._generate("p")


def test_ollama_not_running(monkeypatch) -> None:
    _use_ollama(monkeypatch, _FakeOllama(error=httpx.ConnectError("refused")))
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    with pytest.raises(llm_answer.LLMError, match="not reachable"):
        llm_answer._generate("p")


def _gemini_fails(monkeypatch):
    def _fail(prompt):
        raise llm_answer.LLMError("Gemini quota exhausted (429)")

    monkeypatch.setattr(llm_answer, "_generate_gemini", _fail)


def test_gemini_failure_falls_back_to_qwen(monkeypatch) -> None:
    _gemini_fails(monkeypatch)
    _use_ollama(monkeypatch, _FakeOllama(content="Local answer."))
    monkeypatch.setattr(settings, "llm_fallback_to_ollama", True)
    assert llm_answer._generate("p") == "Local answer."


def test_fallback_failure_reports_both_errors(monkeypatch) -> None:
    _gemini_fails(monkeypatch)
    _use_ollama(monkeypatch, _FakeOllama(error=httpx.ConnectError("refused")))
    monkeypatch.setattr(settings, "llm_fallback_to_ollama", True)
    with pytest.raises(llm_answer.LLMError, match="quota.*Ollama fallback also failed"):
        llm_answer._generate("p")


def test_no_fallback_when_disabled(monkeypatch) -> None:
    _gemini_fails(monkeypatch)
    fake = _use_ollama(monkeypatch, _FakeOllama())
    with pytest.raises(llm_answer.LLMError, match="quota"):
        llm_answer._generate("p")
    assert fake.requests == []


@pytest.mark.parametrize("reply", ["NOT_FOUND", "NOT_FOUND.", '"NOT_FOUND"', "not_found", "**NOT_FOUND**"])
def test_not_found_marker_tolerates_small_model_formatting(monkeypatch, reply) -> None:
    from app.models.schemas import RecognizedChunk

    monkeypatch.setattr(llm_answer, "_generate", lambda prompt: reply)
    answer = llm_answer.generate_answer(
        Query(query_id="q", question_text="?", user_id="u"),
        [RecognizedChunk(chunk_id="d:0", text="t", raw_conf=1.0, calibrated_conf=1.0)],
        ReliabilityLabel.CERTAIN,
    )
    assert answer.answer_text == llm_answer.NOT_FOUND_ANSWER
    assert answer.reliability_label is ReliabilityLabel.UNCERTAIN


# --- OHRBench-style noise injection -------------------------------------------------------------

TEXT = "Retrieval-Augmented Generation combines a retriever with a language model. " * 10


def test_noise_rate_zero_is_identity() -> None:
    assert inject_ocr_noise(TEXT, 0.0, random.Random(1)) == TEXT


def test_noise_is_deterministic_for_a_seed() -> None:
    assert inject_ocr_noise(TEXT, 0.2, random.Random(3)) == inject_ocr_noise(TEXT, 0.2, random.Random(3))


def test_noise_levels_give_increasing_error_rates() -> None:
    rates = [cer(TEXT, inject_ocr_noise(TEXT, r, random.Random(5))) for r in (0.05, 0.15, 0.30)]
    assert rates == sorted(rates)
    assert 0.02 <= rates[0] <= 0.1
    assert 0.18 <= rates[2] <= 0.4
