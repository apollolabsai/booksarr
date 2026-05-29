import pytest

from backend.app.models import Author, Book
from backend.app.routers.authors import list_authors
from backend.app.utils.author_name import author_sort_key


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Agatha Christie", "christie, agatha"),
        ("Sir Arthur Conan Doyle", "doyle, arthur conan"),
        ("James McKimmey, Jr", "mckimmey, james"),
        ("Patterson, James & Roughan, Howard", "patterson, james"),
        ("A Xero", "xero, a"),
        ("B Smith", "smith, b"),
    ],
)
def test_author_sort_key_uses_surname_order(name, expected):
    assert author_sort_key(name) == expected


@pytest.mark.asyncio
async def test_list_authors_name_sort_uses_surname_key(db_session):
    xero = Author(name="A Xero")
    smith = Author(name="B Smith")
    doyle = Author(name="Sir Arthur Conan Doyle")
    db_session.add_all([xero, smith, doyle])
    await db_session.flush()

    db_session.add_all([
        Book(title="Xero Book", author_id=xero.id, hardcover_id=101, manual_visibility="visible"),
        Book(title="Smith Book", author_id=smith.id, hardcover_id=102, manual_visibility="visible"),
        Book(title="Doyle Book", author_id=doyle.id, hardcover_id=103, manual_visibility="visible"),
    ])
    await db_session.commit()
    db_session.expire_all()

    summaries = await list_authors(sort="name", search="", db=db_session)

    assert [author.name for author in summaries] == [
        "Sir Arthur Conan Doyle",
        "B Smith",
        "A Xero",
    ]


@pytest.mark.asyncio
async def test_list_authors_count_sorts_use_surname_tiebreaker(db_session):
    xero = Author(name="A Xero")
    smith = Author(name="B Smith")
    db_session.add_all([xero, smith])
    await db_session.flush()

    db_session.add_all([
        Book(
            title="Xero Book",
            author_id=xero.id,
            hardcover_id=201,
            manual_visibility="visible",
            is_owned=True,
        ),
        Book(
            title="Smith Book",
            author_id=smith.id,
            hardcover_id=202,
            manual_visibility="visible",
            is_owned=True,
        ),
    ])
    await db_session.commit()
    db_session.expire_all()

    by_total = await list_authors(sort="books", search="", db=db_session)
    by_owned = await list_authors(sort="owned", search="", db=db_session)

    assert [author.name for author in by_total] == ["B Smith", "A Xero"]
    assert [author.name for author in by_owned] == ["B Smith", "A Xero"]
