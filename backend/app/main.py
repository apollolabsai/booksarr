import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.app.config import CONFIG_DIR
from backend.app.database import engine, Base
from backend.app.models import *  # noqa: F401, F403
from backend.app.utils.db_migrations import run_schema_migrations

# --- Logging setup ---
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, stream=sys.stdout)

# Quiet down noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

# Attach in-memory log store for the UI
from backend.app.utils.log_store import log_store  # noqa: E402
log_store.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger("booksarr").addHandler(log_store)

logger = logging.getLogger("booksarr.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Booksarr...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(run_schema_migrations)
    logger.info("Database initialized")

    from backend.app.services.scheduler import start_scheduler, stop_scheduler
    from backend.app.services.irc_worker import start_irc_worker, stop_irc_worker
    await start_scheduler()
    await start_irc_worker()

    yield

    await stop_irc_worker()
    await stop_scheduler()
    logger.info("Shutting down Booksarr")


app = FastAPI(title="Booksarr", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
from backend.app.routers import authors, books, series, library, settings, logs, irc  # noqa: E402

app.include_router(authors.router)
app.include_router(books.router)
app.include_router(series.router)
app.include_router(library.router)
app.include_router(settings.router)
app.include_router(logs.router)
app.include_router(irc.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/images/{category}/{filename}")
async def serve_image(category: str, filename: str):
    """Serve cached images (author photos and book covers)."""
    if category not in ("authors", "books"):
        raise HTTPException(status_code=400, detail="Invalid category")
    file_path = CONFIG_DIR / "cache" / category / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(
        str(file_path),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


# Serve React frontend in production
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    # Serve static assets (JS, CSS, etc.)
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

    # Catch-all for SPA client-side routing
    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        # Serve index.html for all non-API, non-asset routes
        return FileResponse(str(frontend_dist / "index.html"))
