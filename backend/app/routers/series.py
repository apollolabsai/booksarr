from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.database import get_db
from backend.app.models import Series, BookSeries, Book
from backend.app.schemas.series import SeriesDetail, SeriesBookEntry

router = APIRouter(prefix="/api/series", tags=["series"])


@router.get("/{series_id}", response_model=SeriesDetail)
async def get_series(series_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Series)
        .where(Series.id == series_id)
        .options(
            selectinload(Series.book_series)
            .selectinload(BookSeries.book)
            .selectinload(Book.author)
        )
    )
    series = result.scalar_one_or_none()
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    books = sorted(series.book_series, key=lambda bs: bs.position if bs.position is not None else 9999)

    return SeriesDetail(
        id=series.id,
        hardcover_id=series.hardcover_id,
        name=series.name,
        description=series.description,
        is_completed=series.is_completed,
        book_count=len(books),
        books=[
            SeriesBookEntry(
                book_id=bs.book.id,
                title=bs.book.title,
                position=bs.position,
                is_owned=bs.book.is_owned,
                cover_image_cached_path=bs.book.cover_image_cached_path,
                author_name=bs.book.author.name if bs.book.author else "Unknown",
            )
            for bs in books
        ],
    )
