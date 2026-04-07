import logging

from sqlalchemy import select


DEFAULT_LOG_LEVEL = "INFO"
VALID_LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def normalize_log_level(value: str | None) -> str:
    normalized = str(value or "").strip().upper()
    return normalized if normalized in VALID_LOG_LEVELS else DEFAULT_LOG_LEVEL


def apply_log_level(level_name: str | None) -> str:
    normalized = normalize_log_level(level_name)
    level = VALID_LOG_LEVELS[normalized]
    logging.getLogger().setLevel(level)
    logging.getLogger("booksarr").setLevel(level)
    return normalized


def get_effective_log_level() -> str:
    effective = logging.getLogger("booksarr").getEffectiveLevel()
    level_name = logging.getLevelName(effective)
    return level_name if isinstance(level_name, str) else DEFAULT_LOG_LEVEL


async def apply_persisted_log_level() -> str:
    from backend.app.database import async_session
    from backend.app.models import Setting

    async with async_session() as session:
        result = await session.execute(select(Setting.value).where(Setting.key == "log_level"))
        persisted_value = result.scalar_one_or_none()

    return apply_log_level(persisted_value)
