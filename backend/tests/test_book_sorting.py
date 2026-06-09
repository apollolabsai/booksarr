import pytest
from sqlalchemy import create_engine
from sqlalchemy import select

from backend.app.database import Base
from backend.app.models import Author, Book
from backend.app.routers.books import list_books
from backend.app.utils.db_migrations import run_schema_migrations
from backend.app.utils.title_sort import effective_title_sort_key, title_sort_key


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ('"Last Lines"', "last lines"),
        ("$100M Leads", "000000000100m leads"),
        ("'48", "000000000048"),
        ("The Hobbit", "hobbit"),
        ("An Accidental Death", "accidental death"),
        ("A Scanner Darkly", "scanner darkly"),
        ("Volume 2", "volume 000000000002"),
        ("Volume 10", "volume 000000000010"),
        ("Éclair", "eclair"),
    ],
)
def test_title_sort_key_normalizes_catalog_order(title, expected):
    assert title_sort_key(title) == expected


@pytest.mark.asyncio
async def test_list_books_title_sort_uses_indexed_normalized_key(db_session):
    author = Author(name="Example Author")
    db_session.add(author)
    await db_session.flush()

    titles = [
        '"Last Lines"',
        '"O" is for Outlaw',
        "$100M Leads",
        "'48",
        "'Til Death",
        "'Til death",
        "'Til Dice Do Us Part",
        "'Tis the Season",
        "'Twas the Night After Christmas",
        "The Hobbit",
        "A Scanner Darkly",
    ]
    db_session.add_all([
        Book(title=title, author_id=author.id, manual_visibility="visible")
        for title in titles
    ])
    await db_session.commit()

    summaries = await list_books(sort="title", owned=None, author_id=None, search="", db=db_session)

    assert [book.title for book in summaries] == [
        "'48",
        "$100M Leads",
        "The Hobbit",
        '"Last Lines"',
        '"O" is for Outlaw',
        "A Scanner Darkly",
        "'Til Death",
        "'Til death",
        "'Til Dice Do Us Part",
        "'Tis the Season",
        "'Twas the Night After Christmas",
    ]


@pytest.mark.asyncio
async def test_book_title_sort_key_tracks_manual_title_overrides(db_session):
    author = Author(name="Example Author")
    db_session.add(author)
    await db_session.flush()

    book = Book(
        title="Z Original",
        author_id=author.id,
        manual_title="The Alpha Override",
        manual_visibility="visible",
    )
    db_session.add(book)
    await db_session.commit()

    refreshed = (await db_session.execute(select(Book).where(Book.id == book.id))).scalar_one()
    assert refreshed.title_sort_key == effective_title_sort_key("Z Original", "The Alpha Override")

    refreshed.manual_title = None
    await db_session.commit()

    refreshed = (await db_session.execute(select(Book).where(Book.id == book.id))).scalar_one()
    assert refreshed.title_sort_key == effective_title_sort_key("Z Original", None)


def test_schema_migration_backfills_missing_book_title_sort_keys(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        conn.exec_driver_sql(
            "INSERT INTO authors (name, author_key, book_count_local, book_count_total, created_at, updated_at) "
            "VALUES ('Example Author', 'example author', 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        conn.exec_driver_sql(
            "INSERT INTO books (title, manual_title, author_id, title_sort_key, is_owned, created_at, updated_at) "
            "VALUES ('Z Original', 'The Alpha Override', 1, NULL, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )

        run_schema_migrations(conn)

        row = conn.exec_driver_sql("SELECT title_sort_key FROM books").fetchone()
        assert row is not None
        assert row[0] == effective_title_sort_key("Z Original", "The Alpha Override")
