from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.database import get_db
from backend.app.models import Author, Book, BookSeries, Series
from backend.app.schemas.author import (
    AuthorSummary, AuthorDetail, BookInAuthor, SeriesPositionInfo,
    SeriesInAuthor, SeriesBookEntry,
)
from backend.app.utils.book_visibility import get_book_visibility_settings, is_book_visible
from backend.app.utils.isbn import has_any_valid_isbn

router = APIRouter(prefix="/api/authors", tags=["authors"])


@router.get("", response_model=list[AuthorSummary])
async def list_authors(
    sort: str = Query("name", regex="^(name|-name|books|-books|owned|-owned)$"),
    search: str = Query("", max_length=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(Author).options(selectinload(Author.books))
    if search:
        query = query.where(Author.name.ilike(f"%{search}%"))
    result = await db.execute(query)
    visibility_settings = await get_book_visibility_settings(db)
    authors = result.scalars().all()

    summaries = []
    for author in authors:
        visible_books = [book for book in author.books if is_book_visible(book, visibility_settings)]
        if not visible_books:
            continue
        summaries.append(AuthorSummary(
            id=author.id,
            name=author.name,
            hardcover_id=author.hardcover_id,
            hardcover_slug=author.hardcover_slug,
            bio=author.bio,
            image_url=author.image_url,
            image_cached_path=author.image_cached_path,
            book_count_local=sum(1 for book in visible_books if book.is_owned),
            book_count_total=len(visible_books),
        ))

    if sort == "name":
        summaries.sort(key=lambda author: author.name.lower())
    elif sort == "-name":
        summaries.sort(key=lambda author: author.name.lower(), reverse=True)
    elif sort == "books":
        summaries.sort(key=lambda author: (author.book_count_total, author.name.lower()))
    elif sort == "-books":
        summaries.sort(key=lambda author: (author.book_count_total, author.name.lower()), reverse=True)
    elif sort == "owned":
        summaries.sort(key=lambda author: (author.book_count_local, author.name.lower()))
    elif sort == "-owned":
        summaries.sort(key=lambda author: (author.book_count_local, author.name.lower()), reverse=True)

    return summaries


@router.get("/{author_id}", response_model=AuthorDetail)
async def get_author(author_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Author).where(Author.id == author_id))
    author = result.scalar_one_or_none()
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")

    # Get all books for this author with their series info
    books_result = await db.execute(
        select(Book)
        .where(Book.author_id == author_id)
        .options(selectinload(Book.book_series).selectinload(BookSeries.series))
    )
    all_books = books_result.scalars().all()

    # Filter to visible books only
    visibility_settings = await get_book_visibility_settings(db)
    books = [b for b in all_books if is_book_visible(b, visibility_settings)]

    # Build series map
    series_map: dict[int, dict] = {}
    books_out = []
    for book in books:
        series_info = []
        for bs in book.book_series:
            s = bs.series
            series_info.append(SeriesPositionInfo(
                series_id=s.id,
                series_name=s.name,
                position=bs.position,
            ))
            if s.id not in series_map:
                series_map[s.id] = {
                    "id": s.id,
                    "name": s.name,
                    "hardcover_id": s.hardcover_id,
                    "books": [],
                }
            series_map[s.id]["books"].append(SeriesBookEntry(
                book_id=book.id,
                title=book.title,
                position=bs.position,
                is_owned=book.is_owned,
                cover_image_cached_path=book.cover_image_cached_path,
            ))

        books_out.append(BookInAuthor(
            id=book.id,
            title=book.title,
            hardcover_id=book.hardcover_id,
            hardcover_slug=book.hardcover_slug,
            compilation=book.compilation,
            book_category_id=book.book_category_id,
            book_category_name=book.book_category_name,
            literary_type_id=book.literary_type_id,
            literary_type_name=book.literary_type_name,
            hardcover_state=book.hardcover_state,
            hardcover_isbn_10=book.hardcover_isbn_10,
            hardcover_isbn_13=book.hardcover_isbn_13,
            isbn=book.isbn,
            google_isbn_10=book.google_isbn_10,
            google_isbn_13=book.google_isbn_13,
            has_valid_isbn=has_any_valid_isbn(
                book.isbn,
                book.hardcover_isbn_10,
                book.hardcover_isbn_13,
                book.google_isbn_10,
                book.google_isbn_13,
            ),
            matched_google=bool(book.google_id and book.google_id != "_none"),
            matched_openlibrary=bool(book.ol_edition_key and book.ol_edition_key != "_none"),
            description=book.description,
            release_date=book.release_date,
            cover_image_url=book.cover_image_url,
            cover_image_cached_path=book.cover_image_cached_path,
            rating=book.rating,
            pages=book.pages,
            is_owned=book.is_owned,
            series_info=series_info,
        ))

    # Sort series books by position
    series_out = []
    for s_data in series_map.values():
        s_data["books"].sort(key=lambda b: b.position if b.position is not None else 9999)
        series_out.append(SeriesInAuthor(**s_data))
    series_out.sort(key=lambda s: s.name)

    return AuthorDetail(
        id=author.id,
        name=author.name,
        hardcover_id=author.hardcover_id,
        hardcover_slug=author.hardcover_slug,
        bio=author.bio,
        image_url=author.image_url,
        image_cached_path=author.image_cached_path,
        book_count_local=sum(1 for book in books if book.is_owned),
        book_count_total=len(books),
        books=books_out,
        series=series_out,
    )
