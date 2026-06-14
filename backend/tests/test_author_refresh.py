import pytest
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy import inspect, select
from sqlalchemy.orm import selectinload

from backend.app.models import Author, AuthorDirectory, Book, BookFile, BookSeries, Setting, Series
from backend.app.services.google_books import GBook, GoogleLookupResult
from backend.app.services.hardcover import HCAuthor, HCBook, HCSeriesRef
from backend.app.services import library_sync, scanner
from backend.app.services.library_sync import (
    AuthorRefreshStatus,
    _apply_hardcover_author_match,
    _repair_local_file_links,
    refresh_single_author,
    refresh_single_book,
)
from backend.app.services.openlibrary import OLBook, OpenLibraryLookupResult
from backend.app.routers import authors as authors_router


def test_display_book_series_links_hides_unpositioned_alternates_when_positioned_series_exists():
    canonical = Series(id=1, name="The Famous Five", hardcover_id=11185)
    translated = Series(id=2, name="An Cúigear Cróga", hardcover_id=128723)
    book = Book(id=1, title="Good Old Timmy")
    book.book_series = [
        BookSeries(book_id=1, series_id=canonical.id, series=canonical, position=19.5),
        BookSeries(book_id=1, series_id=translated.id, series=translated, position=None),
    ]

    links = authors_router._display_book_series_links(book)

    assert [link.series.name for link in links] == ["The Famous Five"]


def test_display_book_series_links_keeps_unpositioned_series_when_no_positioned_series_exists():
    translated = Series(id=2, name="An Cúigear Cróga", hardcover_id=128723)
    book = Book(id=1, title="Good Old Timmy")
    book.book_series = [
        BookSeries(book_id=1, series_id=translated.id, series=translated, position=None),
    ]

    links = authors_router._display_book_series_links(book)

    assert [link.series.name for link in links] == ["An Cúigear Cróga"]


def test_author_refresh_status_reports_new_release_count():
    status = AuthorRefreshStatus()
    status.start(42, mode="new_releases")
    status.update(author_name="David Baldacci")

    status.complete(new_books_added=2)

    payload = status.to_dict()
    assert payload["status"] == "completed"
    assert payload["new_books_added"] == 2
    assert payload["message"] == "Found and added 2 new books for David Baldacci."


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


class FakeAuthorLookupHardcoverClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def get_author(self, hardcover_id: int) -> HCAuthor | None:
        return HCAuthor(
            id=hardcover_id,
            name="Correct Hardcover Author",
            slug="correct-hardcover-author",
            bio="Correct author bio",
            image_url="https://example.test/author.jpg",
            books_count=42,
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
async def test_relink_author_hardcover_resets_last_synced_and_starts_refresh(
    db_session,
    monkeypatch,
):
    author = Author(
        name="Wrong Match",
        hardcover_id=100,
        hardcover_slug="wrong-match",
        bio="Old bio",
        image_url="https://example.test/old.jpg",
        last_synced_at=datetime(2024, 1, 1),
    )
    db_session.add_all([
        Setting(key="hardcover_api_key", value="test-hardcover-key"),
        author,
    ])
    await db_session.commit()

    refresh_calls = []
    monkeypatch.setattr(authors_router, "HardcoverClient", FakeAuthorLookupHardcoverClient)
    monkeypatch.setattr(
        authors_router,
        "trigger_author_refresh",
        lambda author_id, mode="full": refresh_calls.append((author_id, mode)) or True,
    )

    response = await authors_router.relink_author_hardcover(
        author.id,
        authors_router.AuthorRelinkRequest(hardcover_id=200),
        db_session,
    )

    await db_session.refresh(author)
    assert response["status"] == "started"
    assert response["hardcover_id"] == 200
    assert refresh_calls == [(author.id, "full")]
    assert author.name == "Correct Hardcover Author"
    assert author.hardcover_id == 200
    assert author.hardcover_slug == "correct-hardcover-author"
    assert author.bio == "Correct author bio"
    assert author.image_url == "https://example.test/author.jpg"
    assert author.last_synced_at is None


@pytest.mark.asyncio
async def test_relink_author_hardcover_rejects_duplicate_hardcover_id(db_session):
    target = Author(name="Wrong Match", hardcover_id=100)
    existing = Author(name="Already Linked", hardcover_id=200)
    db_session.add_all([
        Setting(key="hardcover_api_key", value="test-hardcover-key"),
        target,
        existing,
    ])
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await authors_router.relink_author_hardcover(
            target.id,
            authors_router.AuthorRelinkRequest(hardcover_id=200),
            db_session,
        )

    await db_session.refresh(target)
    assert exc.value.status_code == 409
    assert "Already Linked" in exc.value.detail
    assert target.hardcover_id == 100


@pytest.mark.asyncio
async def test_hardcover_author_match_merges_duplicate_database_links_without_moving_files(db_session):
    keeper = Author(
        name="J. R. R. Tolkien",
        hardcover_id=123,
        hardcover_slug="j-r-r-tolkien",
        last_synced_at=datetime(2024, 1, 1),
    )
    duplicate = Author(name="JRR Tolkien")
    db_session.add_all([keeper, duplicate])
    await db_session.flush()

    keeper_book = Book(title="The Hobbit", author_id=keeper.id, hardcover_id=10)
    duplicate_book = Book(title="The Silmarillion", author_id=duplicate.id, hardcover_id=20)
    db_session.add_all([keeper_book, duplicate_book])
    await db_session.flush()

    db_session.add_all([
        AuthorDirectory(author_id=keeper.id, dir_path="J. R. R. Tolkien", is_primary=True),
        AuthorDirectory(author_id=duplicate.id, dir_path="JRR Tolkien", is_primary=True),
        BookFile(
            book_id=duplicate_book.id,
            file_path="JRR Tolkien/The Silmarillion/The Silmarillion.epub",
            file_name="The Silmarillion.epub",
            file_format="epub",
        ),
    ])
    await db_session.commit()

    absorbed = await _apply_hardcover_author_match(
        db_session,
        duplicate,
        HCAuthor(id=123, name="J. R. R. Tolkien", slug="j-r-r-tolkien"),
        author_has_manual_image=False,
    )
    await db_session.commit()

    assert absorbed is True

    authors = (await db_session.execute(select(Author).order_by(Author.id))).scalars().all()
    assert authors == [keeper]

    refreshed_books = (await db_session.execute(select(Book).order_by(Book.id))).scalars().all()
    assert [book.author_id for book in refreshed_books] == [keeper.id, keeper.id]

    directories = (
        await db_session.execute(select(AuthorDirectory).order_by(AuthorDirectory.dir_path))
    ).scalars().all()
    assert [(directory.dir_path, directory.author_id, directory.is_primary) for directory in directories] == [
        ("J. R. R. Tolkien", keeper.id, True),
        ("JRR Tolkien", keeper.id, False),
    ]

    book_file = (await db_session.execute(select(BookFile))).scalar_one()
    assert book_file.book_id == duplicate_book.id
    assert book_file.file_path == "JRR Tolkien/The Silmarillion/The Silmarillion.epub"

    await db_session.refresh(keeper)
    assert keeper.last_synced_at is None


@pytest.mark.asyncio
async def test_hardcover_author_match_detaches_absorbed_author_from_loaded_scan_list(db_session):
    keeper = Author(
        name="Carlton Mellick, III",
        hardcover_id=1036058,
        hardcover_slug="carlton-mellick-iii",
        last_synced_at=datetime(2024, 1, 1),
    )
    duplicate = Author(name="Carlton III Mellick")
    db_session.add_all([keeper, duplicate])
    await db_session.flush()
    db_session.add_all([
        AuthorDirectory(author_id=keeper.id, dir_path="Carlton Mellick, III", is_primary=True),
        AuthorDirectory(author_id=duplicate.id, dir_path="Mellick, Carlton III", is_primary=True),
    ])
    await db_session.commit()

    loaded_authors = (
        await db_session.execute(select(Author).order_by(Author.id))
    ).scalars().all()
    loaded_duplicate = next(author for author in loaded_authors if author.hardcover_id is None)

    absorbed = await _apply_hardcover_author_match(
        db_session,
        loaded_duplicate,
        HCAuthor(id=1036058, name="Carlton Mellick, III", slug="carlton-mellick-iii"),
        author_has_manual_image=False,
    )
    await db_session.commit()

    assert absorbed is True
    assert inspect(loaded_duplicate).detached
    assert [(author.id, author.name) for author in loaded_authors] == [
        (keeper.id, "Carlton Mellick, III"),
        (duplicate.id, "Carlton III Mellick"),
    ]

    authors = (await db_session.execute(select(Author).order_by(Author.id))).scalars().all()
    assert authors == [keeper]

    directories = (
        await db_session.execute(select(AuthorDirectory).order_by(AuthorDirectory.dir_path))
    ).scalars().all()
    assert [(directory.dir_path, directory.author_id, directory.is_primary) for directory in directories] == [
        ("Carlton Mellick, III", keeper.id, True),
        ("Mellick, Carlton III", keeper.id, False),
    ]


@pytest.mark.asyncio
async def test_refresh_single_author_rebuilds_existing_series_links_without_duplicates(
    db_session,
    monkeypatch,
):
    async def fake_scan_library(*_args, **_kwargs):
        return None

    async def fake_sync_author_hardcover_catalog(*_args, **_kwargs):
        return (0, 0, [])

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
async def test_get_or_create_author_uses_primary_calibre_ampersand_author(db_session):
    resolved_author = await scanner._get_or_create_author(db_session, "Duncan, Lee & Block, Lawrence")
    author_count = (await db_session.execute(select(Author))).scalars().all()

    assert resolved_author.name == "Lee Duncan"
    assert resolved_author.author_key == "lee duncan"
    assert len(author_count) == 1


@pytest.mark.asyncio
async def test_repair_local_file_links_matches_primary_calibre_ampersand_author(db_session):
    author = Author(name="Lee Duncan")
    db_session.add(author)
    await db_session.flush()

    book = Book(
        title="Coauthored Book",
        author_id=author.id,
        hardcover_id=12345,
        manual_visibility="visible",
        is_owned=False,
    )
    db_session.add(book)
    await db_session.flush()

    book_file = BookFile(
        file_path="Duncan, Lee & Block, Lawrence/Coauthored Book/Coauthored Book.epub",
        file_name="Coauthored Book.epub",
        file_format="epub",
        opf_title="Coauthored Book",
        opf_author="Duncan, Lee & Block, Lawrence",
    )
    db_session.add(book_file)
    await db_session.commit()

    matched_count, repaired_count, books_added = await _repair_local_file_links(db_session)
    await db_session.commit()

    await db_session.refresh(book)
    await db_session.refresh(book_file)
    authors = (await db_session.execute(select(Author))).scalars().all()

    assert matched_count == 1
    assert repaired_count == 0
    assert books_added == 0
    assert book.is_owned is True
    assert book_file.book_id == book.id
    assert book_file.opf_author == "Duncan, Lee & Block, Lawrence"
    assert [item.name for item in authors] == ["Lee Duncan"]


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


@pytest.mark.asyncio
async def test_refresh_single_book_scans_linked_file_prefixes_and_clears_stale_ownership(
    db_session,
    monkeypatch,
    tmp_path,
):
    author = Author(name="Robert Jordan")
    db_session.add(author)
    await db_session.flush()
    db_session.add(AuthorDirectory(author_id=author.id, dir_path="Robert Jordan", is_primary=True))

    book = Book(
        title="The Eye of the World",
        author_id=author.id,
        hardcover_id=5188,
        is_owned=True,
    )
    db_session.add(book)
    await db_session.flush()
    db_session.add(
        BookFile(
            book_id=book.id,
            file_path=(
                "Chuck Dixon/Robert Jordan's Wheel of Time_ Eye of the World #3 (413)/"
                "Robert Jordan's Wheel of Time_ Eye of the - Chuck Dixon.epub"
            ),
            file_name="Robert Jordan's Wheel of Time_ Eye of the - Chuck Dixon.epub",
            file_format="epub",
        )
    )
    await db_session.commit()

    monkeypatch.setattr("backend.app.services.library_sync.async_session", StubSessionFactory(db_session))
    monkeypatch.setattr(library_sync, "BOOKS_DIR", tmp_path)

    (tmp_path / "Robert Jordan").mkdir(parents=True, exist_ok=True)
    (tmp_path / "Chuck Dixon").mkdir(parents=True, exist_ok=True)

    await refresh_single_book(book.id)

    db_session.expire_all()
    refreshed = await db_session.execute(
        select(Book)
        .where(Book.id == book.id)
        .options(selectinload(Book.files))
    )
    refreshed_book = refreshed.scalar_one()
    remaining_files = (await db_session.execute(select(BookFile))).scalars().all()

    assert refreshed_book.is_owned is False
    assert refreshed_book.files == []
    assert remaining_files == []


@pytest.mark.asyncio
async def test_get_author_includes_local_files_not_matched_to_shown_books(
    db_session,
    monkeypatch,
    tmp_path,
):
    author = Author(name="N. K. Jemisin")
    db_session.add(author)
    await db_session.flush()
    db_session.add(AuthorDirectory(author_id=author.id, dir_path="N. K. Jemisin", is_primary=True))

    shown_book = Book(
        title="The Fifth Season",
        author_id=author.id,
        hardcover_id=101,
        is_owned=True,
    )
    hidden_book = Book(
        title="The Broken Kingdoms Sampler",
        author_id=author.id,
        hardcover_id=102,
        is_owned=True,
        manual_visibility="hidden",
    )
    db_session.add_all([shown_book, hidden_book])
    await db_session.flush()
    db_session.add_all([
        BookFile(
            book_id=shown_book.id,
            file_path="N. K. Jemisin/The Fifth Season/The Fifth Season.epub",
            file_name="The Fifth Season.epub",
            file_format="epub",
        ),
        BookFile(
            book_id=hidden_book.id,
            file_path="N. K. Jemisin/The Broken Kingdoms Sampler/The Broken Kingdoms Sampler.epub",
            file_name="The Broken Kingdoms Sampler.epub",
            file_format="epub",
        ),
    ])
    await db_session.commit()

    shown_path = tmp_path / "N. K. Jemisin" / "The Fifth Season" / "The Fifth Season.epub"
    shown_path.parent.mkdir(parents=True, exist_ok=True)
    shown_path.write_text("shown", encoding="utf-8")

    hidden_path = tmp_path / "N. K. Jemisin" / "The Broken Kingdoms Sampler" / "The Broken Kingdoms Sampler.epub"
    hidden_path.parent.mkdir(parents=True, exist_ok=True)
    hidden_path.write_text("hidden", encoding="utf-8")

    orphan_path = tmp_path / "N. K. Jemisin" / "How Long 'til Black Future Month?" / "How Long 'til Black Future Month?.epub"
    orphan_path.parent.mkdir(parents=True, exist_ok=True)
    orphan_path.write_text("orphan", encoding="utf-8")

    monkeypatch.setattr(authors_router, "BOOKS_DIR", tmp_path)

    detail = await authors_router.get_author(author.id, db_session)
    unmatched_by_path = {file.file_path: file for file in detail.unmatched_local_files}

    assert "N. K. Jemisin/The Fifth Season/The Fifth Season.epub" not in unmatched_by_path
    assert "N. K. Jemisin/The Broken Kingdoms Sampler/The Broken Kingdoms Sampler.epub" in unmatched_by_path
    assert "N. K. Jemisin/How Long 'til Black Future Month?/How Long 'til Black Future Month?.epub" in unmatched_by_path
    assert unmatched_by_path[
        "N. K. Jemisin/The Broken Kingdoms Sampler/The Broken Kingdoms Sampler.epub"
    ].linked_book_title == "The Broken Kingdoms Sampler"
    assert unmatched_by_path[
        "N. K. Jemisin/How Long 'til Black Future Month?/How Long 'til Black Future Month?.epub"
    ].linked_book_title is None
