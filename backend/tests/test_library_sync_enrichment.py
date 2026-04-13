import pytest

from backend.app.models import Author, Book, Setting
from backend.app.services.google_books import GBook, GoogleLookupResult
from backend.app.services.library_sync import enrich_imported_books_metadata
from backend.app.services.openlibrary import OLBook, OpenLibraryLookupResult


class FakeGoogleBooksClient:
    instances: list["FakeGoogleBooksClient"] = []

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.calls: list[tuple[str, str]] = []
        self.closed = False
        type(self).instances.append(self)

    async def search_by_isbn_result(self, isbn: str) -> GoogleLookupResult:
        self.calls.append(("isbn", isbn))
        return GoogleLookupResult(book=None, reason="no_result")

    async def search_by_title_author_result(self, title: str, author: str) -> GoogleLookupResult:
        self.calls.append(("title_author", f"{title}|{author}"))
        return GoogleLookupResult(
            book=GBook(
                title=title,
                google_id="google-book-1",
                published_date="2005-04-12",
                cover_url="https://example.com/google-cover.jpg",
                isbn_10="0306406152",
                isbn_13="9780306406157",
                language="pl",
            ),
            reason="matched",
        )

    async def close(self) -> None:
        self.closed = True


class FakeOpenLibraryClient:
    instances: list["FakeOpenLibraryClient"] = []

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.closed = False
        type(self).instances.append(self)

    async def search_book_by_isbn_with_result(self, isbn: str) -> OpenLibraryLookupResult:
        self.calls.append(("isbn", isbn))
        return OpenLibraryLookupResult(
            book=OLBook(
                title="Freakonomics",
                first_publish_year=2005,
                cover_id=321,
                cover_edition_key="OL123M",
                isbn_list=["0306406152", "9780306406157"],
            ),
            reason="matched",
        )

    async def search_book_with_result(self, title: str, author: str) -> OpenLibraryLookupResult:
        self.calls.append(("title_author", f"{title}|{author}"))
        return OpenLibraryLookupResult(
            book=OLBook(
                title=title,
                first_publish_year=2005,
                cover_id=321,
                cover_edition_key="OL123M",
                isbn_list=["0306406152", "9780306406157"],
            ),
            reason="matched",
        )

    async def close(self) -> None:
        self.closed = True


def _reset_fake_clients() -> None:
    FakeGoogleBooksClient.instances.clear()
    FakeOpenLibraryClient.instances.clear()


@pytest.mark.asyncio
async def test_enrich_imported_books_metadata_populates_google_and_openlibrary_fields(
    db_session,
    monkeypatch,
):
    _reset_fake_clients()
    monkeypatch.setattr(
        "backend.app.services.library_sync.GoogleBooksClient",
        FakeGoogleBooksClient,
    )
    monkeypatch.setattr(
        "backend.app.services.library_sync.OpenLibraryClient",
        FakeOpenLibraryClient,
    )

    author = Author(name="Steven D. Levitt", hardcover_id=1)
    db_session.add(author)
    await db_session.flush()

    db_session.add(Setting(key="google_books_api_key", value="test-key"))
    book = Book(
        title="Freakonomics",
        author_id=author.id,
        hardcover_id=123,
        hardcover_slug="freakonomics",
        release_date="2005-04-12",
        is_owned=False,
    )
    db_session.add(book)
    await db_session.commit()

    await enrich_imported_books_metadata(db_session, [book.id])
    await db_session.refresh(book)

    assert book.google_id == "google-book-1"
    assert book.google_published_date == "2005-04-12"
    assert book.google_cover_url == "https://example.com/google-cover.jpg"
    assert book.google_isbn_10 == "0306406152"
    assert book.google_isbn_13 == "9780306406157"
    assert book.language == "pl"
    assert book.ol_edition_key == "OL123M"
    assert book.ol_first_publish_year == 2005
    assert book.ol_cover_url == "https://covers.openlibrary.org/b/id/321-L.jpg"
    assert book.publish_date_checked_at is not None

    assert len(FakeGoogleBooksClient.instances) == 1
    assert FakeGoogleBooksClient.instances[0].api_key == "test-key"
    assert FakeGoogleBooksClient.instances[0].calls == [
        ("title_author", "Freakonomics|Steven D. Levitt"),
    ]
    assert FakeGoogleBooksClient.instances[0].closed is True

    assert len(FakeOpenLibraryClient.instances) == 1
    assert FakeOpenLibraryClient.instances[0].calls == [
        ("isbn", "9780306406157"),
    ]
    assert FakeOpenLibraryClient.instances[0].closed is True


@pytest.mark.asyncio
async def test_enrich_imported_books_metadata_skips_books_hidden_by_non_english_rule(
    db_session,
    monkeypatch,
):
    _reset_fake_clients()
    monkeypatch.setattr(
        "backend.app.services.library_sync.GoogleBooksClient",
        FakeGoogleBooksClient,
    )
    monkeypatch.setattr(
        "backend.app.services.library_sync.OpenLibraryClient",
        FakeOpenLibraryClient,
    )

    author = Author(name="Autor", hardcover_id=2)
    db_session.add(author)
    await db_session.flush()

    db_session.add(Setting(key="google_books_api_key", value="test-key"))
    book = Book(
        title="Livre Cache",
        author_id=author.id,
        hardcover_id=456,
        hardcover_slug="livre-cache",
        language="fr",
        is_owned=False,
    )
    db_session.add(book)
    await db_session.commit()

    await enrich_imported_books_metadata(db_session, [book.id])
    await db_session.refresh(book)

    assert book.google_id is None
    assert book.ol_edition_key is None
    assert book.publish_date_checked_at is None
    assert FakeGoogleBooksClient.instances == []
    assert FakeOpenLibraryClient.instances == []


@pytest.mark.asyncio
async def test_enrich_imported_books_metadata_does_not_override_existing_language(
    db_session,
    monkeypatch,
):
    _reset_fake_clients()
    monkeypatch.setattr(
        "backend.app.services.library_sync.GoogleBooksClient",
        FakeGoogleBooksClient,
    )
    monkeypatch.setattr(
        "backend.app.services.library_sync.OpenLibraryClient",
        FakeOpenLibraryClient,
    )

    author = Author(name="Steven D. Levitt", hardcover_id=3)
    db_session.add(author)
    await db_session.flush()

    db_session.add(Setting(key="google_books_api_key", value="test-key"))
    book = Book(
        title="Freakonomics",
        author_id=author.id,
        hardcover_id=789,
        hardcover_slug="freakonomics",
        language="translated",
        is_owned=False,
    )
    db_session.add(book)
    await db_session.commit()

    await enrich_imported_books_metadata(db_session, [book.id])
    await db_session.refresh(book)

    assert book.language == "translated"
