import pytest
from sqlalchemy import select

from backend.app.models import Author, Book, BookFile
from backend.app.routers import books as books_router
from backend.app.schemas.book import BookFixMatchRequest


@pytest.mark.asyncio
async def test_match_candidates_include_hidden_books(db_session):
    author = Author(name="Sarah Alderson")
    db_session.add(author)
    await db_session.flush()

    source = Book(title="Hunting Lila", author_id=author.id, hardcover_id=100, is_owned=True)
    hidden_target = Book(
        title="Losing Lila",
        author_id=author.id,
        hardcover_id=101,
        hardcover_isbn_13="9781444904729",
        manual_visibility="hidden",
        is_owned=False,
    )
    db_session.add_all([source, hidden_target])
    await db_session.commit()

    response = await books_router.list_book_match_candidates(
        search="Losing",
        author_id=None,
        exclude_book_id=source.id,
        limit=30,
        db=db_session,
    )

    assert len(response.candidates) == 1
    assert response.candidates[0].id == hidden_target.id
    assert response.candidates[0].is_hidden is True
    assert "manual_hidden" in [category.key for category in response.candidates[0].hidden_categories]


@pytest.mark.asyncio
async def test_fix_book_match_moves_file_and_unhides_target(db_session):
    author = Author(name="Matt Dinniman")
    db_session.add(author)
    await db_session.flush()

    source = Book(title="Dungeon Crawler Carl", author_id=author.id, hardcover_id=390, is_owned=True)
    target = Book(
        title="Carl's Doomsday Scenario",
        author_id=author.id,
        hardcover_id=391,
        manual_visibility="hidden",
        is_owned=False,
    )
    db_session.add_all([source, target])
    await db_session.flush()

    book_file = BookFile(
        book_id=source.id,
        file_path="Matt Dinniman/Carls Doomsday Scenario (391)/Carls Doomsday Scenario - Matt Dinniman.epub",
        file_name="Carls Doomsday Scenario - Matt Dinniman.epub",
        file_format="epub",
    )
    db_session.add(book_file)
    await db_session.commit()

    response = await books_router.fix_book_match(
        source.id,
        BookFixMatchRequest(target_book_id=target.id, book_file_ids=[book_file.id]),
        db_session,
    )

    refreshed_file = (await db_session.execute(select(BookFile).where(BookFile.id == book_file.id))).scalar_one()
    refreshed_source = await db_session.get(Book, source.id)
    refreshed_target = await db_session.get(Book, target.id)

    assert response.status == "ok"
    assert response.source_book_id == source.id
    assert response.target_book_id == target.id
    assert response.moved_file_ids == [book_file.id]
    assert refreshed_file.book_id == target.id
    assert refreshed_source.is_owned is False
    assert refreshed_target.is_owned is True
    assert refreshed_target.manual_visibility == "visible"
