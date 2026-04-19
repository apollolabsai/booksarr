import pytest
from sqlalchemy import select

from backend.app.models import (
    Author,
    AuthorDirectory,
    Book,
    BookFile,
    BookSeries,
    IrcBulkDownloadBatch,
    IrcBulkDownloadItem,
    IrcDownloadJob,
    IrcSearchJob,
    IrcSearchResult,
    Series,
)
from backend.app.services.author_management import remove_author_and_books


@pytest.mark.asyncio
async def test_remove_author_and_books_deletes_database_records_only(db_session):
    author = Author(name="Nir Eyal")
    other_author = Author(name="Cal Newport")
    db_session.add_all([author, other_author])
    await db_session.flush()

    db_session.add(
        AuthorDirectory(author_id=author.id, dir_path="Nir Eyal", is_primary=True)
    )
    db_session.add(
        AuthorDirectory(author_id=other_author.id, dir_path="Cal Newport", is_primary=True)
    )

    book = Book(
        title="Indistractable",
        author_id=author.id,
        hardcover_id=427787,
        is_owned=True,
    )
    other_book = Book(
        title="Deep Work",
        author_id=other_author.id,
        hardcover_id=123456,
        is_owned=True,
    )
    db_session.add_all([book, other_book])
    await db_session.flush()

    series = Series(name="Focus")
    db_session.add(series)
    await db_session.flush()

    db_session.add(BookSeries(book_id=book.id, series_id=series.id, position=1))
    db_session.add(
        BookFile(
            book_id=book.id,
            file_path="Nir Eyal/Indistractable/Indistractable.epub",
            file_name="Indistractable.epub",
            file_format="epub",
        )
    )
    db_session.add(
        BookFile(
            book_id=other_book.id,
            file_path="Cal Newport/Deep Work/Deep Work.epub",
            file_name="Deep Work.epub",
            file_format="epub",
        )
    )

    batch = IrcBulkDownloadBatch(request_id="batch-1")
    db_session.add(batch)
    await db_session.flush()

    item = IrcBulkDownloadItem(
        batch_id=batch.id,
        book_id=book.id,
        position=1,
    )
    db_session.add(item)
    await db_session.flush()

    search_job = IrcSearchJob(
        book_id=book.id,
        bulk_item_id=item.id,
        query_text="Indistractable",
        normalized_query="indistractable",
    )
    db_session.add(search_job)
    await db_session.flush()

    search_result = IrcSearchResult(
        search_job_id=search_job.id,
        result_index=0,
        raw_line="raw",
        display_name="Indistractable result",
        download_command="/msg bot xdcc send #1",
    )
    db_session.add(search_result)
    await db_session.flush()

    download_job = IrcDownloadJob(
        book_id=book.id,
        search_job_id=search_job.id,
        search_result_id=search_result.id,
        bulk_item_id=item.id,
        status="queued",
    )
    db_session.add(download_job)
    await db_session.flush()

    item.search_job_id = search_job.id
    item.download_job_id = download_job.id
    item.selected_search_result_id = search_result.id
    await db_session.commit()

    removed_book_count = await remove_author_and_books(db_session, author.id)

    assert removed_book_count == 1
    assert await db_session.get(Author, author.id) is None
    assert await db_session.get(Book, book.id) is None
    assert (await db_session.execute(select(AuthorDirectory).where(AuthorDirectory.author_id == author.id))).scalars().all() == []
    assert (await db_session.execute(select(BookFile).where(BookFile.book_id == book.id))).scalars().all() == []
    assert (await db_session.execute(select(BookSeries).where(BookSeries.book_id == book.id))).scalars().all() == []
    assert await db_session.get(IrcBulkDownloadItem, item.id) is None
    assert await db_session.get(IrcSearchJob, search_job.id) is None
    assert await db_session.get(IrcSearchResult, search_result.id) is None
    assert await db_session.get(IrcDownloadJob, download_job.id) is None

    assert await db_session.get(Author, other_author.id) is not None
    assert await db_session.get(Book, other_book.id) is not None
