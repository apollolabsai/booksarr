from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.database import get_db
from backend.app.models import Author, Book, BookSeries
from backend.app.schemas.book import (
    BookSummary,
    BookDetail,
    HiddenBookSummary,
    SeriesPositionInfo,
    BookCoverOptionsResponse,
    CoverOption,
    BookCoverSelectionRequest,
    BookVisibilityRequest,
)
from backend.app.utils.isbn import has_any_valid_isbn
from backend.app.utils.book_visibility import (
    get_book_visibility_settings,
    get_hidden_category,
    is_book_visible,
)
from backend.app.services.library_sync import (
    refresh_single_book,
    get_book_cover_options,
    set_book_cover_selection,
)
from backend.app.services.image_cache import get_cached_cover_aspect_ratio

router = APIRouter(prefix="/api/books", tags=["books"])


def _book_summary(book: Book) -> BookSummary:
    return BookSummary(
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
        release_date=book.release_date,
        cover_image_url=book.cover_image_url,
        cover_image_cached_path=book.cover_image_cached_path,
        cover_aspect_ratio=get_cached_cover_aspect_ratio(book.cover_image_cached_path),
        rating=book.rating,
        pages=book.pages,
        is_owned=book.is_owned,
        series_info=[
            SeriesPositionInfo(
                series_id=bs.series.id,
                series_name=bs.series.name,
                position=bs.position,
            )
            for bs in book.book_series
        ],
    )


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

    return [_book_summary(book) for book in books]


@router.get("/hidden", response_model=list[HiddenBookSummary])
async def list_hidden_books(
    search: str = Query("", max_length=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(Book).options(
        selectinload(Book.author),
        selectinload(Book.book_series).selectinload(BookSeries.series),
    ).order_by(Book.title.asc())

    if search:
        query = query.where(Book.title.ilike(f"%{search}%"))

    result = await db.execute(query)
    visibility_settings = await get_book_visibility_settings(db)
    hidden_books: list[HiddenBookSummary] = []
    for book in result.scalars().all():
        hidden_category = get_hidden_category(book, visibility_settings)
        if not hidden_category:
            continue
        summary = _book_summary(book)
        hidden_books.append(HiddenBookSummary(
            **summary.model_dump(),
            hidden_category_key=hidden_category[0],
            hidden_category_label=hidden_category[1],
        ))
    return hidden_books


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
        publisher=book.publisher,
        language=book.language,
        release_date=book.release_date,
        cover_image_url=book.cover_image_url,
        cover_image_cached_path=book.cover_image_cached_path,
        cover_aspect_ratio=get_cached_cover_aspect_ratio(book.cover_image_cached_path),
        tags=book.tags,
        rating=book.rating,
        pages=book.pages,
        is_owned=book.is_owned,
        series_info=series_info,
    )


@router.get("/{book_id}/cover-options", response_model=BookCoverOptionsResponse)
async def get_book_cover_options_route(book_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Book)
        .where(Book.id == book_id)
        .options(selectinload(Book.files))
    )
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    options = await get_book_cover_options(book)
    current_source = next((option["source"] for option in options if option["is_current"]), None)
    return BookCoverOptionsResponse(
        book_id=book.id,
        current_source=current_source,
        manual_source=book.manual_cover_source,
        options=[CoverOption(**option) for option in options],
    )


@router.post("/{book_id}/cover-selection")
async def set_book_cover_selection_route(
    book_id: int,
    body: BookCoverSelectionRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Book)
        .where(Book.id == book_id)
        .options(selectinload(Book.files))
    )
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    if not await set_book_cover_selection(book, body.source):
        raise HTTPException(status_code=400, detail="Cover source is not available for this book")

    await db.commit()
    return {"status": "ok", "message": "Cover updated"}


@router.post("/{book_id}/visibility")
async def set_book_visibility_route(
    book_id: int,
    body: BookVisibilityRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    action = body.action.strip().lower()
    if action == "hide":
        book.manual_visibility = "hidden"
        message = "Book hidden"
    elif action == "show":
        book.manual_visibility = "visible"
        message = "Book unhidden"
    elif action == "reset":
        book.manual_visibility = None
        message = "Book visibility reset"
    else:
        raise HTTPException(status_code=400, detail="Invalid visibility action")

    await db.commit()
    return {"status": "ok", "message": message}


@router.post("/{book_id}/refresh")
async def refresh_book(book_id: int):
    try:
        await refresh_single_book(book_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Book not found")
    return {"status": "ok", "message": "Book metadata refreshed"}
