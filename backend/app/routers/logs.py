from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from backend.app.utils.log_store import log_store

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
async def get_logs(
    category: str | None = Query(None),
    level: str | None = Query(None),
):
    return {
        "entries": log_store.get_entries(category=category, level=level),
        "categories": log_store.get_categories(),
    }


@router.get("/download")
async def download_logs(category: str | None = Query(None)):
    text = log_store.get_all_text(category=category)
    return PlainTextResponse(
        content=text,
        headers={"Content-Disposition": "attachment; filename=booksarr.log"},
    )
