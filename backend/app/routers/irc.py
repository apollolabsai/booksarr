import logging
from datetime import datetime, timezone
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
    IrcDownloadFeedEntry,
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
    get_online_irc_nicks,
    get_runtime_status,
    is_bot_online,
    serialize_bulk_file_type_preferences,
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
ACTIVE_BATCH_ITEM_STATUSES = {
    "searching",
    "downloading_search_results",
    "choosing_best_option",
    "downloading_book",
    "extracting",
    "importing",
}
ACTIVE_FEED_ITEM_STATUSES = {
    "queued",
    "searching",
    "downloading_search_results",
    "choosing_best_option",
    "downloading_book",
    "extracting",
    "importing",
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
        online_bots=get_online_irc_nicks(),
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
    batch = IrcBulkDownloadBatch(
        request_id=request_id,
        status="queued",
        file_type_preferences=serialize_bulk_file_type_preferences(
            [preference.model_dump() for preference in body.file_type_preferences]
        ),
    )
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


@router.post("/bulk-batches/{batch_id}/pause", response_model=IrcBulkDownloadBatchSummary)
async def pause_bulk_batch(batch_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(IrcBulkDownloadBatch)
        .options(selectinload(IrcBulkDownloadBatch.items))
        .where(IrcBulkDownloadBatch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if batch is None:
        raise HTTPException(status_code=404, detail="IRC bulk batch not found")

    if batch.status in {"completed", "cancelled"}:
        return await _get_bulk_batch_summary(batch.id, db)

    now = datetime.utcnow()
    has_active_item = any(item.status in ACTIVE_BATCH_ITEM_STATUSES for item in batch.items)
    has_queued_item = any(item.status == "queued" for item in batch.items)

    if has_active_item:
        batch.status = "pausing"
    elif has_queued_item:
        batch.status = "paused"
    else:
        batch.status = "completed"
        batch.completed_at = now

    batch.updated_at = now
    await db.commit()
    logger.info("IRC bulk batch %s pause requested: new_status=%s", batch.request_id, batch.status)
    return await _get_bulk_batch_summary(batch.id, db)


@router.post("/bulk-batches/{batch_id}/resume", response_model=IrcBulkDownloadBatchSummary)
async def resume_bulk_batch(batch_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(IrcBulkDownloadBatch)
        .options(selectinload(IrcBulkDownloadBatch.items))
        .where(IrcBulkDownloadBatch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if batch is None:
        raise HTTPException(status_code=404, detail="IRC bulk batch not found")

    if batch.status in {"paused", "pausing"}:
        batch.status = "running"
        batch.updated_at = datetime.utcnow()
        await db.commit()
        logger.info("IRC bulk batch %s resumed", batch.request_id)

    return await _get_bulk_batch_summary(batch.id, db)


@router.post("/bulk-batches/{batch_id}/cancel", response_model=IrcBulkDownloadBatchSummary)
async def cancel_bulk_batch(batch_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(IrcBulkDownloadBatch)
        .options(
            selectinload(IrcBulkDownloadBatch.items)
            .selectinload(IrcBulkDownloadItem.search_job),
            selectinload(IrcBulkDownloadBatch.items)
            .selectinload(IrcBulkDownloadItem.download_job),
        )
        .where(IrcBulkDownloadBatch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if batch is None:
        raise HTTPException(status_code=404, detail="IRC bulk batch not found")

    if batch.status in {"completed", "cancelled"}:
        return await _get_bulk_batch_summary(batch.id, db)

    now = datetime.utcnow()
    active_item = next((item for item in batch.items if item.status in ACTIVE_BATCH_ITEM_STATUSES), None)
    queued_items = [item for item in batch.items if item.status == "queued"]

    for item in queued_items:
        if item.search_job is not None:
            item.search_job.status = "cancelled"
            item.search_job.error_message = "Cancelled by user"
            item.search_job.updated_at = now
            item.search_job.completed_at = now
        if item.download_job is not None:
            item.download_job.status = "cancelled"
            item.download_job.error_message = "Cancelled by user"
            item.download_job.updated_at = now
            item.download_job.completed_at = now
        await db.delete(item)

    if active_item is not None:
        batch.status = "cancelling"
    else:
        batch.status = "cancelled"
        batch.completed_at = now
    batch.updated_at = now
    await db.commit()
    logger.info(
        "IRC bulk batch %s cancel requested: removed_queued_items=%s active_item_id=%s new_status=%s",
        batch.request_id,
        len(queued_items),
        active_item.id if active_item is not None else None,
        batch.status,
    )
    return await _get_bulk_batch_summary(batch.id, db)


@router.get("/downloads-feed", response_model=list[IrcDownloadFeedEntry])
async def get_downloads_feed(db: AsyncSession = Depends(get_db)):
    bulk_items_result = await db.execute(
        select(IrcBulkDownloadItem)
        .options(
            selectinload(IrcBulkDownloadItem.batch),
            selectinload(IrcBulkDownloadItem.book).selectinload(Book.author),
            selectinload(IrcBulkDownloadItem.search_job).selectinload(IrcSearchJob.results),
            selectinload(IrcBulkDownloadItem.download_job).selectinload(IrcDownloadJob.search_result),
            selectinload(IrcBulkDownloadItem.selected_search_result),
        )
        .order_by(IrcBulkDownloadItem.created_at.desc())
        .limit(100)
    )
    bulk_items = bulk_items_result.scalars().all()

    single_search_result = await db.execute(
        select(IrcSearchJob)
        .options(
            selectinload(IrcSearchJob.results),
            selectinload(IrcSearchJob.download_jobs).selectinload(IrcDownloadJob.search_result),
        )
        .where(IrcSearchJob.bulk_item_id.is_(None))
        .order_by(IrcSearchJob.created_at.desc())
        .limit(100)
    )
    single_search_jobs = single_search_result.scalars().all()

    single_book_ids = sorted({job.book_id for job in single_search_jobs if job.book_id is not None})
    books_by_id: dict[int, Book] = {}
    if single_book_ids:
        books_result = await db.execute(
            select(Book)
            .options(selectinload(Book.author))
            .where(Book.id.in_(single_book_ids))
        )
        books_by_id = {book.id: book for book in books_result.scalars().all()}

    entries = [
        *[_bulk_feed_entry(item) for item in bulk_items],
        *[_single_search_feed_entry(job, books_by_id) for job in single_search_jobs],
    ]
    active_entries = [entry for entry in entries if entry.active]
    inactive_entries = [entry for entry in entries if not entry.active]
    active_entries.sort(key=lambda entry: (entry.sort_timestamp or "", entry.entry_id), reverse=True)
    inactive_entries.sort(key=lambda entry: (entry.sort_timestamp or "", entry.entry_id), reverse=True)
    return active_entries + inactive_entries


@router.delete("/downloads-feed")
async def clear_downloads_feed_history(db: AsyncSession = Depends(get_db)):
    deleted_batches = 0
    deleted_single_jobs = 0

    completed_batch_result = await db.execute(
        select(IrcBulkDownloadBatch)
        .options(
            selectinload(IrcBulkDownloadBatch.items)
            .selectinload(IrcBulkDownloadItem.search_job)
            .selectinload(IrcSearchJob.results),
            selectinload(IrcBulkDownloadBatch.items)
            .selectinload(IrcBulkDownloadItem.download_job),
        )
        .where(IrcBulkDownloadBatch.status.in_(["completed", "cancelled"]))
    )
    completed_batches = completed_batch_result.scalars().all()

    for batch in completed_batches:
        for item in batch.items:
            search_job = item.search_job
            download_job = item.download_job
            item.search_job = None
            item.search_job_id = None
            item.download_job = None
            item.download_job_id = None
            item.selected_search_result = None
            item.selected_search_result_id = None
            if download_job is not None:
                await db.delete(download_job)
            if search_job is not None:
                await db.delete(search_job)
        await db.flush()
        await db.delete(batch)
        deleted_batches += 1

    single_search_result = await db.execute(
        select(IrcSearchJob)
        .options(
            selectinload(IrcSearchJob.download_jobs),
            selectinload(IrcSearchJob.results),
        )
        .where(IrcSearchJob.bulk_item_id.is_(None))
    )
    single_search_jobs = single_search_result.scalars().all()

    for job in single_search_jobs:
        latest_download_job = max(
            job.download_jobs,
            key=lambda row: (row.created_at or datetime.min, row.id),
            default=None,
        )
        if _is_single_feed_active(job, latest_download_job):
            continue
        for download_job in job.download_jobs:
            await db.delete(download_job)
        await db.delete(job)
        deleted_single_jobs += 1

    await db.commit()
    logger.info(
        "IRC downloads history cleared: deleted_batches=%s deleted_single_jobs=%s",
        deleted_batches,
        deleted_single_jobs,
    )
    return {
        "status": "ok",
        "deleted_batches": deleted_batches,
        "deleted_single_jobs": deleted_single_jobs,
    }


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
            bot_online=is_bot_online(row.bot_name),
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
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


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
            selectinload(IrcBulkDownloadBatch.items).selectinload(IrcBulkDownloadItem.selected_search_result),
        )
        .where(IrcBulkDownloadBatch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if batch is None:
        raise HTTPException(status_code=404, detail="IRC bulk batch not found")

    items = [_bulk_item_summary(item) for item in sorted(batch.items, key=lambda row: row.position)]
    completed_books = sum(1 for item in batch.items if item.status == "completed")
    failed_books = sum(1 for item in batch.items if item.status == "failed")
    cancelled_books = sum(1 for item in batch.items if item.status == "cancelled")

    return IrcBulkDownloadBatchSummary(
        id=batch.id,
        request_id=batch.request_id,
        status=batch.status,
        total_books=len(batch.items),
        completed_books=completed_books,
        failed_books=failed_books,
        cancelled_books=cancelled_books,
        items=items,
        created_at=_iso(batch.created_at),
        updated_at=_iso(batch.updated_at),
        completed_at=_iso(batch.completed_at),
    )


def _bulk_item_summary(item: IrcBulkDownloadItem) -> IrcBulkDownloadItemSummary:
    book = item.book
    title = book.title if book else f"Book {item.book_id}"
    author_id = book.author.id if book and book.author else None
    author_name = book.author.name if book and book.author else None
    attempt_count = len(_parse_attempted_result_ids(item.attempted_result_ids))
    selected_result_text = (
        item.selected_search_result.raw_line
        if item.selected_search_result is not None and item.selected_search_result.raw_line
        else item.selected_result_label
    )
    return IrcBulkDownloadItemSummary(
        id=item.id,
        book_id=item.book_id,
        title=title,
        author_id=author_id,
        author_name=author_name,
        position=item.position,
        status=item.status,
        query_text=item.query_text,
        error_message=item.error_message,
        selected_result_label=selected_result_text,
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


def _bulk_feed_entry(item: IrcBulkDownloadItem) -> IrcDownloadFeedEntry:
    status = item.status
    final_result_kind = None
    final_result_text = None
    if item.download_job is not None and item.download_job.moved_to_library_path:
        final_result_kind = "imported"
        final_result_text = item.download_job.moved_to_library_path
    elif item.error_message:
        final_result_kind = "error"
        final_result_text = item.error_message
    elif item.download_job is not None and item.download_job.error_message:
        final_result_kind = "error"
        final_result_text = item.download_job.error_message

    return IrcDownloadFeedEntry(
        entry_id=f"bulk-{item.id}",
        source="bulk",
        batch_id=item.batch_id,
        bulk_request_id=item.batch.request_id if item.batch is not None else None,
        book_id=item.book_id,
        title=item.book.title if item.book is not None else f"Book {item.book_id}",
        author_id=item.book.author.id if item.book is not None and item.book.author is not None else None,
        author_name=item.book.author.name if item.book is not None and item.book.author is not None else None,
        status=status,
        query_text=item.query_text,
        selected_result_label=(
            item.selected_search_result.raw_line
            if item.selected_search_result is not None and item.selected_search_result.raw_line
            else item.selected_result_label
        ),
        attempt_count=len(_parse_attempted_result_ids(item.attempted_result_ids)),
        active=status in ACTIVE_FEED_ITEM_STATUSES,
        final_result_kind=final_result_kind,
        final_result_text=final_result_text,
        sort_timestamp=_iso(item.completed_at or item.updated_at or item.created_at),
        created_at=_iso(item.created_at),
        updated_at=_iso(item.updated_at),
        completed_at=_iso(item.completed_at),
        search_job=_search_job_summary(item.search_job) if item.search_job is not None else None,
        download_job=_download_job_summary(item.download_job) if item.download_job is not None else None,
    )


def _single_search_feed_entry(job: IrcSearchJob, books_by_id: dict[int, Book]) -> IrcDownloadFeedEntry:
    book = books_by_id.get(job.book_id) if job.book_id is not None else None
    latest_download_job = max(
        job.download_jobs,
        key=lambda row: (row.created_at or datetime.min, row.id),
        default=None,
    )
    status = _single_feed_status(job, latest_download_job)
    active = _is_single_feed_active(job, latest_download_job)
    final_result_kind = None
    final_result_text = None
    if latest_download_job is not None and latest_download_job.moved_to_library_path:
        final_result_kind = "imported"
        final_result_text = latest_download_job.moved_to_library_path
    elif latest_download_job is not None and latest_download_job.saved_path:
        final_result_kind = "downloaded"
        final_result_text = latest_download_job.saved_path
    elif latest_download_job is not None and latest_download_job.error_message:
        final_result_kind = "error"
        final_result_text = latest_download_job.error_message
    elif job.error_message:
        final_result_kind = "error"
        final_result_text = job.error_message

    selected_result_label = None
    if latest_download_job is not None and latest_download_job.search_result is not None:
        selected_result_label = latest_download_job.search_result.raw_line or latest_download_job.search_result.display_name

    return IrcDownloadFeedEntry(
        entry_id=f"single-search-{job.id}",
        source="single",
        batch_id=None,
        bulk_request_id=job.bulk_request_id,
        book_id=job.book_id,
        title=book.title if book is not None else job.query_text,
        author_id=book.author.id if book is not None and book.author is not None else None,
        author_name=book.author.name if book is not None and book.author is not None else None,
        status=status,
        query_text=job.query_text,
        selected_result_label=selected_result_label,
        attempt_count=len(job.download_jobs),
        active=active,
        final_result_kind=final_result_kind,
        final_result_text=final_result_text,
        sort_timestamp=_iso(
            (latest_download_job.completed_at if latest_download_job is not None else None)
            or (latest_download_job.updated_at if latest_download_job is not None else None)
            or job.completed_at
            or job.updated_at
            or job.created_at
        ),
        created_at=_iso(job.created_at),
        updated_at=_iso(
            (latest_download_job.updated_at if latest_download_job is not None else None)
            or job.updated_at
        ),
        completed_at=_iso(
            (latest_download_job.completed_at if latest_download_job is not None else None)
            or job.completed_at
        ),
        search_job=_search_job_summary(job),
        download_job=_download_job_summary(latest_download_job) if latest_download_job is not None else None,
    )


def _single_feed_status(job: IrcSearchJob, latest_download_job: IrcDownloadJob | None) -> str:
    if latest_download_job is not None:
        if latest_download_job.status in {"queued", "sent", "waiting_dcc", "downloading"}:
            return "downloading_book"
        if latest_download_job.status == "downloaded":
            return "completed"
        if latest_download_job.status in {"extracting", "extracted"}:
            return "extracting"
        if latest_download_job.status in {"importing", "refreshing_library"}:
            return "importing"
        if latest_download_job.status == "moved":
            return "completed"
        if latest_download_job.status == "failed":
            return "failed"
    if job.status in {"queued", "sent", "waiting_dcc"}:
        return "searching"
    if job.status == "downloading_results":
        return "downloading_search_results"
    if job.status == "results_ready":
        return "choosing_best_option"
    if job.status == "failed":
        return "failed"
    return job.status


def _is_single_feed_active(job: IrcSearchJob, latest_download_job: IrcDownloadJob | None) -> bool:
    if latest_download_job is not None:
        return latest_download_job.status in {
            "queued",
            "sent",
            "waiting_dcc",
            "downloading",
            "extracting",
            "extracted",
            "importing",
            "refreshing_library",
        }
    return job.status in {"queued", "sent", "waiting_dcc", "downloading_results"}


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
