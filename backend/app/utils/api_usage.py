import logging
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import async_session

logger = logging.getLogger("booksarr.api_usage")

API_SOURCES = ("hardcover", "google", "openlibrary")


async def record_api_call(source: str):
    if source not in API_SOURCES:
        raise ValueError(f"Unsupported API source: {source}")

    day = datetime.now().date().isoformat()
    stmt = text("""
        INSERT INTO api_call_usage(day, source, count, updated_at)
        VALUES (:day, :source, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(day, source)
        DO UPDATE SET count = count + 1, updated_at = CURRENT_TIMESTAMP
    """)

    try:
        async with async_session() as db:
            await db.execute(stmt, {"day": day, "source": source})
            await db.commit()
    except Exception as e:
        logger.warning("Failed to record API call usage for %s: %s", source, e)


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
