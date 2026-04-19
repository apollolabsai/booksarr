import asyncio

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.database import get_db
from backend.app.models import Author, Book, BookFile
from backend.app.routers.authors import _collect_current_author_local_files
from backend.app.schemas.author import UnmatchedLocalFile
from backend.app.services.library_sync import run_full_sync, scan_status
from backend.app.utils.book_visibility import get_book_visibility_settings, is_book_visible

router = APIRouter(prefix="/api/library", tags=["library"])


@router.post("/scan")
async def trigger_scan(force: bool = Query(False)):
    if scan_status.status == "scanning":
        return {"status": "already_scanning", "message": "A scan is already in progress"}

    asyncio.create_task(run_full_sync(force=force))
    return {"status": "started", "message": "Library scan started"}


@router.get("/status")
async def get_scan_status():
    return scan_status.to_dict()


@router.get("/unmatched-files", response_model=list[UnmatchedLocalFile])
async def get_all_unmatched_files(db: AsyncSession = Depends(get_db)):
    authors_result = await db.execute(
        select(Author).options(selectinload(Author.author_directories))
    )
    authors = authors_result.scalars().all()

    all_books_result = await db.execute(
        select(Book).options(selectinload(Book.files))
    )
    all_books = all_books_result.scalars().all()

    visibility_settings = await get_book_visibility_settings(db)
    visible_file_paths = {
        bf.file_path
        for book in all_books
        if is_book_visible(book, visibility_settings)
        for bf in book.files
    }
    file_to_book = {
        bf.file_path: book
        for book in all_books
        for bf in book.files
    }

    results: list[UnmatchedLocalFile] = []
    for author in sorted(authors, key=lambda a: a.name.lower()):
        for file_path, file_name, file_size, file_format in _collect_current_author_local_files(author.author_directories):
            if file_path in visible_file_paths:
                continue
            linked_book = file_to_book.get(file_path)
            results.append(UnmatchedLocalFile(
                file_path=file_path,
                file_name=file_name,
                file_size=file_size,
                file_format=file_format,
                linked_book_id=linked_book.id if linked_book else None,
                linked_book_title=linked_book.title if linked_book else None,
                author_id=author.id,
                author_name=author.name,
            ))
    return results
