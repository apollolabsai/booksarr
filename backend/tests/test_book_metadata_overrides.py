import zipfile

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.app.models import Author, Book, BookFile
from backend.app.routers import books as books_router
from backend.app.schemas.book import BookMetadataApplyOpfRequest, BookMetadataUpdateRequest, BookMetadataValues, BookMetadataWriteOpfRequest
from backend.app.utils.opf_parser import parse_epub_opf


def write_minimal_epub(path, *, title: str, author: str):
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" unique-identifier="bookid">
  <metadata>
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:language>en</dc:language>
  </metadata>
  <manifest/>
  <spine/>
</package>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("content.opf", opf)


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


@pytest.mark.asyncio
async def test_write_opf_metadata_repairs_epub_and_refreshes_database(db_session, monkeypatch, tmp_path):
    author = Author(name="Lee Child")
    db_session.add(author)
    await db_session.flush()
    book = Book(title="The Enemy", author_id=author.id, is_owned=True)
    db_session.add(book)
    await db_session.flush()

    relative_path = "Lee Child/The Enemy/Child, Lee - The Enemy.epub"
    epub_path = tmp_path / relative_path
    write_minimal_epub(epub_path, title="Also by Lee Child", author="KILLING FLOOR")
    book_file = BookFile(
        book_id=book.id,
        file_path=relative_path,
        file_name=epub_path.name,
        file_format="epub",
        opf_title="Also by Lee Child",
        opf_author="KILLING FLOOR",
    )
    db_session.add(book_file)
    await db_session.commit()
    monkeypatch.setattr(books_router, "BOOKS_DIR", tmp_path)

    response = await books_router.write_opf_metadata(
        book.id,
        BookMetadataWriteOpfRequest(
            book_file_id=book_file.id,
            fields=["title", "author_name"],
            values=BookMetadataValues(
                title="The Enemy",
                author_name="Lee Child",
                isbn=None,
                publisher=None,
                description=None,
                release_date=None,
                language=None,
                series_name=None,
                series_position=None,
            ),
        ),
        db_session,
    )

    repaired = parse_epub_opf(epub_path)
    refreshed_file = (await db_session.execute(select(BookFile).where(BookFile.id == book_file.id))).scalar_one()

    assert response.status == "ok"
    assert (tmp_path / f"{relative_path}.bak").exists()
    assert repaired is not None
    assert repaired.title == "The Enemy"
    assert repaired.author == "Lee Child"
    assert refreshed_file.opf_title == "The Enemy"
    assert refreshed_file.opf_author == "Lee Child"


@pytest.mark.asyncio
async def test_write_opf_metadata_can_delete_backup_after_success(db_session, monkeypatch, tmp_path):
    author = Author(name="Lee Child")
    db_session.add(author)
    await db_session.flush()
    book = Book(title="The Enemy", author_id=author.id, is_owned=True)
    db_session.add(book)
    await db_session.flush()

    relative_path = "Lee Child/The Enemy/Child, Lee - The Enemy.epub"
    epub_path = tmp_path / relative_path
    write_minimal_epub(epub_path, title="Also by Lee Child", author="KILLING FLOOR")
    book_file = BookFile(
        book_id=book.id,
        file_path=relative_path,
        file_name=epub_path.name,
        file_format="epub",
        opf_title="Also by Lee Child",
        opf_author="KILLING FLOOR",
    )
    db_session.add(book_file)
    await db_session.commit()
    monkeypatch.setattr(books_router, "BOOKS_DIR", tmp_path)

    response = await books_router.write_opf_metadata(
        book.id,
        BookMetadataWriteOpfRequest(
            book_file_id=book_file.id,
            fields=["title"],
            values=BookMetadataValues(
                title="The Enemy",
                author_name=None,
                isbn=None,
                publisher=None,
                description=None,
                release_date=None,
                language=None,
                series_name=None,
                series_position=None,
            ),
            delete_backup=True,
        ),
        db_session,
    )

    assert response.status == "ok"
    assert response.backup_path == ""
    assert not (tmp_path / f"{relative_path}.bak").exists()
