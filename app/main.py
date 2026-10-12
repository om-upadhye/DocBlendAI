"""FastAPI entry point: app instance, router registration, health check.

Single monolith (see CLAUDE.md): all 7 modules run in this one process and
are wired together through the routers.

Run with:  venv/Scripts/python -m uvicorn app.main:app --reload
      or:  venv/Scripts/python -m app.main   (reads PORT, as hosts like Render set it)
"""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app import __version__
from app.config import settings
from app import site
from app.db.database import SessionLocal, init_db
from app.routers import query, upload
from app.routers import site as site_routes

STATIC_DIR = Path(__file__).parent / "static"

# Uvicorn only configures its own loggers; this makes app.* INFO logs visible too.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")
logger = logging.getLogger(__name__)

SWEEP_SECONDS = 15


def _sweep_once() -> None:
    with SessionLocal() as db:
        site.end_expired_sessions(db)


async def _sweep_sessions() -> None:
    """Public demo: every few seconds, delete the documents of visitors who have left."""
    while True:
        try:
            await asyncio.to_thread(_sweep_once)
        except Exception:
            logger.exception("Session cleanup failed")
        await asyncio.sleep(SWEEP_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    sweeper = asyncio.create_task(_sweep_sessions()) if settings.public_demo else None
    yield
    if sweeper:
        sweeper.cancel()


app = FastAPI(
    title="DocBlendAI",
    description="Confidence-aware multi-format document QA assistant.",
    version=__version__,
    lifespan=lifespan,
)

app.include_router(upload.router)
app.include_router(query.router)
app.include_router(site_routes.router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    """Demo UI: upload documents, ask questions, see reliability labels and sources."""
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
