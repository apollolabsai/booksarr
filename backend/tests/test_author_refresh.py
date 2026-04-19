import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.models import Author, AuthorDirectory, Book, BookSeries, Setting, Series
from backend.app.services.google_books import GBook, GoogleLookupResult
from backend.app.services.hardcover import HCBook, HCSeriesRef
from backend.app.services import library_sync, scanner
from backend.app.services.library_sync import refresh_single_author, refresh_single_book
from backend.app.services.openlibrary import OLBook, OpenLibraryLookupResult


class StubSessionFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeHardcoverClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def get_book(self, hardcover_id: int) -> HCBook | None:
        assert hardcover_id == 378059
        return HCBook(
            id=378059,
            title="Freakonomics: A Rogue Economist Explores the Hidden Side of Everything",
            slug="freakonomics",
            release_date="2005-04-12",
            language="en",
            series_refs=[
                HCSeriesRef(id=5489, name="Freakonomics", position=1),
                HCSeriesRef(id=5489, name="Freakonomics", position=1),
            ],
        )

    async def close(self) -> None:
        return None


class FakeGoogleBooksClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search_by_isbn_result(self, isbn: str) -> GoogleLookupResult:
        return GoogleLookupResult(book=None, reason="no_result")

    async def search_by_title_author_result(self, title: str, author: str) -> GoogleLookupResult:
        return GoogleLookupResult(
            book=GBook(
                title=title,
                google_id="google-refresh-1",
                published_date="2005-04-12",
                isbn_10="0306406152",
                isbn_13="9780306406157",
                language="en",
            ),
            reason="matched",
        )

    async def close(self) -> None:
        return None


class FakeOpenLibraryClient:
    async def search_book_by_isbn_with_result(self, isbn: str) -> OpenLibraryLookupResult:
        return OpenLibraryLookupResult(
            book=OLBook(
                title="Freakonomics",
                first_publish_year=2005,
                cover_edition_key="OL123M",
                isbn_list=["0306406152", "9780306406157"],
            ),
            reason="matched",
        )

    async def search_book_with_result(self, title: str, author: str) -> OpenLibraryLookupResult:
        return OpenLibraryLookupResult(book=None, reason="no_result")

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_refresh_single_author_rebuilds_existing_series_links_without_duplicates(
    db_session,
    monkeypatch,
):
    async def fake_scan_library(*_args, **_kwargs):
        return None

    async def fake_sync_author_hardcover_catalog(*_args, **_kwargs):
        return (0, 0)

    async def fake_repair_local_file_links(*_args, **_kwargs):
        return (0, 0, 0)

    author = Author(name="Steven D. Levitt", hardcover_id=177973)
    db_session.add(author)
    await db_session.flush()

    series = Series(hardcover_id=5489, name="Freakonomics")
    db_session.add(series)
    await db_session.flush()

    book = Book(
        title="Freakonomics",
        author_id=author.id,
        hardcover_id=378059,
        hardcover_slug="freakonomics",
        is_owned=False,
    )
    db_session.add(book)
    await db_session.flush()

    db_session.add(BookSeries(book_id=book.id, series_id=series.id, position=1.0))
    db_session.add(Setting(key="hardcover_api_key", value="test-hardcover-key"))
    db_session.add(Setting(key="google_books_api_key", value="test-google-key"))
    await db_session.commit()

    monkeypatch.setattr("backend.app.services.library_sync.async_session", StubSessionFactory(db_session))
    monkeypatch.setattr("backend.app.services.library_sync.scan_library", fake_scan_library)
    monkeypatch.setattr(
        "backend.app.services.library_sync._sync_author_hardcover_catalog",
        fake_sync_author_hardcover_catalog,
    )
    monkeypatch.setattr(
        "backend.app.services.library_sync._repair_local_file_links",
        fake_repair_local_file_links,
    )
    monkeypatch.setattr("backend.app.services.library_sync.HardcoverClient", FakeHardcoverClient)
    monkeypatch.setattr("backend.app.services.library_sync.GoogleBooksClient", FakeGoogleBooksClient)
    monkeypatch.setattr("backend.app.services.library_sync.OpenLibraryClient", FakeOpenLibraryClient)

    await refresh_single_author(author.id)

    refreshed = await db_session.execute(
        select(Book)
        .where(Book.id == book.id)
        .options(selectinload(Book.book_series))
    )
    refreshed_book = refreshed.scalar_one()

    assert refreshed_book.google_id == "google-refresh-1"
    assert refreshed_book.google_isbn_13 == "9780306406157"
    assert refreshed_book.publish_date_checked_at is not None
    assert len(refreshed_book.book_series) == 1
    assert refreshed_book.book_series[0].series_id == series.id


@pytest.mark.asyncio
async def test_get_or_create_author_reuses_existing_normalized_author(db_session):
    existing_author = Author(name="Nir   Eyal")
    db_session.add(existing_author)
    await db_session.commit()

    resolved_author = await scanner._get_or_create_author(db_session, "Eyal, Nir")
    author_count = (await db_session.execute(select(Author))).scalars().all()

    assert resolved_author.id == existing_author.id
    assert resolved_author.name == "Nir Eyal"
    assert len(author_count) == 1


@pytest.mark.asyncio
async def test_refresh_single_book_scans_matching_author_directory_and_links_new_file(
    db_session,
    monkeypatch,
    tmp_path,
):
    author = Author(name="Steven D. Levitt")
    db_session.add(author)
    await db_session.flush()

    book = Book(
        title="Freakonomics",
        author_id=author.id,
        hardcover_id=378059,
        hardcover_slug="freakonomics",
        is_owned=False,
    )
    db_session.add(book)
    await db_session.commit()

    book_path = tmp_path / "Levitt, Steven D." / "Freakonomics" / "Freakonomics.epub"
    book_path.parent.mkdir(parents=True, exist_ok=True)
    book_path.write_text("placeholder", encoding="utf-8")

    class StubMetadata:
        title = "Freakonomics"
        author = "Steven D. Levitt"
        isbn = "9780306406157"
        series = None
        series_index = None
        publisher = "William Morrow"
        description = "A test description"

    monkeypatch.setattr("backend.app.services.library_sync.async_session", StubSessionFactory(db_session))
    monkeypatch.setattr(library_sync, "BOOKS_DIR", tmp_path)
    monkeypatch.setattr(library_sync, "extract_best_metadata", lambda *_args, **_kwargs: StubMetadata())
    monkeypatch.setattr(scanner, "extract_best_metadata", lambda *_args, **_kwargs: StubMetadata())

    await refresh_single_book(book.id)

    refreshed = await db_session.execute(
        select(Book)
        .where(Book.id == book.id)
        .options(
            selectinload(Book.files),
            selectinload(Book.author).selectinload(Author.author_directories),
        )
    )
    refreshed_book = refreshed.scalar_one()
    author_directories = (
        await db_session.execute(
            select(AuthorDirectory.dir_path).where(AuthorDirectory.author_id == author.id)
        )
    ).scalars().all()

    assert refreshed_book.is_owned is True
    assert refreshed_book.isbn == "9780306406157"
    assert refreshed_book.publisher == "William Morrow"
    assert len(refreshed_book.files) == 1
    assert refreshed_book.files[0].file_path == "Levitt, Steven D./Freakonomics/Freakonomics.epub"
    assert author_directories == ["Levitt, Steven D."]
