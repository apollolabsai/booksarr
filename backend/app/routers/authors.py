import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.config import BOOKS_DIR
from backend.app.database import get_db
from backend.app.models import Author, AuthorDirectory, Book, BookFile, BookSeries, Series
from backend.app.schemas.author import (
    AuthorSummary, AuthorDetail, BookInAuthor, SeriesPositionInfo,
    SeriesInAuthor, SeriesBookEntry,
    AuthorPortraitOption, AuthorPortraitOptionsResponse, AuthorPortraitSelectionRequest,
    AuthorPortraitSearchResponse, AuthorPortraitSearchResult,
    AuthorSearchCandidate, AuthorSearchResponse, AuthorAddRequest, LocalBookFile, AuthorDirectoryEntry,
    AuthorDirectoryMergeRequest, AuthorDirectoryMergeResponse,
)
from backend.app.services.hardcover import HardcoverClient, HardcoverLookupError
from backend.app.services.google_image_search import search_author_portraits
from backend.app.utils.book_visibility import get_book_visibility_settings, is_book_visible
from backend.app.utils.isbn import has_any_valid_isbn
from backend.app.services.image_cache import get_cached_cover_aspect_ratio
from backend.app.services.author_images import get_author_portrait_options, set_author_portrait_selection
from backend.app.services.author_management import remove_author_and_books
from backend.app.services.library_sync import (
    _get_or_create_series,
    _deduplicate_books,
    _is_valid_title,
    enrich_imported_books_metadata,
    get_api_key,
    refresh_single_author,
)
from backend.app.utils.author_name import normalize_author_key
from backend.app.utils.hardcover_metadata import get_book_category_name, get_literary_type_name
from backend.app.utils.isbn import normalized_valid_isbn
from backend.app.utils.api_usage import begin_api_usage_batch, clear_api_usage_batch, flush_api_usage_batch

router = APIRouter(prefix="/api/authors", tags=["authors"])
logger = logging.getLogger("booksarr.authors")
_IGNORABLE_FOLDER_MERGE_FILES = {".ds_store", "thumbs.db", "desktop.ini"}


@router.get("/hardcover-search", response_model=AuthorSearchResponse)
async def search_hardcover_authors(
    query: str = Query(..., min_length=3, max_length=200),
    db: AsyncSession = Depends(get_db),
):
    api_key = await get_api_key(db)
    if not api_key:
        raise HTTPException(status_code=400, detail="Hardcover API key is not configured")

    client = HardcoverClient(api_key)
    usage_token = begin_api_usage_batch()
    try:
        candidates = await client.search_author_candidates(query)
    except HardcoverLookupError as exc:
        raise HTTPException(status_code=502, detail=f"Hardcover lookup failed: {exc}") from exc
    finally:
        clear_api_usage_batch(usage_token)
        await client.close()

    return AuthorSearchResponse(
        query=query,
        candidates=[
            AuthorSearchCandidate(
                hardcover_id=item.id,
                name=item.name,
                slug=item.slug,
                bio=item.bio,
                image_url=item.image_url,
                books_count=item.books_count,
            )
            for item in candidates
        ],
    )


@router.post("/add-from-hardcover", response_model=AuthorSummary)
async def add_author_from_hardcover(
    body: AuthorAddRequest,
    db: AsyncSession = Depends(get_db),
):
    api_key = await get_api_key(db)
    if not api_key:
        raise HTTPException(status_code=400, detail="Hardcover API key is not configured")

    client = HardcoverClient(api_key)
    usage_token = begin_api_usage_batch()
    try:
        logger.info("Add author requested from Hardcover: hardcover_id=%s", body.hardcover_id)
        hc_author = await client.get_author(body.hardcover_id)
        if hc_author is None:
            raise HTTPException(status_code=404, detail="Hardcover author not found")

        result = await db.execute(select(Author).where(Author.hardcover_id == hc_author.id))
        author = result.scalar_one_or_none()
        if author is None:
            result = await db.execute(
                select(Author)
                .where(Author.author_key == normalize_author_key(hc_author.name))
                .order_by(
                    Author.hardcover_id.is_(None),
                    Author.book_count_local.desc(),
                    Author.book_count_total.desc(),
                    Author.id,
                )
                .limit(1)
            )
            author = result.scalar_one_or_none()

        if author is None:
            author = Author(
                name=hc_author.name,
                hardcover_id=hc_author.id,
                hardcover_slug=hc_author.slug,
                bio=hc_author.bio,
                image_url=hc_author.image_url,
            )
            db.add(author)
            await db.flush()
        else:
            author.name = hc_author.name
            author.hardcover_id = hc_author.id
            author.hardcover_slug = hc_author.slug
            author.bio = hc_author.bio
            if not author.manual_image_source:
                author.image_url = hc_author.image_url

        folder_name = _sanitize_author_folder_name(hc_author.name)
        folder_path = BOOKS_DIR / folder_name
        folder_path.mkdir(parents=True, exist_ok=True)
        await _upsert_author_directory(db, author, folder_name)
        logger.info("Ensured author folder exists: %s", folder_path)

        hc_books = await client.get_author_books(hc_author.id)
        canonical_books = [b for b in hc_books if b.is_canonical]
        valid_books = [b for b in canonical_books if _is_valid_title(b.title)]
        eligible_books = _deduplicate_books(valid_books)
        author.book_count_total = len(eligible_books)
        logger.info(
            "Importing Hardcover author %s (hc_id=%s): %d raw, %d canonical, %d valid, %d eligible",
            hc_author.name,
            hc_author.id,
            len(hc_books),
            len(canonical_books),
            len(valid_books),
            len(eligible_books),
        )
        imported_book_ids: list[int] = []
        for hc_book in eligible_books:
            book_result = await db.execute(select(Book).where(Book.hardcover_id == hc_book.id))
            book = book_result.scalar_one_or_none()
            tags_json = json.dumps(hc_book.tags) if hc_book.tags else None
            if book:
                if book.title != hc_book.title:
                    book.google_id = None
                    book.google_published_date = None
                    book.google_cover_url = None
                    book.google_isbn_10 = None
                    book.google_isbn_13 = None
                    book.ol_edition_key = None
                    book.ol_first_publish_year = None
                    book.ol_cover_url = None
                    book.ol_isbn_10 = None
                    book.ol_isbn_13 = None
                    book.publish_date_checked_at = None
                if book.release_date != hc_book.release_date:
                    book.publish_date_checked_at = None
                book.title = hc_book.title
                book.author_id = author.id
                book.hardcover_slug = hc_book.slug
                book.compilation = hc_book.compilation
                book.book_category_id = hc_book.book_category_id
                book.book_category_name = get_book_category_name(hc_book.book_category_id)
                book.literary_type_id = hc_book.literary_type_id
                book.literary_type_name = get_literary_type_name(hc_book.literary_type_id)
                book.hardcover_state = hc_book.state or None
                book.hardcover_isbn_10 = normalized_valid_isbn(hc_book.isbn_10)
                book.hardcover_isbn_13 = normalized_valid_isbn(hc_book.isbn_13)
                book.description = hc_book.description
                book.release_date = hc_book.release_date
                book.cover_image_url = hc_book.image_url
                book.tags = tags_json
                book.rating = hc_book.rating
                book.pages = hc_book.pages
                book.language = hc_book.language
            else:
                book = Book(
                    title=hc_book.title,
                    author_id=author.id,
                    hardcover_id=hc_book.id,
                    hardcover_slug=hc_book.slug,
                    compilation=hc_book.compilation,
                    book_category_id=hc_book.book_category_id,
                    book_category_name=get_book_category_name(hc_book.book_category_id),
                    literary_type_id=hc_book.literary_type_id,
                    literary_type_name=get_literary_type_name(hc_book.literary_type_id),
                    hardcover_state=hc_book.state or None,
                    hardcover_isbn_10=normalized_valid_isbn(hc_book.isbn_10),
                    hardcover_isbn_13=normalized_valid_isbn(hc_book.isbn_13),
                    description=hc_book.description,
                    release_date=hc_book.release_date,
                    cover_image_url=hc_book.image_url,
                    tags=tags_json,
                    rating=hc_book.rating,
                    pages=hc_book.pages,
                    language=hc_book.language,
                    is_owned=False,
                )
                db.add(book)
                await db.flush()
                book.publish_date_checked_at = None

            for sr in hc_book.series_refs:
                series = await _get_or_create_series(db, sr.id, sr.name)
                existing_bs = await db.execute(
                    select(BookSeries).where(
                        BookSeries.book_id == book.id,
                        BookSeries.series_id == series.id,
                    )
                )
                if not existing_bs.scalar_one_or_none():
                    db.add(BookSeries(book_id=book.id, series_id=series.id, position=sr.position))
            imported_book_ids.append(book.id)

        await db.commit()
        await enrich_imported_books_metadata(db, imported_book_ids)
        await flush_api_usage_batch(db)
        await db.commit()
        result = await db.execute(
            select(Author)
            .options(selectinload(Author.books))
            .where(Author.id == author.id)
        )
        author = result.scalar_one()
        logger.info(
            "Added or updated author from Hardcover successfully: author_id=%s name=%r visible_books=%s",
            author.id,
            author.name,
            len(author.books),
        )
    except HardcoverLookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"Hardcover lookup failed: {exc}") from exc
    finally:
        clear_api_usage_batch(usage_token)
        await client.close()

    visibility_settings = await get_book_visibility_settings(db)
    visible_books = [book for book in author.books if is_book_visible(book, visibility_settings)]
    return AuthorSummary(
        id=author.id,
        name=author.name,
        hardcover_id=author.hardcover_id,
        hardcover_slug=author.hardcover_slug,
        bio=author.bio,
        image_url=author.image_url,
        image_cached_path=author.image_cached_path,
        book_count_local=sum(1 for book in visible_books if book.is_owned),
        book_count_total=len(visible_books),
    )


async def _upsert_author_directory(db: AsyncSession, author: Author, dir_name: str):
    result = await db.execute(select(AuthorDirectory).where(AuthorDirectory.dir_path == dir_name))
    author_dir = result.scalar_one_or_none()
    if author_dir is None:
        primary_result = await db.execute(
            select(AuthorDirectory).where(
                AuthorDirectory.author_id == author.id,
                AuthorDirectory.is_primary == True,
            )
        )
        has_primary = primary_result.scalar_one_or_none() is not None
        db.add(AuthorDirectory(
            author_id=author.id,
            dir_path=dir_name,
            is_primary=not has_primary,
        ))
        return

    author_dir.author_id = author.id


@router.post("/{author_id}/refresh")
async def refresh_author_route(author_id: int):
    try:
        await refresh_single_author(author_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HardcoverLookupError as exc:
        raise HTTPException(status_code=502, detail=f"Hardcover lookup failed: {exc}") from exc

    return {"status": "ok", "message": "Author refreshed"}


@router.delete("/{author_id}")
async def delete_author_route(author_id: int, db: AsyncSession = Depends(get_db)):
    try:
        removed_book_count = await remove_author_and_books(db, author_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "status": "ok",
        "message": "Author removed from database",
        "removed_book_count": removed_book_count,
    }


def _find_merge_conflicts(source_dir: Path, target_dir: Path, relative_path: Path | None = None) -> list[str]:
    rel_root = relative_path or Path(".")
    conflicts: list[str] = []

    for source_item in source_dir.iterdir():
        if _is_ignorable_folder_merge_path(source_item):
            continue
        rel_item = rel_root / source_item.name if rel_root != Path(".") else Path(source_item.name)
        target_item = target_dir / source_item.name
        if not target_item.exists():
            continue
        if source_item.is_dir() and target_item.is_dir():
            conflicts.extend(_find_merge_conflicts(source_item, target_item, rel_item))
            continue
        conflicts.append(rel_item.as_posix())

    return conflicts


def _move_directory_contents(source_dir: Path, target_dir: Path) -> int:
    moved_items = 0
    for source_item in sorted(source_dir.iterdir(), key=lambda item: item.name.lower()):
        if _is_ignorable_folder_merge_path(source_item):
            if source_item.is_dir():
                shutil.rmtree(source_item, ignore_errors=True)
            else:
                source_item.unlink(missing_ok=True)
            continue
        target_item = target_dir / source_item.name
        if source_item.is_dir() and target_item.exists() and target_item.is_dir():
            moved_items += _move_directory_contents(source_item, target_item)
            _remove_empty_directory_tree(source_item)
            continue

        shutil.move(str(source_item), str(target_item))
        moved_items += 1

    return moved_items


def _remove_empty_directory_tree(root: Path):
    if not root.exists() or not root.is_dir():
        return

    for child in root.iterdir():
        if child.is_dir():
            _remove_empty_directory_tree(child)

    if not any(root.iterdir()):
        root.rmdir()


def _replace_dir_prefix(file_path: str, source_dir_name: str, target_dir_name: str) -> str:
    prefix = f"{source_dir_name}/"
    if file_path.startswith(prefix):
        return f"{target_dir_name}/{file_path[len(prefix):]}"
    return file_path


def _replace_absolute_dir_prefix(path_text: str, source_dir_path: Path, target_dir_path: Path) -> str:
    source_prefix = f"{source_dir_path}/"
    if path_text.startswith(source_prefix):
        return f"{target_dir_path}/{path_text[len(source_prefix):]}"
    return path_text


def _is_ignorable_folder_merge_path(path: Path) -> bool:
    return path.name.lower() in _IGNORABLE_FOLDER_MERGE_FILES


@router.post("/{author_id}/merge-directories", response_model=AuthorDirectoryMergeResponse)
async def merge_author_directories_route(
    author_id: int,
    body: AuthorDirectoryMergeRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Author)
        .options(selectinload(Author.author_directories))
        .where(Author.id == author_id)
    )
    author = result.scalar_one_or_none()
    if not author:
        logger.warning("Author folder merge requested for missing author_id=%s", author_id)
        raise HTTPException(status_code=404, detail="Author not found")

    directories = sorted(author.author_directories, key=lambda item: (not item.is_primary, item.dir_path.lower()))
    if len(directories) < 2:
        logger.warning(
            "Author folder merge requested without enough linked directories: author_id=%s author=%r directories=%s",
            author.id,
            author.name,
            [directory.dir_path for directory in directories],
        )
        raise HTTPException(status_code=400, detail="Author does not have multiple linked directories")

    target_directory = next((directory for directory in directories if directory.id == body.target_directory_id), None)
    if target_directory is None:
        logger.warning(
            "Author folder merge requested with invalid target directory: author_id=%s author=%r target_directory_id=%s linked_directory_ids=%s",
            author.id,
            author.name,
            body.target_directory_id,
            [directory.id for directory in directories],
        )
        raise HTTPException(status_code=400, detail="Selected target directory is not linked to this author")

    source_directories = [directory for directory in directories if directory.id != target_directory.id]
    target_path = BOOKS_DIR / target_directory.dir_path
    target_path.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Starting author folder merge: author_id=%s author=%r keep=%s merge_sources=%s",
        author.id,
        author.name,
        target_directory.dir_path,
        [directory.dir_path for directory in source_directories],
    )

    for source_directory in source_directories:
        source_path = BOOKS_DIR / source_directory.dir_path
        if source_path.exists():
            conflicts = _find_merge_conflicts(source_path, target_path)
            if conflicts:
                logger.warning(
                    "Author folder merge blocked by conflicting file paths: author_id=%s author=%r source=%s target=%s conflicts=%s",
                    author.id,
                    author.name,
                    source_directory.dir_path,
                    target_directory.dir_path,
                    conflicts,
                )
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Cannot merge folder '{source_directory.dir_path}' into '{target_directory.dir_path}' "
                        f"because conflicting file paths already exist: {', '.join(conflicts[:5])}"
                    ),
                )

    moved_items = 0
    removed_directories: list[str] = []
    for source_directory in source_directories:
        source_path = BOOKS_DIR / source_directory.dir_path
        if source_path.exists():
            moved_items += _move_directory_contents(source_path, target_path)
            _remove_empty_directory_tree(source_path)
            if source_path.exists():
                logger.error(
                    "Author folder merge left source directory non-empty after move: author_id=%s author=%r source=%s target=%s",
                    author.id,
                    author.name,
                    source_directory.dir_path,
                    target_directory.dir_path,
                )
                raise HTTPException(
                    status_code=500,
                    detail=f"Source folder was not empty after merge: {source_directory.dir_path}",
                )

            book_files_result = await db.execute(
                select(BookFile).where(BookFile.file_path.like(f"{source_directory.dir_path}/%"))
            )
            for book_file in book_files_result.scalars().all():
                book_file.file_path = _replace_dir_prefix(
                    book_file.file_path,
                    source_directory.dir_path,
                    target_directory.dir_path,
                )
                if book_file.local_cover_path:
                    book_file.local_cover_path = _replace_absolute_dir_prefix(
                        book_file.local_cover_path,
                        source_path,
                        target_path,
                    )

        await db.delete(source_directory)
        removed_directories.append(source_directory.dir_path)

    for directory in directories:
        directory.is_primary = directory.id == target_directory.id
        if directory.id == target_directory.id:
            directory.last_seen_at = datetime.utcnow()

    await db.commit()
    logger.info(
        "Merged author directories: author_id=%s author=%r kept=%s removed=%s moved_items=%s",
        author.id,
        author.name,
        target_directory.dir_path,
        removed_directories,
        moved_items,
    )

    return AuthorDirectoryMergeResponse(
        status="ok",
        message="Author folders merged",
        kept_directory=target_directory.dir_path,
        removed_directories=removed_directories,
        moved_items=moved_items,
    )


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
    result = await db.execute(
        select(Author)
        .options(selectinload(Author.author_directories))
        .where(Author.id == author_id)
    )
    author = result.scalar_one_or_none()
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")

    # Get all books for this author with their series info
    books_result = await db.execute(
        select(Book)
        .where(Book.author_id == author_id)
        .options(
            selectinload(Book.files),
            selectinload(Book.book_series).selectinload(BookSeries.series),
        )
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
            ol_isbn_10=book.ol_isbn_10,
            ol_isbn_13=book.ol_isbn_13,
            has_valid_isbn=has_any_valid_isbn(
                book.isbn,
                book.hardcover_isbn_10,
                book.hardcover_isbn_13,
                book.google_isbn_10,
                book.google_isbn_13,
                book.ol_isbn_10,
                book.ol_isbn_13,
            ),
            matched_google=bool(book.google_id and book.google_id != "_none"),
            matched_openlibrary=bool(book.ol_edition_key and book.ol_edition_key != "_none"),
            description=book.description,
            release_date=book.release_date,
            cover_image_url=book.cover_image_url,
            cover_image_cached_path=book.cover_image_cached_path,
            cover_aspect_ratio=get_cached_cover_aspect_ratio(book.cover_image_cached_path),
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
        author_directories=[
            AuthorDirectoryEntry(
                id=directory.id,
                dir_path=directory.dir_path,
                is_primary=directory.is_primary,
            )
            for directory in sorted(
                author.author_directories,
                key=lambda item: (not item.is_primary, item.dir_path.lower()),
            )
        ],
        books=books_out,
        series=series_out,
    )


@router.get("/{author_id}/portrait-options", response_model=AuthorPortraitOptionsResponse)
async def get_author_portrait_options_route(author_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Author).where(Author.id == author_id))
    author = result.scalar_one_or_none()
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")

    options = await get_author_portrait_options(author)
    current_source = next((option["source"] for option in options if option["is_current"]), None)
    return AuthorPortraitOptionsResponse(
        author_id=author.id,
        current_source=current_source,
        manual_source=author.manual_image_source,
        options=[AuthorPortraitOption(**option) for option in options],
    )


@router.post("/{author_id}/portrait-selection")
async def set_author_portrait_selection_route(
    author_id: int,
    body: AuthorPortraitSelectionRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Author).where(Author.id == author_id))
    author = result.scalar_one_or_none()
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")

    success = await set_author_portrait_selection(
        author,
        source=body.source,
        image_url=body.image_url,
        page_url=body.page_url,
    )
    if not success:
        raise HTTPException(status_code=400, detail="Unable to save portrait")

    await db.commit()
    return {"status": "ok", "message": "Author portrait updated"}


@router.get("/{author_id}/portrait-search", response_model=AuthorPortraitSearchResponse)
async def search_author_portraits_route(author_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Author).where(Author.id == author_id))
    author = result.scalar_one_or_none()
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")

    query = f"{author.name} author portrait".strip()
    results = await search_author_portraits(author.name)
    return AuthorPortraitSearchResponse(
        author_id=author.id,
        query=query,
        results=[
            AuthorPortraitSearchResult(
                url=item.url,
                thumbnail_url=item.thumbnail_url,
                width=item.width,
                height=item.height,
                title=item.title,
                source_url=item.source_url,
            )
            for item in results
        ],
    )


def _sanitize_author_folder_name(value: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value).strip()
    sanitized = re.sub(r"\s+", " ", sanitized).rstrip(".")
    return sanitized or "Unknown Author"
