import logging
import os
import shutil
import json

from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import BOOKS_DIR, CONFIG_DIR, HARDCOVER_API_KEY, GOOGLE_BOOKS_API_KEY
from backend.app.database import get_db
from backend.app.models import Setting
from backend.app.schemas.setting import (
    SettingsResponse,
    SettingsUpdate,
    ApiUsageDay,
    VisibilityCategories,
    ScanSummary,
)
from backend.app.utils.api_usage import get_api_usage_rows
from backend.app.utils.book_visibility import normalize_visibility_settings
from backend.app.utils.logging_config import (
    apply_log_level,
    get_effective_log_level,
    normalize_log_level,
)

logger = logging.getLogger("booksarr.settings")

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Setting))
    settings = {s.key: s.value for s in result.scalars().all()}

    # Resolve keys: saved DB value takes precedence over env fallback
    db_hardcover_key = settings.get("hardcover_api_key", "")
    hc_from_env = bool(HARDCOVER_API_KEY)
    api_key = db_hardcover_key or HARDCOVER_API_KEY
    hardcover_source = "database" if db_hardcover_key else ("environment" if hc_from_env else "none")

    db_google_key = settings.get("google_books_api_key", "")
    google_from_env = bool(GOOGLE_BOOKS_API_KEY)
    google_key = db_google_key or GOOGLE_BOOKS_API_KEY
    google_source = "database" if db_google_key else ("environment" if google_from_env else "none")

    last_scan = settings.get("last_scan_at")
    last_scan_summary = None
    raw_summary = settings.get("last_scan_summary")
    if raw_summary:
        try:
            last_scan_summary = ScanSummary.model_validate_json(raw_summary)
        except ValueError:
            logger.warning("Ignoring invalid last_scan_summary setting payload")
    scan_interval = int(settings.get("scan_interval_hours", "24"))
    log_level = normalize_log_level(settings.get("log_level"))
    effective_log_level = get_effective_log_level()
    visibility_categories = normalize_visibility_settings(settings.get("book_visibility_categories"))

    # Mask API keys for display
    def _mask(key: str) -> str:
        if not key:
            return ""
        return key[:10] + "..." + key[-4:] if len(key) > 14 else "***"

    return SettingsResponse(
        hardcover_api_key=_mask(api_key),
        hardcover_api_key_from_env=hc_from_env,
        hardcover_api_key_source=hardcover_source,
        google_books_api_key=_mask(google_key),
        google_books_api_key_from_env=google_from_env,
        google_books_api_key_source=google_source,
        library_path=str(BOOKS_DIR),
        last_scan_at=last_scan,
        last_scan_summary=last_scan_summary,
        scan_interval_hours=scan_interval,
        log_level=effective_log_level if settings.get("log_level") or effective_log_level != "INFO" else log_level,
        visibility_categories=VisibilityCategories(**visibility_categories),
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

    if body.log_level is not None:
        normalized_log_level = normalize_log_level(body.log_level)
        await _upsert_setting(db, "log_level", normalized_log_level)
        apply_log_level(normalized_log_level)
        logger.warning("Application log level changed to %s", normalized_log_level)

    if body.visibility_categories is not None:
        await _upsert_setting(
            db,
            "book_visibility_categories",
            json.dumps(body.visibility_categories.model_dump(), sort_keys=True),
        )

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
    """Delete library data and cached images while preserving settings and API usage history."""
    logger.warning("Factory reset triggered — deleting library data and cache")

    # Stop the scheduler
    from backend.app.services.scheduler import update_scan_schedule
    await update_scan_schedule(0)

    # Clear all library data tables in dependency order.
    # Preserve settings and persistent API usage history.
    for table in ["book_files", "book_series", "books", "series", "authors"]:
        await db.execute(text(f"DELETE FROM {table}"))
    # Clear last scan markers so the UI resets cleanly
    await db.execute(text("DELETE FROM settings WHERE key IN ('last_scan_at', 'last_scan_summary')"))
    await db.commit()
    logger.info("Library data cleared (settings and API usage preserved)")

    # Delete cached images
    cache_dir = CONFIG_DIR / "cache"
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "authors").mkdir(exist_ok=True)
        (cache_dir / "books").mkdir(exist_ok=True)
    logger.info("Image cache cleared")

    return {"status": "ok", "message": "All data has been reset"}


@router.get("/api-usage", response_model=list[ApiUsageDay])
async def get_api_usage(days: int = 7, db: AsyncSession = Depends(get_db)):
    return await get_api_usage_rows(db, days=days)


@router.get("/build-info")
async def get_build_info():
    return {
        "branch": os.environ.get("BUILD_BRANCH", "dev"),
        "commit": os.environ.get("BUILD_COMMIT", "local"),
        "date": os.environ.get("BUILD_DATE", ""),
    }
