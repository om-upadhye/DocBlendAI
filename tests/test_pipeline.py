"""Pipeline tests, grouped by module (1-7).

Modules not built yet are skipped; un-skip and fill in as the build order in
CLAUDE.md progresses.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from app.config import settings
from app.db.models import DocumentORM
from app.models.schemas import Document, FormatType, RecognizedChunk
from app.modules import chunker, embedder, format_detection, text_parser, vector_store
from tests.conftest import TYPED_PAGE, fake_embed

not_built = pytest.mark.skip(reason="module not implemented yet")


# --- Module 1: Document Upload ---------------------------------------------


def test_module1_upload_saves_document(client, pdf_file, db_session_factory) -> None:
    path = pdf_file([TYPED_PAGE, TYPED_PAGE])

    with path.open("rb") as f:
        resp = client.post("/upload", files={"file": ("notes.pdf", f, "application/pdf")})

    assert resp.status_code == 201
    doc = Document.model_validate(resp.json())
    assert doc.format_type is FormatType.TYPED
    assert doc.page_count == 2
    assert Path(doc.file_path).is_file()
    with db_session_factory() as db:
        assert db.get(DocumentORM, doc.doc_id) is not None


def test_module1_rejects_non_pdf(client) -> None:
    resp = client.post("/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert resp.status_code == 415


def test_module1_rejects_corrupt_pdf_and_cleans_up(client, tmp_path) -> None:
    resp = client.post("/upload", files={"file": ("broken.pdf", b"not a pdf", "application/pdf")})
    assert resp.status_code == 422
    assert not any((tmp_path / "uploads").iterdir())


def test_module1_rejects_pdf_without_text_layer(client, pdf_file, tmp_path) -> None:
    with pdf_file(["", ""]).open("rb") as f:
        resp = client.post("/upload", files={"file": ("scan.pdf", f, "application/pdf")})
    assert resp.status_code == 422
    assert not any((tmp_path / "uploads").iterdir())


# --- Module 2: Format Detection & Text Extraction ---------------------------


def test_module2_detects_typed_pdf(pdf_file) -> None:
    assert format_detection.detect_format(str(pdf_file([TYPED_PAGE]))) is FormatType.TYPED


def test_module2_pdf_without_text_is_not_typed(pdf_file) -> None:
    assert format_detection.detect_format(str(pdf_file(["", "", TYPED_PAGE]))) is not FormatType.TYPED


def test_module2_text_parser_returns_page_text_with_full_confidence(pdf_file) -> None:
    pages = text_parser.parse_pdf(str(pdf_file([TYPED_PAGE, ""])))

    assert len(pages) == 2
    assert "Retrieval-Augmented Generation" in pages[0][0]
    assert pages[1][0] == ""
    assert all(conf == 1.0 for _, conf in pages)


def test_module2_extract_routes_typed_to_text_parser(pdf_file) -> None:
    path = str(pdf_file([TYPED_PAGE]))
    doc = Document(doc_id="d", file_path=path, format_type=FormatType.TYPED, page_count=1)
    assert format_detection.extract(doc) == text_parser.parse_pdf(path)


# --- Chunker (supports Modules 4/5) ----------------------------------------


def test_chunker_short_page_is_one_chunk() -> None:
    chunks = chunker.chunk_pages("doc", [("A short page.", 0.9)])

    assert len(chunks) == 1
    assert chunks[0].chunk_id == "doc:0"
    assert chunks[0].text == "A short page."
    assert chunks[0].raw_conf == 0.9


def test_chunker_respects_size_and_overlap() -> None:
    words = [f"word{i}" for i in range(400)]
    chunks = chunker.chunk_pages("doc", [(" ".join(words), 1.0)], chunk_size=200, overlap=50)

    assert len(chunks) > 1
    assert all(len(c.text) <= 200 for c in chunks)
    # Consecutive chunks share words (the overlap) ...
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.text.split()[0] in prev.text.split()
    # ... and together they cover every word, in order.
    assert set(words) == {w for c in chunks for w in c.text.split()}


def test_chunker_skips_empty_pages_and_numbers_ids_across_pages() -> None:
    chunks = chunker.chunk_pages("doc", [("Page one.", 1.0), ("", 1.0), ("Page three.", 0.5)])

    assert [c.chunk_id for c in chunks] == ["doc:0", "doc:1"]
    assert [c.raw_conf for c in chunks] == [1.0, 0.5]


def test_chunker_preserves_line_breaks() -> None:
    chunks = chunker.chunk_pages("doc", [("Name  Marks\nAsha  91\nRavi  84", 1.0)])
    assert chunks[0].text == "Name  Marks\nAsha  91\nRavi  84"


def test_chunker_rejects_overlap_not_smaller_than_size() -> None:
    with pytest.raises(ValueError):
        chunker.chunk_pages("doc", [("text", 1.0)], chunk_size=100, overlap=100)


# --- Module 5: embeddings + vector store (build step 2) ---------------------


class _FakeGenaiClient:
    """Records embed_content batches instead of calling Gemini."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[int, str]] = []
        self.fail = fail
        self.models = self

    def embed_content(self, model, contents, config):
        if self.fail:
            raise genai_errors.APIError(500, {"error": {"message": "boom"}})
        self.calls.append((len(contents), config.task_type))
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1, 0.2]) for _ in contents])


@pytest.fixture
def fake_genai(monkeypatch: pytest.MonkeyPatch):
    def _install(fail: bool = False) -> _FakeGenaiClient:
        fake = _FakeGenaiClient(fail)
        monkeypatch.setattr(settings, "gemini_api_key", "test-key")
        monkeypatch.setattr(embedder, "_client", lambda api_key: fake)
        return fake

    return _install


def test_module5_embedder_splits_into_batches_of_100(fake_genai) -> None:
    fake = fake_genai()
    vectors = embedder.embed_texts(["text"] * 250)

    assert len(vectors) == 250
    assert fake.calls == [(100, "RETRIEVAL_DOCUMENT"), (100, "RETRIEVAL_DOCUMENT"), (50, "RETRIEVAL_DOCUMENT")]


def test_module5_embed_query_uses_query_task_type(fake_genai) -> None:
    fake = fake_genai()
    assert embedder.embed_query("What is RAG?") == [0.1, 0.2]
    assert fake.calls == [(1, "RETRIEVAL_QUERY")]


def test_module5_embedder_requires_api_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "gemini_api_key", "")
    with pytest.raises(embedder.EmbeddingError, match="GEMINI_API_KEY"):
        embedder.embed_texts(["text"])


def test_module5_embedder_wraps_api_errors(fake_genai) -> None:
    fake_genai(fail=True)
    with pytest.raises(embedder.EmbeddingError):
        embedder.embed_texts(["text"])


def _embedded(doc_id: str, texts: list[str], raw_conf: float = 1.0) -> list[RecognizedChunk]:
    return [
        RecognizedChunk(chunk_id=f"{doc_id}:{i}", text=t, raw_conf=raw_conf, vector=v)
        for i, (t, v) in enumerate(zip(texts, fake_embed(texts, "RETRIEVAL_DOCUMENT")))
    ]


def test_module5_vector_store_search_ranks_best_match_first(chroma) -> None:
    vector_store.add_chunks("doc", _embedded("doc", ["transformers use attention", "ocr reads scanned pages"], 0.8))

    results = vector_store.search(fake_embed(["ocr reads scanned pages"], "RETRIEVAL_QUERY")[0], top_k=2)

    assert [c.chunk_id for c, _ in results] == ["doc:1", "doc:0"]
    best, similarity = results[0]
    assert similarity == pytest.approx(1.0, abs=1e-4)  # identical text -> cosine similarity 1
    assert results[1][1] < similarity
    assert best.text == "ocr reads scanned pages"
    assert best.raw_conf == 0.8
    assert best.calibrated_conf is None


def test_module5_vector_store_upsert_does_not_duplicate(chroma) -> None:
    chunks = _embedded("doc", ["one chunk"])
    vector_store.add_chunks("doc", chunks)
    vector_store.add_chunks("doc", chunks)

    assert len(vector_store.search(chunks[0].vector, top_k=10)) == 1


def test_module5_vector_store_requires_vectors(chroma) -> None:
    with pytest.raises(ValueError):
        vector_store.add_chunks("doc", [RecognizedChunk(chunk_id="doc:0", text="t", raw_conf=1.0)])


def test_module5_vector_store_delete_document(chroma) -> None:
    vector_store.add_chunks("a", _embedded("a", ["alpha text"]))
    vector_store.add_chunks("b", _embedded("b", ["beta text"]))

    vector_store.delete_document("a")

    assert [c.chunk_id for c, _ in vector_store.search(fake_embed(["text"], "")[0], top_k=10)] == ["b:0"]


def test_module5_upload_stores_chunks_in_vector_store(client, pdf_file) -> None:
    with pdf_file([TYPED_PAGE]).open("rb") as f:
        doc_id = client.post("/upload", files={"file": ("notes.pdf", f, "application/pdf")}).json()["doc_id"]

    results = vector_store.search(fake_embed(["retriever language model"], "")[0], top_k=5)

    assert results and all(c.chunk_id.startswith(f"{doc_id}:") for c, _ in results)
    assert "Retrieval-Augmented Generation" in results[0][0].text


def test_module5_upload_rolls_back_when_embedding_fails(client, pdf_file, tmp_path, monkeypatch, db_session_factory) -> None:
    def _fail(texts, task_type):
        raise embedder.EmbeddingError("down")

    monkeypatch.setattr(embedder, "_embed", _fail)

    with pdf_file([TYPED_PAGE]).open("rb") as f:
        resp = client.post("/upload", files={"file": ("notes.pdf", f, "application/pdf")})

    assert resp.status_code == 502
    assert not any((tmp_path / "uploads").iterdir())
    with db_session_factory() as db:
        assert db.query(DocumentORM).count() == 0


# --- Modules 3-7: not built yet --------------------------------------------


@not_built
def test_module3_confidence_calibration() -> None:
    """Module 3: calibrated_conf is in [0, 1] and monotonic in raw_conf."""


@not_built
def test_module4_content_type_identification() -> None:
    """Module 4: table/paragraph/image chunks are labeled correctly."""


@not_built
def test_module5_confidence_aware_retrieval() -> None:
    """Module 5: results are ranked by combined_score (build step 5)."""


@not_built
def test_module6_reliability_tiers() -> None:
    """Module 6: scores map to Certain/Moderate/Uncertain/Unreadable."""


@not_built
def test_module7_llm_answer_generation() -> None:
    """Module 7: POST /ask returns an Answer with a reliability_label."""
