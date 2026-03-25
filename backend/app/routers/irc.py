import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.config import DOWNLOADS_DIR
from backend.app.database import get_db
from backend.app.models import Book, IrcDownloadJob, IrcSearchJob, IrcSearchResult, Setting
from backend.app.schemas.irc import (
    IrcDownloadRequest,
    IrcDownloadJobSummary,
    IrcSearchRequest,
    IrcSearchResultSummary,
    IrcSearchJobSummary,
    IrcSettingsResponse,
    IrcSettingsUpdate,
    IrcWorkerStatusResponse,
)
from backend.app.services.irc_parser import (
    build_expected_result_filename,
    build_search_command,
    normalize_query_key,
    normalize_query_text,
)
from backend.app.services.irc_worker import (
    get_runtime_status,
    request_connect,
    request_disconnect,
)

logger = logging.getLogger("booksarr.irc")

router = APIRouter(prefix="/api/irc", tags=["irc"])


@router.get("/settings", response_model=IrcSettingsResponse)
async def get_irc_settings(db: AsyncSession = Depends(get_db)):
    settings = await _load_settings(db)
    return IrcSettingsResponse(
        enabled=settings["enabled"],
        server=settings["server"],
        port=settings["port"],
        use_tls=settings["use_tls"],
        nickname=settings["nickname"],
        username=settings["username"],
        real_name=settings["real_name"],
        channel=settings["channel"],
        channel_password_set=bool(settings["channel_password"]),
        auto_move_to_library=settings["auto_move_to_library"],
        downloads_dir=str(DOWNLOADS_DIR),
    )


@router.put("/settings")
async def update_irc_settings(body: IrcSettingsUpdate, db: AsyncSession = Depends(get_db)):
    updates = {
        "irc_enabled": _bool_to_text(body.enabled) if body.enabled is not None else None,
        "irc_server": body.server,
        "irc_port": str(body.port) if body.port is not None else None,
        "irc_use_tls": _bool_to_text(body.use_tls) if body.use_tls is not None else None,
        "irc_nickname": body.nickname,
        "irc_username": body.username,
        "irc_real_name": body.real_name,
        "irc_channel": body.channel,
        "irc_channel_password": body.channel_password,
        "irc_auto_move_to_library": _bool_to_text(body.auto_move_to_library) if body.auto_move_to_library is not None else None,
    }
    for key, value in updates.items():
        if value is None:
            continue
        await _upsert_setting(db, key, value)

    await db.commit()
    logger.info("IRC settings updated")
    return {"status": "ok"}


@router.get("/status", response_model=IrcWorkerStatusResponse)
async def get_irc_status(db: AsyncSession = Depends(get_db)):
    runtime = get_runtime_status()
    queued_search_jobs, queued_download_jobs = await _get_queue_counts(db)
    return IrcWorkerStatusResponse(
        enabled=runtime.enabled,
        desired_connection=runtime.desired_connection,
        connected=runtime.connected,
        joined_channel=runtime.joined_channel,
        state=runtime.state,
        server=runtime.server,
        channel=runtime.channel,
        nickname=runtime.nickname,
        active_search_job_id=runtime.active_search_job_id,
        active_download_job_id=runtime.active_download_job_id,
        last_message=runtime.last_message,
        last_error=runtime.last_error,
        queued_search_jobs=queued_search_jobs,
        queued_download_jobs=queued_download_jobs,
    )


@router.post("/connect")
async def connect_irc():
    await request_connect()
    return {"status": "ok", "message": "IRC connection requested"}


@router.post("/disconnect")
async def disconnect_irc():
    await request_disconnect()
    return {"status": "ok", "message": "IRC disconnect requested"}


@router.get("/search-jobs", response_model=list[IrcSearchJobSummary])
async def list_search_jobs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(IrcSearchJob)
        .options(selectinload(IrcSearchJob.results))
        .order_by(IrcSearchJob.created_at.desc())
        .limit(25)
    )
    jobs = result.scalars().all()
    return [_search_job_summary(job) for job in jobs]


@router.post("/search", response_model=IrcSearchJobSummary)
async def create_search_job(body: IrcSearchRequest, db: AsyncSession = Depends(get_db)):
    query_text = normalize_query_text(body.query_text)
    normalized_query = normalize_query_key(query_text)
    if not query_text or not normalized_query:
        raise HTTPException(status_code=400, detail="Search query must contain letters or numbers")

    book_context = None
    if body.book_id is not None:
        book_result = await db.execute(select(Book).where(Book.id == body.book_id))
        book = book_result.scalar_one_or_none()
        if book is None:
            raise HTTPException(status_code=404, detail="Book not found")
        book_context = f"{book.title}"

    job = IrcSearchJob(
        book_id=body.book_id,
        query_text=query_text,
        normalized_query=normalized_query,
        status="queued",
        request_message=build_search_command(query_text),
        expected_result_filename=build_expected_result_filename(query_text),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    logger.info(
        "IRC search job queued: job_id=%s book_id=%s book=%r query=%r command=%r expected_result=%r",
        job.id,
        body.book_id,
        book_context,
        query_text,
        job.request_message,
        job.expected_result_filename,
    )
    return _search_job_summary(job)


@router.get("/search-jobs/{job_id}", response_model=IrcSearchJobSummary)
async def get_search_job(job_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(IrcSearchJob)
        .options(selectinload(IrcSearchJob.results))
        .where(IrcSearchJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="IRC search job not found")
    return _search_job_summary(job)


@router.get("/search-jobs/{job_id}/results", response_model=list[IrcSearchResultSummary])
async def get_search_results(job_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(IrcSearchJob)
        .options(selectinload(IrcSearchJob.results))
        .where(IrcSearchJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="IRC search job not found")

    return [
        IrcSearchResultSummary(
            id=row.id,
            search_job_id=row.search_job_id,
            result_index=row.result_index,
            raw_line=row.raw_line,
            bot_name=row.bot_name,
            display_name=row.display_name,
            file_format=row.file_format,
            file_size_text=row.file_size_text,
            download_command=row.download_command,
            selected=row.selected,
        )
        for row in sorted(job.results, key=lambda item: item.result_index)
    ]


@router.get("/download-jobs", response_model=list[IrcDownloadJobSummary])
async def list_download_jobs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(IrcDownloadJob).order_by(IrcDownloadJob.created_at.desc()).limit(25)
    )
    jobs = result.scalars().all()
    return [
        IrcDownloadJobSummary(
            id=job.id,
            book_id=job.book_id,
            search_job_id=job.search_job_id,
            search_result_id=job.search_result_id,
            status=job.status,
            dcc_filename=job.dcc_filename,
            saved_path=job.saved_path,
            moved_to_library_path=job.moved_to_library_path,
            error_message=job.error_message,
            created_at=_iso(job.created_at),
            updated_at=_iso(job.updated_at),
            completed_at=_iso(job.completed_at),
        )
        for job in jobs
    ]


@router.post("/download", response_model=IrcDownloadJobSummary)
async def create_download_job(body: IrcDownloadRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(IrcSearchResult)
        .options(selectinload(IrcSearchResult.search_job))
        .where(IrcSearchResult.id == body.search_result_id)
    )
    search_result = result.scalar_one_or_none()
    if search_result is None:
        raise HTTPException(status_code=404, detail="IRC search result not found")

    search_job = search_result.search_job
    if search_job is None:
        raise HTTPException(status_code=404, detail="IRC search job not found for selected result")

    selected_rows = await db.execute(
        select(IrcSearchResult).where(IrcSearchResult.search_job_id == search_job.id)
    )
    for row in selected_rows.scalars().all():
        row.selected = row.id == search_result.id

    download_job = IrcDownloadJob(
        book_id=search_job.book_id,
        search_job_id=search_job.id,
        search_result_id=search_result.id,
        status="queued",
        request_message=search_result.download_command,
        dcc_filename=search_result.display_name,
    )
    db.add(download_job)
    await db.commit()
    await db.refresh(download_job)

    logger.info(
        "IRC download job queued: job_id=%s search_job_id=%s search_result_id=%s book_id=%s command=%r",
        download_job.id,
        search_job.id,
        search_result.id,
        search_job.book_id,
        download_job.request_message,
    )
    return IrcDownloadJobSummary(
        id=download_job.id,
        book_id=download_job.book_id,
        search_job_id=download_job.search_job_id,
        search_result_id=download_job.search_result_id,
        status=download_job.status,
        dcc_filename=download_job.dcc_filename,
        saved_path=download_job.saved_path,
        moved_to_library_path=download_job.moved_to_library_path,
        error_message=download_job.error_message,
        created_at=_iso(download_job.created_at),
        updated_at=_iso(download_job.updated_at),
        completed_at=_iso(download_job.completed_at),
    )


async def _load_settings(db: AsyncSession) -> dict[str, object]:
    result = await db.execute(select(Setting).where(Setting.key.like("irc_%")))
    settings = {row.key: row.value for row in result.scalars().all()}
    return {
        "enabled": settings.get("irc_enabled", "false").lower() == "true",
        "server": settings.get("irc_server", ""),
        "port": int(settings.get("irc_port", "6697")),
        "use_tls": settings.get("irc_use_tls", "true").lower() == "true",
        "nickname": settings.get("irc_nickname", ""),
        "username": settings.get("irc_username", ""),
        "real_name": settings.get("irc_real_name", ""),
        "channel": settings.get("irc_channel", ""),
        "channel_password": settings.get("irc_channel_password", ""),
        "auto_move_to_library": settings.get("irc_auto_move_to_library", "true").lower() == "true",
    }


async def _upsert_setting(db: AsyncSession, key: str, value: str):
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        db.add(Setting(key=key, value=value))


async def _get_queue_counts(db: AsyncSession) -> tuple[int, int]:
    search_result = await db.execute(
        select(func.count(IrcSearchJob.id)).where(IrcSearchJob.status.in_(["queued", "sent", "waiting_dcc", "downloading_results"]))
    )
    download_result = await db.execute(
        select(func.count(IrcDownloadJob.id)).where(IrcDownloadJob.status.in_(["queued", "sent", "waiting_dcc", "downloading"]))
    )
    return search_result.scalar() or 0, download_result.scalar() or 0


def _bool_to_text(value: bool) -> str:
    return "true" if value else "false"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _search_job_summary(job: IrcSearchJob) -> IrcSearchJobSummary:
    return IrcSearchJobSummary(
        id=job.id,
        book_id=job.book_id,
        query_text=job.query_text,
        status=job.status,
        expected_result_filename=job.expected_result_filename,
        result_count=len(job.results),
        error_message=job.error_message,
        created_at=_iso(job.created_at),
        updated_at=_iso(job.updated_at),
        completed_at=_iso(job.completed_at),
    )
