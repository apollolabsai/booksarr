from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.database import get_db
from backend.app.models import Author, Book, BookSeries, Series
from backend.app.schemas.author import (
    AuthorSummary, AuthorDetail, BookInAuthor, SeriesPositionInfo,
    SeriesInAuthor, SeriesBookEntry,
)

router = APIRouter(prefix="/api/authors", tags=["authors"])


@router.get("", response_model=list[AuthorSummary])
async def list_authors(
    sort: str = Query("name", regex="^(name|-name|books|-books|owned|-owned)$"),
    search: str = Query("", max_length=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(Author)
    if search:
        query = query.where(Author.name.ilike(f"%{search}%"))

    if sort == "name":
        query = query.order_by(Author.name.asc())
    elif sort == "-name":
        query = query.order_by(Author.name.desc())
    elif sort == "books":
        query = query.order_by(Author.book_count_total.asc())
    elif sort == "-books":
        query = query.order_by(Author.book_count_total.desc())
    elif sort == "owned":
        query = query.order_by(Author.book_count_local.asc())
    elif sort == "-owned":
        query = query.order_by(Author.book_count_local.desc())

    result = await db.execute(query)
    return result.scalars().all()


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
    books = books_result.scalars().all()

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
            isbn=book.isbn,
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
        book_count_local=author.book_count_local,
        book_count_total=author.book_count_total,
        books=books_out,
        series=series_out,
    )
