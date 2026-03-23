import logging
from collections import Counter
from contextvars import ContextVar
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import async_session

logger = logging.getLogger("booksarr.api_usage")

API_SOURCES = ("hardcover", "google", "openlibrary")
_usage_batch: ContextVar[Counter[str] | None] = ContextVar("api_usage_batch", default=None)


def begin_api_usage_batch():
    return _usage_batch.set(Counter())


def clear_api_usage_batch(token):
    _usage_batch.reset(token)


async def record_api_call(source: str):
    if source not in API_SOURCES:
        raise ValueError(f"Unsupported API source: {source}")

    batch = _usage_batch.get()
    if batch is not None:
        batch[source] += 1
        return

    day = datetime.now().date().isoformat()

    try:
        async with async_session() as db:
            await _apply_api_usage_counts(db, day, {source: 1})
            await db.commit()
    except Exception as e:
        logger.warning("Failed to record API call usage for %s: %s", source, e)


async def flush_api_usage_batch(db: AsyncSession):
    batch = _usage_batch.get()
    if not batch:
        return

    day = datetime.now().date().isoformat()
    await _apply_api_usage_counts(db, day, dict(batch))
    batch.clear()


async def _apply_api_usage_counts(db: AsyncSession, day: str, counts: dict[str, int]):
    stmt = text("""
        INSERT INTO api_call_usage(day, source, count, updated_at)
        VALUES (:day, :source, :count, CURRENT_TIMESTAMP)
        ON CONFLICT(day, source)
        DO UPDATE SET count = count + :count, updated_at = CURRENT_TIMESTAMP
    """)
    for source, count in counts.items():
        if count <= 0:
            continue
        await db.execute(stmt, {"day": day, "source": source, "count": count})


async def get_api_usage_rows(db: AsyncSession, days: int = 7) -> list[dict]:
    # Keep full history in storage. The caller decides how much to display.
    days = max(1, days)
    end_day = datetime.now().date()
    start_day = end_day - timedelta(days=days - 1)

    result = await db.execute(
        text("""
            SELECT day, source, count
            FROM api_call_usage
            WHERE day >= :start_day AND day <= :end_day
            ORDER BY day ASC, source ASC
        """),
        {
            "start_day": start_day.isoformat(),
            "end_day": end_day.isoformat(),
        },
    )

    usage_map: dict[str, dict[str, int]] = {}
    for day, source, count in result.fetchall():
        usage_map.setdefault(day, {})[source] = int(count)

    rows = []
    for offset in range(days):
        day = (start_day + timedelta(days=offset)).isoformat()
        hardcover = usage_map.get(day, {}).get("hardcover", 0)
        google = usage_map.get(day, {}).get("google", 0)
        openlibrary = usage_map.get(day, {}).get("openlibrary", 0)
        rows.append({
            "day": day,
            "total": hardcover + google + openlibrary,
            "hardcover": hardcover,
            "google": google,
            "openlibrary": openlibrary,
        })

    return rows
