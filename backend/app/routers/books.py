from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.database import get_db
from backend.app.models import Author, Book, BookSeries
from backend.app.schemas.book import BookSummary, BookDetail, SeriesPositionInfo
from backend.app.utils.book_visibility import get_book_visibility_settings, is_book_visible

router = APIRouter(prefix="/api/books", tags=["books"])


@router.get("", response_model=list[BookSummary])
async def list_books(
    sort: str = Query("title", regex="^(title|-title|author|-author|date|-date)$"),
    owned: bool | None = Query(None),
    author_id: int | None = Query(None),
    search: str = Query("", max_length=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(Book).options(
        selectinload(Book.author),
        selectinload(Book.book_series).selectinload(BookSeries.series),
    )

    if search:
        query = query.where(Book.title.ilike(f"%{search}%"))
    if owned is not None:
        query = query.where(Book.is_owned == owned)
    if author_id is not None:
        query = query.where(Book.author_id == author_id)

    if sort == "title":
        query = query.order_by(Book.title.asc())
    elif sort == "-title":
        query = query.order_by(Book.title.desc())
    elif sort == "author":
        query = query.join(Author).order_by(Author.name.asc(), Book.title.asc())
    elif sort == "-author":
        query = query.join(Author).order_by(Author.name.desc(), Book.title.asc())
    elif sort == "date":
        query = query.order_by(Book.release_date.asc())
    elif sort == "-date":
        query = query.order_by(Book.release_date.desc())

    result = await db.execute(query)
    visibility_settings = await get_book_visibility_settings(db)
    books = [
        book for book in result.scalars().all()
        if is_book_visible(book, visibility_settings)
    ]

    return [
        BookSummary(
            id=b.id,
            title=b.title,
            author_id=b.author_id,
            author_name=b.author.name if b.author else "Unknown",
            hardcover_id=b.hardcover_id,
            hardcover_slug=b.hardcover_slug,
            compilation=b.compilation,
            book_category_id=b.book_category_id,
            book_category_name=b.book_category_name,
            literary_type_id=b.literary_type_id,
            literary_type_name=b.literary_type_name,
            hardcover_state=b.hardcover_state,
            isbn=b.isbn,
            release_date=b.release_date,
            cover_image_url=b.cover_image_url,
            cover_image_cached_path=b.cover_image_cached_path,
            rating=b.rating,
            pages=b.pages,
            is_owned=b.is_owned,
            series_info=[
                SeriesPositionInfo(
                    series_id=bs.series.id,
                    series_name=bs.series.name,
                    position=bs.position,
                )
                for bs in b.book_series
            ],
        )
        for b in books
    ]


@router.get("/{book_id}", response_model=BookDetail)
async def get_book(book_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Book)
        .where(Book.id == book_id)
        .options(
            selectinload(Book.author),
            selectinload(Book.book_series).selectinload(BookSeries.series),
        )
    )
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    series_info = [
        SeriesPositionInfo(
            series_id=bs.series.id,
            series_name=bs.series.name,
            position=bs.position,
        )
        for bs in book.book_series
    ]

    return BookDetail(
        id=book.id,
        title=book.title,
        author_id=book.author_id,
        author_name=book.author.name if book.author else "Unknown",
        hardcover_id=book.hardcover_id,
        hardcover_slug=book.hardcover_slug,
        compilation=book.compilation,
        book_category_id=book.book_category_id,
        book_category_name=book.book_category_name,
        literary_type_id=book.literary_type_id,
        literary_type_name=book.literary_type_name,
        hardcover_state=book.hardcover_state,
        isbn=book.isbn,
        description=book.description,
        publisher=book.publisher,
        language=book.language,
        release_date=book.release_date,
        cover_image_url=book.cover_image_url,
        cover_image_cached_path=book.cover_image_cached_path,
        tags=book.tags,
        rating=book.rating,
        pages=book.pages,
        is_owned=book.is_owned,
        series_info=series_info,
    )
