import asyncio

from fastapi import APIRouter, Query

from backend.app.services.library_sync import run_full_sync, scan_status

router = APIRouter(prefix="/api/library", tags=["library"])


@router.post("/scan")
async def trigger_scan(force: bool = Query(False)):
    if scan_status.status == "scanning":
        return {"status": "already_scanning", "message": "A scan is already in progress"}

    asyncio.create_task(run_full_sync(force=force))
    return {"status": "started", "message": "Library scan started"}


@router.get("/status")
async def get_scan_status():
    return scan_status.to_dict()
