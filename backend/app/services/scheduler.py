import asyncio
import logging

logger = logging.getLogger("booksarr.scheduler")

_scheduler_task: asyncio.Task | None = None
_current_interval: int = 0  # hours, 0 = disabled


async def _scan_loop(interval_hours: int):
    """Background loop that triggers a library sync at the configured interval."""
    from backend.app.services.library_sync import run_full_sync
    logger.info("Scheduled scan started: every %d hour(s)", interval_hours)
    while True:
        await asyncio.sleep(interval_hours * 3600)
        logger.info("Scheduled scan triggered (interval: %dh)", interval_hours)
        await run_full_sync(force=False)


async def update_scan_schedule(interval_hours: int):
    """Update the scan schedule. Pass 0 to disable."""
    global _scheduler_task, _current_interval

    # Cancel existing task if running
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
        _scheduler_task = None

    _current_interval = interval_hours

    if interval_hours > 0:
        _scheduler_task = asyncio.create_task(_scan_loop(interval_hours))
        logger.info("Scan schedule updated: every %d hour(s)", interval_hours)
    else:
        logger.info("Scheduled scanning disabled")


async def start_scheduler():
    """Load the scan interval from the DB and start the scheduler if configured."""
    from backend.app.database import async_session
    from backend.app.models import Setting
    from sqlalchemy import select

    try:
        async with async_session() as db:
            result = await db.execute(
                select(Setting).where(Setting.key == "scan_interval_hours")
            )
            setting = result.scalar_one_or_none()
            interval = int(setting.value) if setting else 24
            if interval > 0:
                await update_scan_schedule(interval)
    except Exception as e:
        logger.warning("Failed to load scan schedule: %s", e)


async def stop_scheduler():
    """Cancel the scheduler task on shutdown."""
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
        _scheduler_task = None
