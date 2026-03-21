import logging
import os
import shutil

from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import BOOKS_DIR, CONFIG_DIR, HARDCOVER_API_KEY, GOOGLE_BOOKS_API_KEY
from backend.app.database import get_db
from backend.app.models import Setting
from backend.app.schemas.setting import SettingsResponse, SettingsUpdate

logger = logging.getLogger("booksarr.settings")

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Setting))
    settings = {s.key: s.value for s in result.scalars().all()}

    # Resolve keys: env var takes precedence over DB
    hc_from_env = bool(HARDCOVER_API_KEY)
    api_key = HARDCOVER_API_KEY or settings.get("hardcover_api_key", "")

    google_from_env = bool(GOOGLE_BOOKS_API_KEY)
    google_key = GOOGLE_BOOKS_API_KEY or settings.get("google_books_api_key", "")

    last_scan = settings.get("last_scan_at")
    scan_interval = int(settings.get("scan_interval_hours", "24"))

    # Mask API keys for display
    def _mask(key: str) -> str:
        if not key:
            return ""
        return key[:10] + "..." + key[-4:] if len(key) > 14 else "***"

    return SettingsResponse(
        hardcover_api_key=_mask(api_key),
        hardcover_api_key_from_env=hc_from_env,
        google_books_api_key=_mask(google_key),
        google_books_api_key_from_env=google_from_env,
        library_path=str(BOOKS_DIR),
        last_scan_at=last_scan,
        scan_interval_hours=scan_interval,
    )


@router.put("")
async def update_settings(body: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    if body.hardcover_api_key is not None:
        await _upsert_setting(db, "hardcover_api_key", body.hardcover_api_key)

    if body.google_books_api_key is not None:
        await _upsert_setting(db, "google_books_api_key", body.google_books_api_key)

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


@router.post("/reset")
async def reset_all_data(db: AsyncSession = Depends(get_db)):
    """Delete all database data and cached images. Resets to fresh install."""
    logger.warning("Factory reset triggered — deleting all data and cache")

    # Stop the scheduler
    from backend.app.services.scheduler import update_scan_schedule
    await update_scan_schedule(0)

    # Clear all data tables in dependency order (preserve settings like API key)
    for table in ["book_files", "book_series", "books", "series", "authors"]:
        await db.execute(text(f"DELETE FROM {table}"))
    # Clear last_scan_at so it shows "Never" again
    await db.execute(text("DELETE FROM settings WHERE key = 'last_scan_at'"))
    await db.commit()
    logger.info("All database tables cleared (settings preserved)")

    # Delete cached images
    cache_dir = CONFIG_DIR / "cache"
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "authors").mkdir(exist_ok=True)
        (cache_dir / "books").mkdir(exist_ok=True)
    logger.info("Image cache cleared")

    return {"status": "ok", "message": "All data has been reset"}


@router.get("/build-info")
async def get_build_info():
    return {
        "branch": os.environ.get("BUILD_BRANCH", "dev"),
        "commit": os.environ.get("BUILD_COMMIT", "local"),
        "date": os.environ.get("BUILD_DATE", ""),
    }
