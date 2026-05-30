import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.app.models import Author, Book, BookFile
from backend.app.routers import books as books_router
from backend.app.schemas.book import BookMetadataApplyOpfRequest, BookMetadataUpdateRequest


@pytest.mark.asyncio
async def test_metadata_info_returns_current_original_manual_and_opf(db_session):
    author = Author(name="Lee Child")
    db_session.add(author)
    await db_session.flush()
    book = Book(
        title="The Enemy",
        author_id=author.id,
        hardcover_id=123,
        isbn="0440241014",
        publisher="Bantam",
        description="Original description",
        release_date="2004-01-01",
        language="en",
        manual_title="Enemy Override",
        is_owned=True,
    )
    db_session.add(book)
    await db_session.flush()
    db_session.add(
        BookFile(
            book_id=book.id,
            file_path="Lee Child/The Enemy/The Enemy.epub",
            file_name="The Enemy.epub",
            file_format="epub",
            opf_title="Also by Lee Child",
            opf_author="KILLING FLOOR",
            opf_isbn="9780440241010",
            opf_publisher="OPF Publisher",
            opf_description="OPF description",
            opf_date="2005",
            opf_language="en",
        )
    )
    await db_session.commit()

    info = await books_router.get_book_metadata_info(book.id, db_session)

    assert info.current.title == "Enemy Override"
    assert info.original.title == "The Enemy"
    assert info.manual.title == "Enemy Override"
    assert info.files[0].opf_title == "Also by Lee Child"
    assert "title" in info.editable_fields


@pytest.mark.asyncio
async def test_apply_opf_metadata_updates_only_selected_manual_fields(db_session):
    author = Author(name="Lee Child")
    db_session.add(author)
    await db_session.flush()
    book = Book(title="The Enemy", author_id=author.id, is_owned=True)
    db_session.add(book)
    await db_session.flush()
    book_file = BookFile(
        book_id=book.id,
        file_path="Lee Child/The Enemy/The Enemy.epub",
        file_name="The Enemy.epub",
        file_format="epub",
        opf_title="The Enemy",
        opf_author="Lee Child",
        opf_isbn="9780440241010",
        opf_publisher="Bantam",
    )
    db_session.add(book_file)
    await db_session.commit()

    await books_router.apply_opf_metadata(
        book.id,
        BookMetadataApplyOpfRequest(book_file_id=book_file.id, fields=["title", "isbn"]),
        db_session,
    )

    refreshed = (await db_session.execute(select(Book).where(Book.id == book.id))).scalar_one()
    assert refreshed.manual_title == "The Enemy"
    assert refreshed.manual_isbn == "9780440241010"
    assert refreshed.manual_publisher is None


@pytest.mark.asyncio
async def test_update_metadata_saves_and_clears_manual_overrides(db_session):
    author = Author(name="Lee Child")
    db_session.add(author)
    await db_session.flush()
    book = Book(
        title="The Enemy",
        author_id=author.id,
        manual_title="Old override",
        manual_publisher="Old publisher",
        is_owned=True,
    )
    db_session.add(book)
    await db_session.commit()

    await books_router.update_book_metadata(
        book.id,
        BookMetadataUpdateRequest(
            title="New override",
            publisher="Ignored because cleared",
            clear_fields=["publisher"],
        ),
        db_session,
    )

    refreshed = (await db_session.execute(select(Book).where(Book.id == book.id))).scalar_one()
    assert refreshed.manual_title == "New override"
    assert refreshed.manual_publisher is None


@pytest.mark.asyncio
async def test_update_metadata_rejects_invalid_isbn(db_session):
    author = Author(name="Lee Child")
    db_session.add(author)
    await db_session.flush()
    book = Book(title="The Enemy", author_id=author.id, is_owned=True)
    db_session.add(book)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await books_router.update_book_metadata(
            book.id,
            BookMetadataUpdateRequest(isbn="not an isbn"),
            db_session,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid ISBN"
