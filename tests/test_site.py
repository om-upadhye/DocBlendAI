"""Website support: demo sessions (privacy + cleanup), usage counters, upload limits, original-file preview."""

import time
from pathlib import Path

import pytest

from app import site
from app.config import settings
from app.db.models import DocumentORM, SessionORM
from app.modules import llm_answer, vector_store
from tests.conftest import TYPED_PAGE

A, B = "session-aaaa-1111", "session-bbbb-2222"


@pytest.fixture
def demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "public_demo", True)


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_answer, "_generate", lambda prompt: "An answer.")


def _upload(client, pdf_file, session: str | None = None, name: str = "notes.pdf"):
    headers = {"X-Session-Id": session} if session else {}
    with pdf_file([TYPED_PAGE], name).open("rb") as f:
        return client.post("/upload", files={"file": (name, f, "application/pdf")}, headers=headers)


def _ask(client, session: str, query_id: str, doc_ids=None):
    body = {"query_id": query_id, "question_text": "What does the retriever select?", "user_id": "web"}
    if doc_ids is not None:
        body["doc_ids"] = doc_ids
    return client.post("/ask", json=body, headers={"X-Session-Id": session})


def test_demo_requires_a_session(client, pdf_file, demo) -> None:
    assert _upload(client, pdf_file).status_code == 400
    assert client.get("/documents").status_code == 400


def test_demo_sessions_only_see_their_own_documents(client, pdf_file, demo, fake_llm) -> None:
    doc_a = _upload(client, pdf_file, A).json()["doc_id"]
    doc_b = _upload(client, pdf_file, B, "other.pdf").json()["doc_id"]

    assert [d["doc_id"] for d in client.get("/documents", headers={"X-Session-Id": A}).json()] == [doc_a]
    assert _ask(client, A, "q1", [doc_b]).status_code == 422  # someone else's document
    assert client.delete(f"/documents/{doc_b}", headers={"X-Session-Id": A}).status_code == 404

    resp = _ask(client, A, "q2")  # no doc_ids: only A's own documents are searched
    assert resp.status_code == 200
    sources = client.get(f"/answer/{resp.json()['answer_id']}/sources").json()
    assert {s["doc_id"] for s in sources} == {doc_a}


def test_local_mode_keeps_old_behaviour(client, pdf_file) -> None:
    doc_id = _upload(client, pdf_file).json()["doc_id"]
    assert [d["doc_id"] for d in client.get("/documents").json()] == [doc_id]


def test_idle_session_documents_are_deleted(client, pdf_file, demo, db_session_factory) -> None:
    doc_id = _upload(client, pdf_file, A).json()["doc_id"]
    kept = _upload(client, pdf_file, B, "kept.pdf").json()["doc_id"]
    with db_session_factory() as db:
        path = Path(db.get(DocumentORM, doc_id).file_path)
        site.touch(db, A, time.time() - settings.session_ttl_seconds - 1)

        assert site.end_expired_sessions(db) == 1

        assert db.get(DocumentORM, doc_id) is None
        assert db.get(SessionORM, A) is None
        assert db.get(DocumentORM, kept) is not None
    assert not path.exists()
    assert vector_store.get_chunks([f"{doc_id}:0"]) == {}


def test_leaving_expires_after_grace_but_a_reload_keeps_documents(client, pdf_file, demo, db_session_factory, monkeypatch) -> None:
    doc_id = _upload(client, pdf_file, A).json()["doc_id"]
    assert client.post(f"/session/{A}/leave").status_code == 204
    with db_session_factory() as db:
        assert site.end_expired_sessions(db) == 0  # still within the grace period

    beat = {"session_id": A, "visitor_id": "visitor-1234"}
    assert client.post("/session/heartbeat", json=beat).json()["public_demo"] is True  # page reloaded
    monkeypatch.setattr(settings, "session_leave_grace_seconds", -1)
    with db_session_factory() as db:
        assert site.end_expired_sessions(db) == 0
        assert db.get(DocumentORM, doc_id) is not None

    client.post(f"/session/{A}/leave")  # closed for good
    with db_session_factory() as db:
        assert site.end_expired_sessions(db) == 1


def test_stats_count_unique_visitors_and_questions(client, pdf_file, fake_llm) -> None:
    for visitor in ["visitor-1111", "visitor-2222", "visitor-1111"]:
        client.post("/session/heartbeat", json={"session_id": A, "visitor_id": visitor})
    _upload(client, pdf_file)
    _ask(client, A, "q1")
    _ask(client, A, "q2")

    assert client.get("/stats").json() == {
        "visitors_today": 2, "questions_today": 2, "visitors_total": 2, "questions_total": 2,
    }


def test_heartbeat_rejects_bad_ids(client) -> None:
    assert client.post("/session/heartbeat", json={"session_id": "x", "visitor_id": "visitor-1"}).status_code == 422


def test_upload_limits(client, pdf_file, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_pages", 1)
    with pdf_file([TYPED_PAGE, TYPED_PAGE]).open("rb") as f:
        assert client.post("/upload", files={"file": ("two.pdf", f, "application/pdf")}).status_code == 413
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    resp = client.post("/upload", files={"file": ("big.txt", b"x" * (1024 * 1024 + 1), "text/plain")})
    assert resp.status_code == 413


def test_original_file_is_served_inline_for_preview(client, pdf_file) -> None:
    doc_id = _upload(client, pdf_file).json()["doc_id"]
    resp = client.get(f"/documents/{doc_id}/file")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"].startswith("inline")
    assert client.get("/documents/nope/file").status_code == 404
