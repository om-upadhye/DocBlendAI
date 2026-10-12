"""Website support (not one of the 7 synopsis modules): demo sessions, document cleanup, usage counters.

On the hosted demo (settings.public_demo) every browser tab sends an
X-Session-Id header. It only sees the documents it uploaded, and those are
deleted once the tab stops sending heartbeats (closed, or the visitor left).

Usage counters (visitors and questions per day) are kept in both modes.
"""

import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import Header, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import DailyQuestionsORM, DocumentORM, SessionDocumentORM, SessionORM, VisitORM
from app.modules import page_store, vector_store

logger = logging.getLogger(__name__)

_ID = re.compile(r"[A-Za-z0-9-]{8,64}")


def valid_id(value: str | None) -> str | None:
    return value if value and _ID.fullmatch(value) else None


def session_header(x_session_id: str | None = Header(None, description="Browser-tab session (hosted demo)")) -> str | None:
    """FastAPI dependency: the caller's session id. Required on the public demo."""
    session_id = valid_id(x_session_id)
    if settings.public_demo and session_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing session; reload the page")
    return session_id


def today() -> date:
    return datetime.now(timezone(timedelta(hours=settings.stats_utc_offset_hours))).date()


# ---------- sessions ----------


def touch(db: Session, session_id: str, last_seen: float | None = None) -> None:
    row = db.get(SessionORM, session_id)
    seen = time.time() if last_seen is None else last_seen
    if row is None:
        db.add(SessionORM(session_id=session_id, last_seen=seen))
    else:
        row.last_seen = seen
    db.commit()


def leave(db: Session, session_id: str) -> None:
    """The tab is closing: expire the session after a short grace period (a reload heartbeats again first)."""
    if db.get(SessionORM, session_id) is not None:
        touch(db, session_id, time.time() - settings.session_ttl_seconds + settings.session_leave_grace_seconds)


def claim(db: Session, session_id: str | None, doc_id: str) -> None:
    if session_id:
        db.add(SessionDocumentORM(doc_id=doc_id, session_id=session_id))
        db.commit()


def visible_doc_ids(db: Session, session_id: str | None) -> set[str] | None:
    """Documents this caller may use, or None for all (local/team mode)."""
    if not settings.public_demo:
        return None
    rows = db.query(SessionDocumentORM.doc_id).filter_by(session_id=session_id)
    return {doc_id for (doc_id,) in rows}


def remove_document(db: Session, row: DocumentORM) -> None:
    """Delete a document everywhere: its row, its chunks in ChromaDB, the uploaded file, and its page view."""
    vector_store.delete_document(row.doc_id)
    Path(row.file_path).unlink(missing_ok=True)
    page_store.delete(row.doc_id)
    owner = db.get(SessionDocumentORM, row.doc_id)
    if owner is not None:
        db.delete(owner)
    db.delete(row)
    db.commit()


def end_expired_sessions(db: Session) -> int:
    """Delete the documents of sessions with no recent heartbeat, then the sessions. Returns documents removed."""
    cutoff = time.time() - settings.session_ttl_seconds
    expired = [sid for (sid,) in db.query(SessionORM.session_id).filter(SessionORM.last_seen < cutoff)]
    removed = 0
    for session_id in expired:
        for owner in db.query(SessionDocumentORM).filter_by(session_id=session_id).all():
            row = db.get(DocumentORM, owner.doc_id)
            if row is None:
                db.delete(owner)
                db.commit()
            else:
                remove_document(db, row)
                removed += 1
        db.query(SessionORM).filter_by(session_id=session_id).delete()
        db.commit()
    if removed:
        logger.info("Ended %d idle session(s), deleted %d document(s)", len(expired), removed)
    return removed


# ---------- usage counters ----------


def count_visit(db: Session, visitor_id: str) -> None:
    day = today()
    if db.get(VisitORM, (day, visitor_id)) is None:
        db.add(VisitORM(day=day, visitor_id=visitor_id))
        db.commit()


def count_question(db: Session) -> None:
    day = today()
    row = db.get(DailyQuestionsORM, day)
    if row is None:
        db.add(DailyQuestionsORM(day=day, count=1))
    else:
        row.count += 1
    db.commit()


def stats(db: Session) -> dict[str, int]:
    day = today()
    questions_today = db.get(DailyQuestionsORM, day)
    return {
        "visitors_today": db.query(func.count()).select_from(VisitORM).filter(VisitORM.day == day).scalar(),
        "questions_today": questions_today.count if questions_today else 0,
        "visitors_total": db.query(func.count(func.distinct(VisitORM.visitor_id))).scalar(),
        "questions_total": db.query(func.coalesce(func.sum(DailyQuestionsORM.count), 0)).scalar(),
    }
