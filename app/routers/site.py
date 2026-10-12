"""Website routes (not a synopsis module): session heartbeats and the usage counters shown on the page."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import site
from app.config import settings
from app.db.database import get_db

router = APIRouter(tags=["site"])


class Heartbeat(BaseModel):
    session_id: str
    visitor_id: str


class SessionInfo(BaseModel):
    public_demo: bool
    heartbeat_seconds: int


class Stats(BaseModel):
    visitors_today: int
    questions_today: int
    visitors_total: int
    questions_total: int


@router.post("/session/heartbeat", response_model=SessionInfo)
def heartbeat(beat: Heartbeat, db: Session = Depends(get_db)) -> SessionInfo:
    """Sent by the page on load and every minute or so: keeps this tab's documents alive and counts the visitor."""
    session_id, visitor_id = site.valid_id(beat.session_id), site.valid_id(beat.visitor_id)
    if session_id is None or visitor_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid session or visitor id")
    site.touch(db, session_id)
    site.count_visit(db, visitor_id)
    return SessionInfo(public_demo=settings.public_demo, heartbeat_seconds=max(10, settings.session_ttl_seconds // 4))


@router.post("/session/{session_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave(session_id: str, db: Session = Depends(get_db)) -> None:
    """Sent (via navigator.sendBeacon) when the tab closes; documents go after a short grace period."""
    if site.valid_id(session_id):
        site.leave(db, session_id)


@router.get("/stats", response_model=Stats)
def get_stats(db: Session = Depends(get_db)) -> Stats:
    return Stats(**site.stats(db))
