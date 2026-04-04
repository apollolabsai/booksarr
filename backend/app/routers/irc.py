import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.config import DOWNLOADS_DIR
from backend.app.database import get_db
from backend.app.models import (
    Book,
    IrcBulkDownloadBatch,
    IrcBulkDownloadItem,
    IrcDownloadJob,
    IrcSearchJob,
    IrcSearchResult,
    Setting,
)
from backend.app.schemas.irc import (
    IrcBulkBatchCreateRequest,
    IrcBulkDownloadBatchSummary,
    IrcBulkDownloadItemSummary,
    IrcBulkSearchQueuedItem,
    IrcBulkSearchRequest,
    IrcBulkSearchResponse,
    IrcBulkSearchSkippedItem,
    IrcDownloadRequest,
    IrcDownloadJobSummary,
    IrcSearchRequest,
    IrcSearchResultSummary,
    IrcSearchJobSummary,
    IrcSettingsResponse,
    IrcSettingsUpdate,
    IrcWorkerStatusResponse,
)
from backend.app.services.vpn_manager import normalize_pia_region
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

ACTIVE_SEARCH_STATUSES = {"queued", "sent", "waiting_dcc", "downloading_results"}
ACTIVE_DOWNLOAD_STATUSES = {
    "queued",
    "sent",
    "waiting_dcc",
    "downloading",
    "extracting",
    "importing",
    "refreshing_library",
}


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
        vpn_enabled=settings["vpn_enabled"],
        vpn_region=settings["vpn_region"],
        vpn_username=settings["vpn_username"],
        vpn_password_set=bool(settings["vpn_password"]),
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
        "irc_vpn_enabled": _bool_to_text(body.vpn_enabled) if body.vpn_enabled is not None else None,
        "irc_vpn_region": normalize_pia_region(body.vpn_region) if body.vpn_region is not None else None,
        "irc_vpn_username": body.vpn_username,
        "irc_vpn_password": body.vpn_password,
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


@router.post("/bulk-batches", response_model=IrcBulkDownloadBatchSummary)
async def create_bulk_batch(body: IrcBulkBatchCreateRequest, db: AsyncSession = Depends(get_db)):
    seen_book_ids: set[int] = set()
    requested_book_ids: list[int] = []
    for book_id in body.book_ids:
        if book_id in seen_book_ids:
            continue
        seen_book_ids.add(book_id)
        requested_book_ids.append(book_id)

    result = await db.execute(
        select(Book)
        .options(selectinload(Book.author))
        .where(Book.id.in_(requested_book_ids))
    )
    books = result.scalars().all()
    books_by_id = {book.id: book for book in books}

    missing_book_ids = [book_id for book_id in requested_book_ids if book_id not in books_by_id]
    if missing_book_ids:
        raise HTTPException(status_code=404, detail=f"Book not found: {missing_book_ids[0]}")

    request_id = uuid4().hex[:12]
    batch = IrcBulkDownloadBatch(request_id=request_id, status="queued")
    db.add(batch)
    await db.flush()

    for position, book_id in enumerate(requested_book_ids, start=1):
        book = books_by_id[book_id]
        item = IrcBulkDownloadItem(
            batch_id=batch.id,
            book_id=book.id,
            position=position,
            status="queued",
            query_text=normalize_query_text(" ".join(part for part in [book.author.name if book.author else "", book.title] if part).strip()),
        )
        db.add(item)

    await db.commit()
    return await _get_bulk_batch_summary(batch.id, db)


@router.get("/bulk-batches/{batch_id}", response_model=IrcBulkDownloadBatchSummary)
async def get_bulk_batch(batch_id: int, db: AsyncSession = Depends(get_db)):
    return await _get_bulk_batch_summary(batch_id, db)


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
        auto_download=body.auto_download,
        bulk_request_id=None,
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


@router.post("/search/bulk", response_model=IrcBulkSearchResponse)
async def create_bulk_search_jobs(body: IrcBulkSearchRequest, db: AsyncSession = Depends(get_db)):
    bulk_request_id = uuid4().hex[:12]
    seen_book_ids: set[int] = set()
    requested_book_ids: list[int] = []
    for book_id in body.book_ids:
        if book_id in seen_book_ids:
            continue
        seen_book_ids.add(book_id)
        requested_book_ids.append(book_id)

    logger.info(
        "IRC bulk search request started: bulk_request_id=%s requested_books=%s skip_owned=%s auto_download_single_result=%s",
        bulk_request_id,
        len(requested_book_ids),
        body.skip_owned,
        body.auto_download_single_result,
    )

    result = await db.execute(
        select(Book)
        .options(selectinload(Book.author))
        .where(Book.id.in_(requested_book_ids))
    )
    books = result.scalars().all()
    books_by_id = {book.id: book for book in books}

    missing_book_ids = [book_id for book_id in requested_book_ids if book_id not in books_by_id]
    if missing_book_ids:
        raise HTTPException(status_code=404, detail=f"Book not found: {missing_book_ids[0]}")

    active_search_result = await db.execute(
        select(IrcSearchJob.book_id).where(
            IrcSearchJob.book_id.in_(requested_book_ids),
            IrcSearchJob.status.in_(ACTIVE_SEARCH_STATUSES),
        )
    )
    active_search_book_ids = {book_id for book_id in active_search_result.scalars().all() if book_id is not None}

    active_download_result = await db.execute(
        select(IrcDownloadJob.book_id).where(
            IrcDownloadJob.book_id.in_(requested_book_ids),
            IrcDownloadJob.status.in_(ACTIVE_DOWNLOAD_STATUSES),
        )
    )
    active_download_book_ids = {book_id for book_id in active_download_result.scalars().all() if book_id is not None}

    queued_books: list[IrcBulkSearchQueuedItem] = []
    skipped_books: list[IrcBulkSearchSkippedItem] = []
    jobs_to_refresh: list[IrcSearchJob] = []

    for book_id in requested_book_ids:
        book = books_by_id[book_id]
        author_name = book.author.name if book.author else None

        if body.skip_owned and book.is_owned:
            skipped_item = IrcBulkSearchSkippedItem(
                book_id=book.id,
                title=book.title,
                author_name=author_name,
                reason="owned",
            )
            skipped_books.append(skipped_item)
            logger.info(
                "IRC bulk search request %s skipped book_id=%s title=%r author=%r reason=%s",
                bulk_request_id,
                skipped_item.book_id,
                skipped_item.title,
                skipped_item.author_name,
                skipped_item.reason,
            )
            continue

        if book.id in active_search_book_ids:
            skipped_item = IrcBulkSearchSkippedItem(
                book_id=book.id,
                title=book.title,
                author_name=author_name,
                reason="search_already_queued",
            )
            skipped_books.append(skipped_item)
            logger.info(
                "IRC bulk search request %s skipped book_id=%s title=%r author=%r reason=%s",
                bulk_request_id,
                skipped_item.book_id,
                skipped_item.title,
                skipped_item.author_name,
                skipped_item.reason,
            )
            continue

        if book.id in active_download_book_ids:
            skipped_item = IrcBulkSearchSkippedItem(
                book_id=book.id,
                title=book.title,
                author_name=author_name,
                reason="download_already_queued",
            )
            skipped_books.append(skipped_item)
            logger.info(
                "IRC bulk search request %s skipped book_id=%s title=%r author=%r reason=%s",
                bulk_request_id,
                skipped_item.book_id,
                skipped_item.title,
                skipped_item.author_name,
                skipped_item.reason,
            )
            continue

        query_text = normalize_query_text(" ".join(part for part in [author_name or "", book.title] if part).strip())
        normalized_query = normalize_query_key(query_text)
        if not query_text or not normalized_query:
            skipped_item = IrcBulkSearchSkippedItem(
                book_id=book.id,
                title=book.title,
                author_name=author_name,
                reason="invalid_query",
            )
            skipped_books.append(skipped_item)
            logger.info(
                "IRC bulk search request %s skipped book_id=%s title=%r author=%r reason=%s",
                bulk_request_id,
                skipped_item.book_id,
                skipped_item.title,
                skipped_item.author_name,
                skipped_item.reason,
            )
            continue

        job = IrcSearchJob(
            book_id=book.id,
            query_text=query_text,
            normalized_query=normalized_query,
            status="queued",
            auto_download=body.auto_download_single_result,
            bulk_request_id=bulk_request_id,
            request_message=build_search_command(query_text),
            expected_result_filename=build_expected_result_filename(query_text),
        )
        db.add(job)
        jobs_to_refresh.append(job)
        queued_books.append(IrcBulkSearchQueuedItem(
            book_id=book.id,
            title=book.title,
            author_name=author_name,
            query_text=query_text,
            job=IrcSearchJobSummary(
                id=0,
                book_id=book.id,
                query_text=query_text,
                status="queued",
                auto_download=body.auto_download_single_result,
                bulk_request_id=bulk_request_id,
                expected_result_filename=job.expected_result_filename,
                result_count=0,
                error_message=None,
                created_at=None,
                updated_at=None,
                completed_at=None,
            ),
        ))

    await db.commit()
    for job in jobs_to_refresh:
        await db.refresh(job)

    for item, job in zip(queued_books, jobs_to_refresh):
        item.job = _search_job_summary(job)

    if queued_books:
        logger.info(
            "IRC bulk search request completed: bulk_request_id=%s queued=%s skipped=%s book_ids=%s auto_download_single_result=%s",
            bulk_request_id,
            len(queued_books),
            len(skipped_books),
            [item.book_id for item in queued_books],
            body.auto_download_single_result,
        )
    else:
        logger.info(
            "IRC bulk search request completed: bulk_request_id=%s queued=0 skipped=%s auto_download_single_result=%s",
            bulk_request_id,
            len(skipped_books),
            body.auto_download_single_result,
        )

    return IrcBulkSearchResponse(
        queued=queued_books,
        skipped=skipped_books,
    )


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
            bulk_request_id=job.bulk_request_id,
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


@router.get("/download-jobs/{job_id}", response_model=IrcDownloadJobSummary)
async def get_download_job(job_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(IrcDownloadJob).where(IrcDownloadJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="IRC download job not found")

    return IrcDownloadJobSummary(
        id=job.id,
        book_id=job.book_id,
        search_job_id=job.search_job_id,
        search_result_id=job.search_result_id,
        status=job.status,
        bulk_request_id=job.bulk_request_id,
        dcc_filename=job.dcc_filename,
        saved_path=job.saved_path,
        moved_to_library_path=job.moved_to_library_path,
        error_message=job.error_message,
        created_at=_iso(job.created_at),
        updated_at=_iso(job.updated_at),
        completed_at=_iso(job.completed_at),
    )


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
        bulk_request_id=search_job.bulk_request_id,
        request_message=search_result.download_command,
        dcc_filename=search_result.display_name,
    )
    db.add(download_job)
    await db.commit()
    await db.refresh(download_job)

    logger.info(
        "IRC download job queued: job_id=%s search_job_id=%s search_result_id=%s book_id=%s bulk_request_id=%s command=%r",
        download_job.id,
        search_job.id,
        search_result.id,
        search_job.book_id,
        search_job.bulk_request_id,
        download_job.request_message,
    )
    return IrcDownloadJobSummary(
        id=download_job.id,
        book_id=download_job.book_id,
        search_job_id=download_job.search_job_id,
        search_result_id=download_job.search_result_id,
        status=download_job.status,
        bulk_request_id=download_job.bulk_request_id,
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
        "vpn_enabled": settings.get("irc_vpn_enabled", "false").lower() == "true",
        "vpn_region": normalize_pia_region(settings.get("irc_vpn_region", "Netherlands")),
        "vpn_username": settings.get("irc_vpn_username", ""),
        "vpn_password": settings.get("irc_vpn_password", ""),
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
        select(func.count(IrcSearchJob.id)).where(IrcSearchJob.status.in_(ACTIVE_SEARCH_STATUSES))
    )
    download_result = await db.execute(
        select(func.count(IrcDownloadJob.id)).where(
            IrcDownloadJob.status.in_(ACTIVE_DOWNLOAD_STATUSES)
        )
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
        auto_download=job.auto_download,
        bulk_request_id=job.bulk_request_id,
        expected_result_filename=job.expected_result_filename,
        result_count=len(job.results),
        error_message=job.error_message,
        created_at=_iso(job.created_at),
        updated_at=_iso(job.updated_at),
        completed_at=_iso(job.completed_at),
    )


async def _get_bulk_batch_summary(batch_id: int, db: AsyncSession) -> IrcBulkDownloadBatchSummary:
    result = await db.execute(
        select(IrcBulkDownloadBatch)
        .options(
            selectinload(IrcBulkDownloadBatch.items)
            .selectinload(IrcBulkDownloadItem.book)
            .selectinload(Book.author),
            selectinload(IrcBulkDownloadBatch.items).selectinload(IrcBulkDownloadItem.search_job).selectinload(IrcSearchJob.results),
            selectinload(IrcBulkDownloadBatch.items).selectinload(IrcBulkDownloadItem.download_job),
        )
        .where(IrcBulkDownloadBatch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if batch is None:
        raise HTTPException(status_code=404, detail="IRC bulk batch not found")

    items = [_bulk_item_summary(item) for item in sorted(batch.items, key=lambda row: row.position)]
    completed_books = sum(1 for item in batch.items if item.status == "completed")
    failed_books = sum(1 for item in batch.items if item.status == "failed")

    return IrcBulkDownloadBatchSummary(
        id=batch.id,
        request_id=batch.request_id,
        status=batch.status,
        total_books=len(batch.items),
        completed_books=completed_books,
        failed_books=failed_books,
        items=items,
        created_at=_iso(batch.created_at),
        updated_at=_iso(batch.updated_at),
        completed_at=_iso(batch.completed_at),
    )


def _bulk_item_summary(item: IrcBulkDownloadItem) -> IrcBulkDownloadItemSummary:
    book = item.book
    title = book.title if book else f"Book {item.book_id}"
    author_name = book.author.name if book and book.author else None
    attempt_count = len(_parse_attempted_result_ids(item.attempted_result_ids))
    return IrcBulkDownloadItemSummary(
        id=item.id,
        book_id=item.book_id,
        title=title,
        author_name=author_name,
        position=item.position,
        status=item.status,
        query_text=item.query_text,
        error_message=item.error_message,
        selected_result_label=item.selected_result_label,
        attempt_count=attempt_count,
        search_job=_search_job_summary(item.search_job) if item.search_job is not None else None,
        download_job=_download_job_summary(item.download_job) if item.download_job is not None else None,
        created_at=_iso(item.created_at),
        updated_at=_iso(item.updated_at),
        completed_at=_iso(item.completed_at),
    )


def _download_job_summary(job: IrcDownloadJob) -> IrcDownloadJobSummary:
    return IrcDownloadJobSummary(
        id=job.id,
        book_id=job.book_id,
        search_job_id=job.search_job_id,
        search_result_id=job.search_result_id,
        status=job.status,
        bulk_request_id=job.bulk_request_id,
        dcc_filename=job.dcc_filename,
        saved_path=job.saved_path,
        moved_to_library_path=job.moved_to_library_path,
        error_message=job.error_message,
        created_at=_iso(job.created_at),
        updated_at=_iso(job.updated_at),
        completed_at=_iso(job.completed_at),
    )


def _parse_attempted_result_ids(value: str | None) -> list[int]:
    if not value:
        return []
    result: list[int] = []
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            result.append(int(chunk))
        except ValueError:
            continue
    return result
