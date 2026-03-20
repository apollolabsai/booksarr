import os

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import BOOKS_DIR, HARDCOVER_API_KEY
from backend.app.database import get_db
from backend.app.models import Setting
from backend.app.schemas.setting import SettingsResponse, SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)):
    api_key = HARDCOVER_API_KEY
    last_scan = None

    result = await db.execute(select(Setting))
    settings = {s.key: s.value for s in result.scalars().all()}

    if not api_key:
        api_key = settings.get("hardcover_api_key", "")

    last_scan = settings.get("last_scan_at")
    scan_interval = int(settings.get("scan_interval_hours", "24"))

    # Mask API key for display
    masked_key = ""
    if api_key:
        masked_key = api_key[:10] + "..." + api_key[-4:] if len(api_key) > 14 else "***"

    return SettingsResponse(
        hardcover_api_key=masked_key,
        library_path=str(BOOKS_DIR),
        last_scan_at=last_scan,
        scan_interval_hours=scan_interval,
    )


@router.put("")
async def update_settings(body: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    if body.hardcover_api_key is not None:
        await _upsert_setting(db, "hardcover_api_key", body.hardcover_api_key)

    if body.scan_interval_hours is not None:
        await _upsert_setting(db, "scan_interval_hours", str(body.scan_interval_hours))
        # Update the running scheduler
        from backend.app.services.scheduler import update_scan_schedule
        await update_scan_schedule(body.scan_interval_hours)

    await db.commit()
    return {"status": "ok"}


async def _upsert_setting(db: AsyncSession, key: str, value: str):
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        db.add(Setting(key=key, value=value))


@router.get("/build-info")
async def get_build_info():
    return {
        "branch": os.environ.get("BUILD_BRANCH", "dev"),
        "commit": os.environ.get("BUILD_COMMIT", "local"),
        "date": os.environ.get("BUILD_DATE", ""),
    }
