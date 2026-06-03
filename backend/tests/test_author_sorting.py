import pytest

from backend.app.models import Author, Book
from backend.app.routers.authors import list_authors
from backend.app.utils.author_name import author_sort_key, clean_author_name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Lloyd Biggle, Jr.", "Lloyd Biggle, Jr."),
        ("James McKimmey, Jr", "James McKimmey, Jr"),
        ("Deepak Chopra, M.D.", "Deepak Chopra, M.D."),
        ("Jared Diamond, Ph.D.", "Jared Diamond, Ph.D."),
        ("Murphy, C. E.", "C. E. Murphy"),
        ("Christie, Agatha", "Agatha Christie"),
        ("C. E_ Murphy", "C. E. Murphy"),
        ("Murphy, C. E_", "C. E. Murphy"),
        ("H. G_ Wells", "H. G. Wells"),
        ("Wells, H. G_", "H. G. Wells"),
        ("Agatha Christie", "Agatha Christie"),
    ],
)
def test_clean_author_name_preserves_suffixes_but_swaps_last_first(name, expected):
    assert clean_author_name(name) == expected


def test_author_model_name_validator_preserves_suffixes():
    author = Author(name="placeholder")

    author.name = "Lloyd Biggle, Jr."

    assert author.name == "Lloyd Biggle, Jr."
    assert author.author_key == "lloyd biggle, jr."


def test_author_model_name_validator_restores_calibre_windows_initial_periods():
    author = Author(name="placeholder")

    author.name = "Murphy, C. E_"

    assert author.name == "C. E. Murphy"
    assert author.author_key == "c. e. murphy"


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


@pytest.mark.asyncio
async def test_list_authors_counts_visible_books_and_omits_hidden_only_authors(db_session):
    visible_author = Author(name="Visible Author")
    hidden_author = Author(name="Hidden Author")
    db_session.add_all([visible_author, hidden_author])
    await db_session.flush()

    db_session.add_all([
        Book(
            title="Owned Visible",
            author_id=visible_author.id,
            hardcover_id=301,
            manual_visibility="visible",
            is_owned=True,
        ),
        Book(
            title="Catalog Visible",
            author_id=visible_author.id,
            hardcover_id=302,
            manual_visibility="visible",
            is_owned=False,
        ),
        Book(
            title="Hidden",
            author_id=visible_author.id,
            hardcover_id=303,
            manual_visibility="hidden",
            is_owned=True,
        ),
        Book(
            title="Only Hidden",
            author_id=hidden_author.id,
            hardcover_id=304,
            manual_visibility="hidden",
            is_owned=True,
        ),
    ])
    await db_session.commit()
    db_session.expire_all()

    summaries = await list_authors(sort="name", search="", db=db_session)

    assert [author.name for author in summaries] == ["Visible Author"]
    assert summaries[0].book_count_local == 1
    assert summaries[0].book_count_total == 2
