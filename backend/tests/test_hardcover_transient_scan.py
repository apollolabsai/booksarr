import json

import pytest
from sqlalchemy import select

from backend.app.models import Author, Book, Setting
from backend.app.services import library_sync
from backend.app.services.hardcover import HCAuthor, HCBook, HardcoverLookupError
from backend.app.services.openlibrary import OpenLibraryLookupResult
from backend.app.services.scanner import ScanResult


class StubSessionFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class NoopOpenLibraryClient:
    async def search_author(self, _name: str):
        return None

    async def search_book_by_isbn_with_result(self, _isbn: str):
        return OpenLibraryLookupResult(book=None, reason="no_result")

    async def search_book_with_result(self, _title: str, _author: str):
        return OpenLibraryLookupResult(book=None, reason="no_result")

    async def close(self) -> None:
        return None


class NoopWikimediaClient:
    async def search_author_with_result(self, _name: str):
        return type("Lookup", (), {"author": None, "reason": "no_result"})()

    async def close(self) -> None:
        return None


def _scan_result_with_change() -> ScanResult:
    result = ScanResult()
    result.new_files = ["Good Author/Good Book/Good Book.epub"]
    result.total_files = 1
    return result


async def _fake_scan_library(*_args, **_kwargs) -> ScanResult:
    return _scan_result_with_change()


async def _fake_repair_local_file_links(*_args, **_kwargs):
    return 0, 0, 0


def _reset_scan_status() -> None:
    library_sync.scan_status.status = "idle"
    library_sync.scan_status.progress = 0.0
    library_sync.scan_status.message = ""


@pytest.mark.asyncio
async def test_full_sync_skips_transient_hardcover_author_lookup_and_continues(
    db_session,
    monkeypatch,
):
    class TransientAuthorLookupHardcoverClient:
        def __init__(self, _api_key: str):
            return None

        async def search_author(self, name: str):
            if name == "Broken Author":
                raise HardcoverLookupError(
                    "transient_http_error",
                    "HTTP 502",
                    status_code=502,
                )
            return HCAuthor(id=200, name=name, slug="good-author")

        async def get_author_books(self, author_id: int):
            assert author_id == 200
            return [HCBook(id=300, title="Good Book", is_canonical=True)]

        async def close(self) -> None:
            return None

    broken_author = Author(name="Broken Author")
    good_author = Author(name="Good Author")
    db_session.add_all([
        Setting(key="hardcover_api_key", value="test-key"),
        broken_author,
        good_author,
    ])
    await db_session.commit()

    _reset_scan_status()
    monkeypatch.setattr(library_sync, "async_session", StubSessionFactory(db_session))
    monkeypatch.setattr(library_sync, "scan_library", _fake_scan_library)
    monkeypatch.setattr(library_sync, "_repair_local_file_links", _fake_repair_local_file_links)
    monkeypatch.setattr(library_sync, "HardcoverClient", TransientAuthorLookupHardcoverClient)
    monkeypatch.setattr(library_sync, "OpenLibraryClient", NoopOpenLibraryClient)
    monkeypatch.setattr(library_sync, "WikimediaClient", NoopWikimediaClient)

    await library_sync.run_full_sync(force=False)

    await db_session.refresh(broken_author)
    await db_session.refresh(good_author)
    books = (await db_session.execute(select(Book))).scalars().all()
    summary_setting = await db_session.get(Setting, "last_scan_summary")
    summary = json.loads(summary_setting.value)

    assert library_sync.scan_status.status == "idle"
    assert "temporary lookup failures" in library_sync.scan_status.message
    assert broken_author.hardcover_id is None
    assert good_author.hardcover_id == 200
    assert good_author.last_synced_at is not None
    assert [book.title for book in books] == ["Good Book"]
    assert summary["status"] == "completed"
    assert summary["hardcover"]["failure_reasons"]["transient_http_error"] >= 1
    assert summary["hardcover"]["deferred"] >= 1


@pytest.mark.asyncio
async def test_full_sync_skips_transient_hardcover_book_sync_and_continues(
    db_session,
    monkeypatch,
):
    class TransientBookSyncHardcoverClient:
        def __init__(self, _api_key: str):
            return None

        async def get_author_books(self, author_id: int):
            if author_id == 100:
                raise HardcoverLookupError(
                    "transient_http_error",
                    "HTTP 502",
                    status_code=502,
                )
            return [HCBook(id=400, title="Recovered Book", is_canonical=True)]

        async def close(self) -> None:
            return None

    broken_author = Author(
        name="Broken Author",
        hardcover_id=100,
        image_cached_path="authors/broken.jpg",
    )
    good_author = Author(
        name="Good Author",
        hardcover_id=200,
        image_cached_path="authors/good.jpg",
    )
    db_session.add_all([
        Setting(key="hardcover_api_key", value="test-key"),
        broken_author,
        good_author,
    ])
    await db_session.commit()

    _reset_scan_status()
    monkeypatch.setattr(library_sync, "async_session", StubSessionFactory(db_session))
    monkeypatch.setattr(library_sync, "scan_library", _fake_scan_library)
    monkeypatch.setattr(library_sync, "_repair_local_file_links", _fake_repair_local_file_links)
    monkeypatch.setattr(library_sync, "HardcoverClient", TransientBookSyncHardcoverClient)
    monkeypatch.setattr(library_sync, "OpenLibraryClient", NoopOpenLibraryClient)
    monkeypatch.setattr(library_sync, "WikimediaClient", NoopWikimediaClient)

    await library_sync.run_full_sync(force=True)

    await db_session.refresh(broken_author)
    await db_session.refresh(good_author)
    books = (await db_session.execute(select(Book))).scalars().all()
    summary_setting = await db_session.get(Setting, "last_scan_summary")
    summary = json.loads(summary_setting.value)

    assert library_sync.scan_status.status == "idle"
    assert "temporary lookup failures" in library_sync.scan_status.message
    assert broken_author.last_synced_at is None
    assert good_author.last_synced_at is not None
    assert [book.title for book in books] == ["Recovered Book"]
    assert summary["status"] == "completed"
    assert summary["hardcover"]["failure_reasons"]["transient_http_error"] >= 1
    assert summary["hardcover"]["deferred"] >= 1
