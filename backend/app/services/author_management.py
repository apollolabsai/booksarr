from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import (
    Author,
    AuthorDirectory,
    Book,
    BookFile,
    BookSeries,
    IrcBulkDownloadItem,
    IrcDownloadJob,
    IrcSearchJob,
    IrcSearchResult,
)


async def remove_author_and_books(db: AsyncSession, author_id: int) -> int:
    author_result = await db.execute(select(Author.id).where(Author.id == author_id))
    author_exists = author_result.scalar_one_or_none()
    if author_exists is None:
        raise ValueError("Author not found")

    book_ids = list((
        await db.execute(select(Book.id).where(Book.author_id == author_id))
    ).scalars().all())

    bulk_item_rows = (
        await db.execute(
            select(
                IrcBulkDownloadItem.id,
                IrcBulkDownloadItem.search_job_id,
                IrcBulkDownloadItem.download_job_id,
                IrcBulkDownloadItem.selected_search_result_id,
            ).where(IrcBulkDownloadItem.book_id.in_(book_ids))
        )
    ).all() if book_ids else []
    bulk_item_ids = {row.id for row in bulk_item_rows}
    search_job_ids = {
        row.search_job_id for row in bulk_item_rows
        if row.search_job_id is not None
    }
    download_job_ids = {
        row.download_job_id for row in bulk_item_rows
        if row.download_job_id is not None
    }
    search_result_ids = {
        row.selected_search_result_id for row in bulk_item_rows
        if row.selected_search_result_id is not None
    }

    if book_ids:
        search_job_ids.update((
            await db.execute(select(IrcSearchJob.id).where(IrcSearchJob.book_id.in_(book_ids)))
        ).scalars().all())
        download_job_ids.update((
            await db.execute(select(IrcDownloadJob.id).where(IrcDownloadJob.book_id.in_(book_ids)))
        ).scalars().all())

    if search_job_ids:
        search_result_ids.update((
            await db.execute(select(IrcSearchResult.id).where(IrcSearchResult.search_job_id.in_(search_job_ids)))
        ).scalars().all())

    if bulk_item_ids:
        await db.execute(
            update(IrcSearchJob)
            .where(IrcSearchJob.bulk_item_id.in_(bulk_item_ids))
            .values(bulk_item_id=None)
        )
        await db.execute(
            update(IrcDownloadJob)
            .where(IrcDownloadJob.bulk_item_id.in_(bulk_item_ids))
            .values(bulk_item_id=None)
        )
        await db.execute(delete(IrcBulkDownloadItem).where(IrcBulkDownloadItem.id.in_(bulk_item_ids)))

    if download_job_ids:
        await db.execute(delete(IrcDownloadJob).where(IrcDownloadJob.id.in_(download_job_ids)))

    if search_result_ids:
        await db.execute(delete(IrcSearchResult).where(IrcSearchResult.id.in_(search_result_ids)))

    if search_job_ids:
        await db.execute(delete(IrcSearchJob).where(IrcSearchJob.id.in_(search_job_ids)))

    if book_ids:
        await db.execute(delete(BookFile).where(BookFile.book_id.in_(book_ids)))
        await db.execute(delete(BookSeries).where(BookSeries.book_id.in_(book_ids)))
        await db.execute(delete(Book).where(Book.id.in_(book_ids)))

    await db.execute(delete(AuthorDirectory).where(AuthorDirectory.author_id == author_id))
    await db.execute(delete(Author).where(Author.id == author_id))
    await db.commit()

    return len(book_ids)
