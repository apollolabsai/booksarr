import json

import pytest

from backend.app.models import Author, Book, Setting
from backend.app.services.genre_backfill import (
    GENRE_BACKFILL_COMPLETE,
    GENRE_BACKFILL_SETTING_KEY,
    backfill_missing_genres,
)
from backend.app.services.hardcover import HCBook, HardcoverLookupError


class FakeHardcoverClient:
    instances: list["FakeHardcoverClient"] = []

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.author_calls: list[int] = []
        self.book_calls: list[int] = []
        self.closed = False
        type(self).instances.append(self)

    async def get_author_books(self, author_id: int) -> list[HCBook]:
        self.author_calls.append(author_id)
        return [
            HCBook(id=101, title="One", genres=["Fantasy", "Adventure"]),
            HCBook(id=102, title="Two", genres=[]),
        ]

    async def get_book(self, book_id: int) -> HCBook | None:
        self.book_calls.append(book_id)
        return None

    async def close(self) -> None:
        self.closed = True


class FailingHardcoverClient(FakeHardcoverClient):
    async def get_author_books(self, author_id: int) -> list[HCBook]:
        self.author_calls.append(author_id)
        raise HardcoverLookupError(
            "transient_http_error",
            "HTTP 503",
            status_code=503,
        )


@pytest.mark.asyncio
async def test_genre_backfill_preserves_tags_and_marks_empty_genres_complete(db_session):
    FakeHardcoverClient.instances.clear()
    author = Author(name="Example Author", hardcover_id=500)
    db_session.add_all([
        Setting(key="hardcover_api_key", value="test-key"),
        author,
    ])
    await db_session.flush()
    first = Book(
        title="One",
        author_id=author.id,
        hardcover_id=101,
        tags=json.dumps(["Fantasy", "Adventurous"]),
    )
    second = Book(
        title="Two",
        author_id=author.id,
        hardcover_id=102,
        tags=json.dumps(["Tense"]),
    )
    already_done = Book(
        title="Done",
        author_id=author.id,
        hardcover_id=103,
        tags=json.dumps(["Mystery", "Dark"]),
        genres=json.dumps(["Mystery"]),
    )
    db_session.add_all([first, second, already_done])
    await db_session.commit()

    updated = await backfill_missing_genres(
        db_session,
        client_factory=FakeHardcoverClient,
    )
    await db_session.refresh(first)
    await db_session.refresh(second)
    await db_session.refresh(already_done)

    marker = await db_session.get(Setting, GENRE_BACKFILL_SETTING_KEY)
    client = FakeHardcoverClient.instances[0]
    assert updated == 2
    assert json.loads(first.tags) == ["Fantasy", "Adventurous"]
    assert json.loads(first.genres) == ["Fantasy", "Adventure"]
    assert json.loads(second.tags) == ["Tense"]
    assert json.loads(second.genres) == []
    assert json.loads(already_done.genres) == ["Mystery"]
    assert client.author_calls == [500]
    assert client.book_calls == []
    assert client.closed is True
    assert marker is not None
    assert marker.value == GENRE_BACKFILL_COMPLETE

    second_updated = await backfill_missing_genres(
        db_session,
        client_factory=FakeHardcoverClient,
    )
    assert second_updated == 0
    assert len(FakeHardcoverClient.instances) == 1


@pytest.mark.asyncio
async def test_genre_backfill_retries_after_transient_failure(db_session):
    FailingHardcoverClient.instances.clear()
    author = Author(name="Example Author", hardcover_id=500)
    db_session.add_all([
        Setting(key="hardcover_api_key", value="test-key"),
        author,
    ])
    await db_session.flush()
    book = Book(
        title="One",
        author_id=author.id,
        hardcover_id=101,
        tags=json.dumps(["Fantasy", "Adventurous"]),
    )
    db_session.add(book)
    await db_session.commit()

    updated = await backfill_missing_genres(
        db_session,
        client_factory=FailingHardcoverClient,
    )
    await db_session.refresh(book)

    assert updated == 0
    assert book.genres is None
    assert await db_session.get(Setting, GENRE_BACKFILL_SETTING_KEY) is None
