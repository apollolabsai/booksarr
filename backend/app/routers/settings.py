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

    # Mask API key for display
    masked_key = ""
    if api_key:
        masked_key = api_key[:10] + "..." + api_key[-4:] if len(api_key) > 14 else "***"

    return SettingsResponse(
        hardcover_api_key=masked_key,
        library_path=str(BOOKS_DIR),
        last_scan_at=last_scan,
    )


@router.put("")
async def update_settings(body: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    if body.hardcover_api_key is not None:
        result = await db.execute(
            select(Setting).where(Setting.key == "hardcover_api_key")
        )
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = body.hardcover_api_key
        else:
            db.add(Setting(key="hardcover_api_key", value=body.hardcover_api_key))
        await db.commit()

    return {"status": "ok"}
