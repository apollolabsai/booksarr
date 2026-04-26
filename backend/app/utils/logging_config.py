import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from sqlalchemy import select

from backend.app.config import CONFIG_DIR


DEFAULT_LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DIR = CONFIG_DIR / "logs"
LOG_FILE = LOG_DIR / "booksarr.log"
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 10
VALID_LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


_SECRET_REPLACEMENTS = [
    (
        re.compile(r"(?i)\b(Authorization)([\"']?\s*[:=]\s*[\"']?)(Bearer\s+)?([^\"'\s,&}]+)"),
        r"\1\2[REDACTED]",
    ),
    (
        re.compile(r"(?i)\b(Bearer)\s+([A-Za-z0-9._~+/=-]+)"),
        r"\1 [REDACTED]",
    ),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b"),
        "[REDACTED_JWT]",
    ),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|token|password|secret|authorization|"
            r"hardcover_api_key|google_books_api_key|irc_socks5_password|"
            r"irc_socks5_username|irc_vpn_password|irc_vpn_username)"
            r"([\"']?\s*[:=]\s*[\"']?)([^\"'\s,&}]+)"
        ),
        r"\1\2[REDACTED]",
    ),
]


def redact_log_text(value: str) -> str:
    redacted = value
    for pattern, replacement in _SECRET_REPLACEMENTS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_log_text(super().format(record))


def _has_handler(logger: logging.Logger, marker: str) -> bool:
    return any(getattr(handler, "_booksarr_handler", None) == marker for handler in logger.handlers)


def configure_logging() -> Path:
    """Configure stdout, persistent rotating file logs, and library noise levels."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    formatter = RedactingFormatter(LOG_FORMAT)

    if not _has_handler(root_logger, "stdout"):
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(formatter)
        stdout_handler._booksarr_handler = "stdout"  # type: ignore[attr-defined]
        root_logger.addHandler(stdout_handler)

    if not _has_handler(root_logger, "file"):
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler._booksarr_handler = "file"  # type: ignore[attr-defined]
        root_logger.addHandler(file_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    return LOG_FILE


def get_log_files() -> list[Path]:
    files = [LOG_FILE]
    files.extend(sorted(LOG_DIR.glob("booksarr.log.*"), key=lambda path: path.name))
    return [path for path in files if path.exists() and path.is_file()]


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
