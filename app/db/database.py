"""SQLAlchemy engine and session setup for the SQLite relational store.

Supports Modules 1, 5, 6, 7: SQLite holds Document, Query, Answer, and
RetrievalResult rows (ChromaDB holds chunk vectors, see vector_store.py).
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# check_same_thread=False: FastAPI may use a session from a different thread than the one that created it.
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Called once on app startup."""
    from app.db import models  # noqa: F401  (registers models on Base.metadata)

    Base.metadata.create_all(bind=engine)
