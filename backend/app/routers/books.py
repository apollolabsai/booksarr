import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.config import BOOKS_DIR
from backend.app.database import get_db
from backend.app.models import Author, Book, BookFile, BookSeries
from backend.app.schemas.book import (
    BookSummary,
    BookDetail,
    HiddenBookSummary,
    HiddenCategoryTag,
    LocalBookFile,
    SeriesPositionInfo,
    BookCoverOptionsResponse,
    CoverOption,
    BookCoverSelectionRequest,
    BookCoverSearchResponse,
    CoverSearchResult,
    BookVisibilityRequest,
    BookMetadataApplyOpfRequest,
    BookMetadataInfoResponse,
    BookMetadataUpdateRequest,
    BookMetadataValues,
    BookMetadataWriteOpfRequest,
    BookMetadataWriteOpfResponse,
    BookOpfMetadataFile,
)
from backend.app.utils.book_metadata import (
    effective_author_name,
    effective_description,
    effective_has_valid_isbn,
    effective_isbn,
    effective_language,
    effective_publisher,
    effective_release_date,
    effective_title,
)
from backend.app.utils.isbn import normalized_valid_isbn
from backend.app.utils.book_visibility import (
    get_book_visibility_settings,
    get_hidden_category,
    get_hidden_categories,
    is_book_visible,
)
from backend.app.services.library_sync import (
    refresh_single_book,
    get_book_cover_options,
    set_book_cover_selection,
)
from backend.app.services.image_cache import get_cached_cover_aspect_ratio
from backend.app.utils.opf_parser import OPFMetadata, write_epub_opf_metadata

router = APIRouter(prefix="/api/books", tags=["books"])

EDITABLE_METADATA_FIELDS = {
    "title",
    "author_name",
    "isbn",
    "publisher",
    "description",
    "release_date",
    "language",
    "series_name",
    "series_position",
}


def _clean_metadata_value(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _manual_series_position(book: Book) -> float | None:
    return book.manual_series_position


def _original_series_name(book: Book) -> str | None:
    if not book.book_series:
        return None
    first = book.book_series[0]
    return first.series.name if first.series else None


def _original_series_position(book: Book) -> float | None:
    if not book.book_series:
        return None
    first = book.book_series[0]
    return first.position


def _metadata_values(book: Book, *, source: str) -> BookMetadataValues:
    if source == "current":
        return BookMetadataValues(
            title=effective_title(book),
            author_name=effective_author_name(book),
            isbn=effective_isbn(book),
            publisher=effective_publisher(book),
            description=effective_description(book),
            release_date=effective_release_date(book),
            language=effective_language(book),
            series_name=_clean_metadata_value(book.manual_series_name) or _original_series_name(book),
            series_position=_manual_series_position(book) if book.manual_series_position is not None else _original_series_position(book),
        )
    if source == "manual":
        return BookMetadataValues(
            title=book.manual_title,
            author_name=book.manual_author_name,
            isbn=book.manual_isbn,
            publisher=book.manual_publisher,
            description=book.manual_description,
            release_date=book.manual_release_date,
            language=book.manual_language,
            series_name=book.manual_series_name,
            series_position=book.manual_series_position,
        )
    return BookMetadataValues(
        title=book.title,
        author_name=book.author.name if book.author else "Unknown",
        isbn=book.isbn,
        publisher=book.publisher,
        description=book.description,
        release_date=book.release_date,
        language=book.language,
        series_name=_original_series_name(book),
        series_position=_original_series_position(book),
    )


def _opf_metadata_values(book_file: BookFile) -> dict[str, str | float | None]:
    return {
        "title": book_file.opf_title,
        "author_name": book_file.opf_author,
        "isbn": book_file.opf_isbn,
        "publisher": book_file.opf_publisher,
        "description": book_file.opf_description,
        "release_date": book_file.opf_date,
        "language": book_file.opf_language,
        "series_name": book_file.opf_series,
        "series_position": book_file.opf_series_index,
    }


def _assign_manual_metadata(book: Book, field_name: str, value: str | float | None) -> None:
    if field_name == "isbn" and isinstance(value, str):
        value = normalized_valid_isbn(value) or value.strip()
    if isinstance(value, str):
        value = _clean_metadata_value(value)
    if field_name == "series_position":
        setattr(book, "manual_series_position", value)
        return
    setattr(book, f"manual_{field_name}", value)


def _clear_manual_metadata(book: Book, field_name: str) -> None:
    if field_name == "series_position":
        book.manual_series_position = None
        return
    setattr(book, f"manual_{field_name}", None)


def _update_book_file_opf_metadata(book_file: BookFile, opf: OPFMetadata) -> None:
    book_file.opf_title = opf.title or None
    book_file.opf_author = opf.author or None
    book_file.opf_isbn = opf.isbn or None
    book_file.opf_series = opf.series or None
    book_file.opf_series_index = opf.series_index
    book_file.opf_publisher = opf.publisher or None
    book_file.opf_description = opf.description or None
    book_file.opf_date = opf.date or None
    book_file.opf_language = opf.language or None


def _archive_directory_for_download(source_dir: Path) -> Path:
    temp_file = tempfile.NamedTemporaryFile(prefix="booksarr-download-", suffix=".zip", delete=False)
    archive_path = Path(temp_file.name)
    temp_file.close()

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for child in sorted(source_dir.rglob("*")):
            if child.is_file():
                archive.write(child, arcname=str(child.relative_to(source_dir)))

    return archive_path


def _book_summary(book: Book) -> BookSummary:
    owned_copy_count = len(book.files) if book.is_owned else 0
    return BookSummary(
        id=book.id,
        title=effective_title(book),
        author_id=book.author_id,
        author_name=effective_author_name(book),
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
        isbn=effective_isbn(book),
        google_isbn_10=book.google_isbn_10,
        google_isbn_13=book.google_isbn_13,
        ol_isbn_10=book.ol_isbn_10,
        ol_isbn_13=book.ol_isbn_13,
        has_valid_isbn=effective_has_valid_isbn(book),
        matched_google=bool(book.google_id and book.google_id != "_none"),
        matched_openlibrary=bool(book.ol_edition_key and book.ol_edition_key != "_none"),
        release_date=effective_release_date(book),
        manual_title=book.manual_title,
        manual_author_name=book.manual_author_name,
        manual_isbn=book.manual_isbn,
        manual_publisher=book.manual_publisher,
        manual_description=book.manual_description,
        manual_release_date=book.manual_release_date,
        manual_language=book.manual_language,
        manual_series_name=book.manual_series_name,
        manual_series_position=book.manual_series_position,
        cover_image_url=book.cover_image_url,
        cover_image_cached_path=book.cover_image_cached_path,
        cover_aspect_ratio=get_cached_cover_aspect_ratio(book.cover_image_cached_path),
        rating=book.rating,
        pages=book.pages,
        is_owned=book.is_owned,
        owned_copy_count=owned_copy_count,
        local_files=[
            LocalBookFile(
                id=book_file.id,
                file_path=book_file.file_path,
                file_name=book_file.file_name,
                file_size=book_file.file_size,
                file_format=book_file.file_format,
            )
            for book_file in book.files
        ],
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
        selectinload(Book.files),
        selectinload(Book.book_series).selectinload(BookSeries.series),
    )

    if search:
        query = query.where(
            or_(
                Book.title.ilike(f"%{search}%"),
                Book.manual_title.ilike(f"%{search}%"),
                Book.manual_author_name.ilike(f"%{search}%"),
            )
        )
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
        selectinload(Book.files),
        selectinload(Book.book_series).selectinload(BookSeries.series),
    ).order_by(Book.title.asc())

    if search:
        query = (
            query.join(Author)
            .where(
                or_(
                    Book.title.ilike(f"%{search}%"),
                    Book.manual_title.ilike(f"%{search}%"),
                    Book.manual_author_name.ilike(f"%{search}%"),
                    Author.name.ilike(f"%{search}%"),
                )
            )
        )

    result = await db.execute(query)
    visibility_settings = await get_book_visibility_settings(db)
    hidden_books: list[HiddenBookSummary] = []
    for book in result.scalars().all():
        hidden_categories = get_hidden_categories(book, visibility_settings)
        if not hidden_categories:
            continue
        hidden_category = hidden_categories[0]
        summary = _book_summary(book)
        hidden_books.append(HiddenBookSummary(
            **summary.model_dump(),
            hidden_category_key=hidden_category[0],
            hidden_category_label=hidden_category[1],
            hidden_categories=[
                HiddenCategoryTag(key=key, label=label)
                for key, label in hidden_categories
            ],
        ))
    return hidden_books


@router.get("/{book_id}/metadata-info", response_model=BookMetadataInfoResponse)
async def get_book_metadata_info(book_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Book)
        .where(Book.id == book_id)
        .options(
            selectinload(Book.author),
            selectinload(Book.files),
            selectinload(Book.book_series).selectinload(BookSeries.series),
        )
    )
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    return BookMetadataInfoResponse(
        book_id=book.id,
        hardcover_id=book.hardcover_id,
        hardcover_slug=book.hardcover_slug,
        current=_metadata_values(book, source="current"),
        original=_metadata_values(book, source="original"),
        manual=_metadata_values(book, source="manual"),
        files=[
            BookOpfMetadataFile(
                id=book_file.id,
                file_path=book_file.file_path,
                file_name=book_file.file_name,
                file_format=book_file.file_format,
                file_size=book_file.file_size,
                opf_title=book_file.opf_title,
                opf_author=book_file.opf_author,
                opf_isbn=book_file.opf_isbn,
                opf_publisher=book_file.opf_publisher,
                opf_description=book_file.opf_description,
                opf_date=book_file.opf_date,
                opf_language=book_file.opf_language,
                opf_series=book_file.opf_series,
                opf_series_index=book_file.opf_series_index,
            )
            for book_file in sorted(book.files, key=lambda bf: bf.file_path)
        ],
        editable_fields=sorted(EDITABLE_METADATA_FIELDS),
    )


@router.patch("/{book_id}/metadata")
async def update_book_metadata(
    book_id: int,
    body: BookMetadataUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    clear_fields = set(body.clear_fields or [])
    invalid_clear_fields = clear_fields - EDITABLE_METADATA_FIELDS
    if invalid_clear_fields:
        raise HTTPException(status_code=400, detail=f"Invalid metadata field: {sorted(invalid_clear_fields)[0]}")

    payload = body.model_dump(exclude_unset=True, exclude={"clear_fields"})
    invalid_fields = set(payload) - EDITABLE_METADATA_FIELDS
    if invalid_fields:
        raise HTTPException(status_code=400, detail=f"Invalid metadata field: {sorted(invalid_fields)[0]}")

    isbn_value = payload.get("isbn")
    if isinstance(isbn_value, str) and isbn_value.strip() and normalized_valid_isbn(isbn_value) is None:
        raise HTTPException(status_code=400, detail="Invalid ISBN")

    for field_name in clear_fields:
        _clear_manual_metadata(book, field_name)

    for field_name, value in payload.items():
        if field_name in clear_fields:
            continue
        _assign_manual_metadata(book, field_name, value)

    await db.commit()
    return {"status": "ok", "message": "Metadata overrides saved"}


@router.post("/{book_id}/metadata/apply-opf")
async def apply_opf_metadata(
    book_id: int,
    body: BookMetadataApplyOpfRequest,
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

    book_file = next((file for file in book.files if file.id == body.book_file_id), None)
    if book_file is None:
        raise HTTPException(status_code=404, detail="Book file not found for this book")

    requested_fields = set(body.fields)
    invalid_fields = requested_fields - EDITABLE_METADATA_FIELDS
    if invalid_fields:
        raise HTTPException(status_code=400, detail=f"Invalid metadata field: {sorted(invalid_fields)[0]}")
    if not requested_fields:
        raise HTTPException(status_code=400, detail="Select at least one field")

    opf_values = _opf_metadata_values(book_file)
    isbn_value = opf_values.get("isbn")
    if "isbn" in requested_fields and isinstance(isbn_value, str) and isbn_value.strip() and normalized_valid_isbn(isbn_value) is None:
        raise HTTPException(status_code=400, detail="OPF ISBN is invalid")

    for field_name in requested_fields:
        _assign_manual_metadata(book, field_name, opf_values.get(field_name))

    await db.commit()
    return {"status": "ok", "message": "Selected OPF metadata applied"}


@router.post("/{book_id}/metadata/write-opf", response_model=BookMetadataWriteOpfResponse)
async def write_opf_metadata(
    book_id: int,
    body: BookMetadataWriteOpfRequest,
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

    book_file = next((file for file in book.files if file.id == body.book_file_id), None)
    if book_file is None:
        raise HTTPException(status_code=404, detail="Book file not found for this book")

    requested_fields = set(body.fields)
    invalid_fields = requested_fields - EDITABLE_METADATA_FIELDS
    if invalid_fields:
        raise HTTPException(status_code=400, detail=f"Invalid metadata field: {sorted(invalid_fields)[0]}")
    if not requested_fields:
        raise HTTPException(status_code=400, detail="Select at least one field")

    if (book_file.file_format or "").lower() != "epub":
        raise HTTPException(status_code=400, detail="OPF repair is only supported for EPUB files")

    selected_values: dict[str, str | float | None] = {}
    values = body.values.model_dump()
    for field_name in requested_fields:
        value = values.get(field_name)
        if isinstance(value, str):
            value = value.strip()
        if value in {None, ""}:
            raise HTTPException(status_code=400, detail=f"No value provided for {field_name}")
        selected_values[field_name] = value

    isbn_value = selected_values.get("isbn")
    if isinstance(isbn_value, str) and normalized_valid_isbn(isbn_value) is None:
        raise HTTPException(status_code=400, detail="Invalid ISBN")
    if isinstance(isbn_value, str):
        selected_values["isbn"] = normalized_valid_isbn(isbn_value)

    epub_path = BOOKS_DIR / book_file.file_path
    if not epub_path.exists() or not epub_path.is_file():
        raise HTTPException(status_code=404, detail="Local EPUB file not found")

    try:
        opf, backup_path = write_epub_opf_metadata(epub_path, selected_values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to repair OPF metadata: {exc}")

    _update_book_file_opf_metadata(book_file, opf)
    await db.commit()
    backup_display_path = str(backup_path.relative_to(BOOKS_DIR)) if backup_path.is_relative_to(BOOKS_DIR) else str(backup_path)
    if body.delete_backup:
        backup_path.unlink(missing_ok=True)
        backup_display_path = ""
    return BookMetadataWriteOpfResponse(
        status="ok",
        message="EPUB OPF metadata repaired",
        backup_path=backup_display_path,
    )


@router.get("/{book_id}", response_model=BookDetail)
async def get_book(book_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Book)
        .where(Book.id == book_id)
        .options(
            selectinload(Book.author),
            selectinload(Book.files),
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
        title=effective_title(book),
        author_id=book.author_id,
        author_name=effective_author_name(book),
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
        isbn=effective_isbn(book),
        google_isbn_10=book.google_isbn_10,
        google_isbn_13=book.google_isbn_13,
        ol_isbn_10=book.ol_isbn_10,
        ol_isbn_13=book.ol_isbn_13,
        has_valid_isbn=effective_has_valid_isbn(book),
        matched_google=bool(book.google_id and book.google_id != "_none"),
        matched_openlibrary=bool(book.ol_edition_key and book.ol_edition_key != "_none"),
        description=effective_description(book),
        publisher=effective_publisher(book),
        language=effective_language(book),
        release_date=effective_release_date(book),
        manual_title=book.manual_title,
        manual_author_name=book.manual_author_name,
        manual_isbn=book.manual_isbn,
        manual_publisher=book.manual_publisher,
        manual_description=book.manual_description,
        manual_release_date=book.manual_release_date,
        manual_language=book.manual_language,
        manual_series_name=book.manual_series_name,
        manual_series_position=book.manual_series_position,
        cover_image_url=book.cover_image_url,
        cover_image_cached_path=book.cover_image_cached_path,
        cover_aspect_ratio=get_cached_cover_aspect_ratio(book.cover_image_cached_path),
        tags=book.tags,
        rating=book.rating,
        pages=book.pages,
        is_owned=book.is_owned,
        owned_copy_count=len(book.files) if book.is_owned else 0,
        local_files=[
            LocalBookFile(
                id=book_file.id,
                file_path=book_file.file_path,
                file_name=book_file.file_name,
                file_size=book_file.file_size,
                file_format=book_file.file_format,
            )
            for book_file in book.files
        ],
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

    if not await set_book_cover_selection(book, body.source, url=body.url):
        raise HTTPException(status_code=400, detail="Cover source is not available for this book")

    await db.commit()
    return {"status": "ok", "message": "Cover updated"}


@router.get("/{book_id}/cover-search", response_model=BookCoverSearchResponse)
async def search_book_covers_route(book_id: int, db: AsyncSession = Depends(get_db)):
    from backend.app.services.google_image_search import search_book_covers

    result = await db.execute(
        select(Book)
        .where(Book.id == book_id)
        .options(selectinload(Book.author))
    )
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    author_name = book.author.name if book.author else ""
    query = f"{book.title} {author_name}".strip()
    results = await search_book_covers(book.title, author_name)

    return BookCoverSearchResponse(
        book_id=book.id,
        query=query,
        results=[
            CoverSearchResult(
                url=r.url,
                thumbnail_url=r.thumbnail_url,
                width=r.width,
                height=r.height,
                title=r.title,
                source_url=r.source_url,
            )
            for r in results
        ],
    )


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


@router.get("/{book_id}/download")
async def download_book(
    book_id: int,
    file_id: int | None = Query(default=None, ge=1),
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
    if not book.is_owned or not book.files:
        raise HTTPException(status_code=404, detail="No local file available for this book")

    if file_id is not None:
        book_file = next((file for file in book.files if file.id == file_id), None)
        if book_file is None:
            raise HTTPException(status_code=404, detail="Requested local file not found for this book")
    else:
        preferred_formats = ("epub", "mobi", "pdf", "audiobook")
        files_by_format = {(f.file_format or "").lower(): f for f in sorted(book.files, key=lambda f: f.id)}
        book_file = next(
            (files_by_format[fmt] for fmt in preferred_formats if fmt in files_by_format),
            sorted(book.files, key=lambda file: file.id)[0],
        )

    file_path = BOOKS_DIR / book_file.file_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Local file not available for download")

    if file_path.is_dir():
        archive_path = _archive_directory_for_download(file_path)
        return FileResponse(
            str(archive_path),
            media_type="application/zip",
            filename=f"{book_file.file_name}.zip",
            background=BackgroundTask(lambda path=archive_path: path.unlink(missing_ok=True)),
        )
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Local file not available for download")

    fmt = (book_file.file_format or "").lower()
    media_types = {
        "epub": "application/epub+zip",
        "mobi": "application/x-mobipocket-ebook",
        "pdf": "application/pdf",
    }
    media_type = media_types.get(fmt, "application/octet-stream")
    return FileResponse(
        str(file_path),
        media_type=media_type,
        filename=book_file.file_name,
    )
