"""SQLAlchemy ORM models for the relational entities.

Mirrors the Pydantic schemas in app/models/schemas.py for Document, Query,
Answer, and RetrievalResult. RecognizedChunk is not stored here: it lives in
ChromaDB (Module 5, vector_store.py).
"""

from datetime import date

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.models.schemas import FormatType, ReliabilityLabel


class DocumentORM(Base):
    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    file_path: Mapped[str] = mapped_column(String)
    format_type: Mapped[FormatType] = mapped_column(SAEnum(FormatType), index=True)
    page_count: Mapped[int] = mapped_column(Integer)


class QueryORM(Base):
    __tablename__ = "queries"

    query_id: Mapped[str] = mapped_column(String, primary_key=True)
    question_text: Mapped[str] = mapped_column(Text)
    user_id: Mapped[str] = mapped_column(String, index=True)


class AnswerORM(Base):
    __tablename__ = "answers"

    answer_id: Mapped[str] = mapped_column(String, primary_key=True)
    # Not in the synopsis entity (so not in schemas.py): links the answer to its question.
    query_id: Mapped[str] = mapped_column(ForeignKey("queries.query_id"), index=True)
    answer_text: Mapped[str] = mapped_column(Text)
    reliability_label: Mapped[ReliabilityLabel] = mapped_column(SAEnum(ReliabilityLabel), index=True)


class RetrievalResultORM(Base):
    __tablename__ = "retrieval_results"

    # Surrogate key: the same chunk_id can be retrieved for many queries, so it cannot be the PK.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Not in the synopsis entity (so not in schemas.py): which question retrieved this chunk.
    query_id: Mapped[str] = mapped_column(ForeignKey("queries.query_id"), index=True)
    chunk_id: Mapped[str] = mapped_column(String, index=True)
    similarity: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    combined_score: Mapped[float] = mapped_column(Float)


# --- Website support tables (not synopsis entities): demo sessions and usage counters. ---


class SessionORM(Base):
    """One browser tab on the hosted demo; its documents are deleted when it goes quiet."""

    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    last_seen: Mapped[float] = mapped_column(Float, index=True)  # Unix time of the last heartbeat


class SessionDocumentORM(Base):
    """Which session uploaded a document (kept apart so the Document entity matches the synopsis)."""

    __tablename__ = "session_documents"

    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, index=True)


class VisitORM(Base):
    """A visitor (one browser) seen on a given day; the count per day is the visitor count."""

    __tablename__ = "visits"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    visitor_id: Mapped[str] = mapped_column(String, primary_key=True)


class DailyQuestionsORM(Base):
    __tablename__ = "daily_questions"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
