"""FastAPI entry point: app instance, router registration, health check.

Single monolith (see CLAUDE.md): all 7 modules run in this one process and
are wired together through the routers.

Run with:  venv/Scripts/python -m uvicorn app.main:app --reload
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db.database import init_db
from app.routers import query, upload


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(
    title="DocBlendAI",
    description="Confidence-aware multi-format document QA assistant.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(upload.router)
app.include_router(query.router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}
