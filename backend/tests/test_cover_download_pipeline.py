import asyncio

import pytest

from backend.app.models import Author, Book
from backend.app.services import library_sync


@pytest.mark.asyncio
async def test_remote_cover_downloads_are_bounded_and_committed_incrementally(
    db_session,
    monkeypatch,
):
    author = Author(name="Cover Author")
    db_session.add(author)
    await db_session.flush()

    books = [
        Book(
            title=f"Book {index}",
            author_id=author.id,
            cover_image_url=f"https://example.test/{index}.jpg",
        )
        for index in range(5)
    ]
    db_session.add_all(books)
    await db_session.flush()

    active_downloads = 0
    max_active_downloads = 0

    async def fake_download_image_bytes(_url: str):
        nonlocal active_downloads, max_active_downloads
        active_downloads += 1
        max_active_downloads = max(max_active_downloads, active_downloads)
        await asyncio.sleep(0)
        active_downloads -= 1
        return b"cover-bytes"

    monkeypatch.setattr(library_sync, "download_image_bytes", fake_download_image_bytes)
    monkeypatch.setattr(library_sync, "_measure_cover_data", lambda _data: (1200, 0.66))
    monkeypatch.setattr(
        library_sync,
        "cache_cover_data",
        lambda _data, book_id, source: f"cache/books/{source}_{book_id}.jpg",
    )

    original_commit = db_session.commit
    commit_count = 0

    async def counting_commit():
        nonlocal commit_count
        commit_count += 1
        await original_commit()

    monkeypatch.setattr(db_session, "commit", counting_commit)

    cover_heights = {book.id: 0 for book in books}
    cover_sources = {book.id: None for book in books}
    cover_ratios = {book.id: None for book in books}

    cached = await library_sync._download_and_cache_remote_covers(
        db_session,
        books,
        source="hardcover",
        source_label="Hardcover",
        url_getter=lambda book: book.cover_image_url,
        cover_heights=cover_heights,
        cover_sources=cover_sources,
        cover_ratios=cover_ratios,
        concurrency=2,
        batch_size=3,
        progress_interval=2,
    )

    assert cached == 5
    assert max_active_downloads <= 2
    assert commit_count == 3
    assert {book.cover_image_cached_path for book in books} == {
        f"cache/books/hardcover_{book.id}.jpg" for book in books
    }
    assert set(cover_heights.values()) == {1200}
    assert set(cover_sources.values()) == {"hardcover"}
