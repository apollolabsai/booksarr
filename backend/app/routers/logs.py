from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from backend.app.utils.log_store import log_store

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
async def get_logs(
    category: list[str] = Query(default=[]),
    level: list[str] = Query(default=[]),
):
    return {
        "entries": log_store.get_entries(categories=category, levels=level),
        "categories": log_store.get_categories(),
    }


@router.get("/download")
async def download_logs(
    category: list[str] = Query(default=[]),
    level: list[str] = Query(default=[]),
):
    text = log_store.get_all_text(categories=category, levels=level)
    return PlainTextResponse(
        content=text,
        headers={"Content-Disposition": "attachment; filename=booksarr.log"},
    )
