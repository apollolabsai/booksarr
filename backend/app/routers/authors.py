import asyncio
import errno
import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.config import BOOKS_DIR
from backend.app.database import async_session, get_db
from backend.app.models import Author, AuthorDirectory, Book, BookFile, BookSeries, Series
from backend.app.schemas.author import (
    AuthorSummary, AuthorDetail, BookInAuthor, SeriesPositionInfo,
    SeriesInAuthor, SeriesBookEntry,
    AuthorPortraitOption, AuthorPortraitOptionsResponse, AuthorPortraitSelectionRequest,
    AuthorPortraitSearchResponse, AuthorPortraitSearchResult,
    AuthorSearchCandidate, AuthorSearchResponse, AuthorAddRequest, AuthorRelinkRequest, LocalBookFile, AuthorDirectoryEntry,
    AuthorDirectoryMergeRequest, AuthorDirectoryMergeResponse, UnmatchedLocalFile,
)
from backend.app.services.hardcover import HardcoverClient, HardcoverLookupError
from backend.app.services.google_image_search import search_author_portraits
from backend.app.services.scanner import _classify_standalone_file, _collect_book_dir_artifacts
from backend.app.utils.book_visibility import book_visibility_sql_filter, get_book_visibility_settings, is_book_visible
from backend.app.utils.book_metadata import (
    effective_description,
    effective_has_valid_isbn,
    effective_isbn,
    effective_release_date,
    effective_title,
)
from backend.app.services.image_cache import get_cached_cover_aspect_ratio
from backend.app.services.author_images import get_author_portrait_options, set_author_portrait_selection
from backend.app.services.author_management import remove_author_and_books
from backend.app.services.library_sync import (
    _get_or_create_series,
    _deduplicate_books,
    _is_valid_title,
    enrich_imported_books_metadata,
    get_api_key,
    author_refresh_status,
    trigger_author_refresh,
)
from backend.app.utils.author_name import author_sort_key, normalize_author_key
from backend.app.utils.hardcover_metadata import get_book_category_name, get_literary_type_name
from backend.app.utils.isbn import normalized_valid_isbn
from backend.app.utils.api_usage import begin_api_usage_batch, clear_api_usage_batch, flush_api_usage_batch

router = APIRouter(prefix="/api/authors", tags=["authors"])
logger = logging.getLogger("booksarr.authors")
_IGNORABLE_FOLDER_MERGE_FILES = {".ds_store", "thumbs.db", "desktop.ini"}


class AuthorAddStatus:
    def __init__(self):
        self.status = "idle"
        self.hardcover_id: int | None = None
        self.author_id: int | None = None
        self.author_name: str | None = None
        self.progress = 0.0
        self.message = ""
        self.started_at: str | None = None
        self.completed_at: str | None = None
        self.error: str | None = None

    def start(self, hardcover_id: int):
        self.status = "adding"
        self.hardcover_id = hardcover_id
        self.author_id = None
        self.author_name = None
        self.progress = 0.0
        self.message = "Starting author import..."
        self.started_at = datetime.utcnow().isoformat()
        self.completed_at = None
        self.error = None

    def update(
        self,
        *,
        progress: float | None = None,
        message: str | None = None,
        author_id: int | None = None,
        author_name: str | None = None,
    ):
        if progress is not None:
            self.progress = max(0.0, min(100.0, progress))
        if message is not None:
            self.message = message
        if author_id is not None:
            self.author_id = author_id
        if author_name is not None:
            self.author_name = author_name

    def complete(self, author: AuthorSummary):
        self.status = "completed"
        self.author_id = author.id
        self.author_name = author.name
        self.progress = 100.0
        self.message = f"Finished adding {author.name}."
        self.completed_at = datetime.utcnow().isoformat()
        self.error = None

    def fail(self, error: str):
        self.status = "failed"
        self.progress = 0.0
        self.message = f"Author import failed: {error}"
        self.completed_at = datetime.utcnow().isoformat()
        self.error = error

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "hardcover_id": self.hardcover_id,
            "author_id": self.author_id,
            "author_name": self.author_name,
            "progress": self.progress,
            "message": self.message,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }


author_add_status = AuthorAddStatus()


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


async def _build_author_summary(db: AsyncSession, author: Author) -> AuthorSummary:
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


async def _ensure_author_directory_mapping(db: AsyncSession, author: Author, folder_name: str) -> None:
    folder_path = BOOKS_DIR / folder_name
    try:
        folder_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        if exc.errno not in {errno.EACCES, errno.EPERM, errno.EROFS}:
            raise
        logger.warning(
            "Could not create author folder %s because the books library is not writable; "
            "continuing with Hardcover catalog import",
            folder_path,
        )
    else:
        logger.info("Ensured author folder exists: %s", folder_path)

    await _upsert_author_directory(db, author, folder_name)


async def _prepare_author_from_hardcover(
    db: AsyncSession,
    hardcover_id: int,
    client: HardcoverClient,
) -> Author:
    author_add_status.update(progress=8.0, message="Fetching Hardcover author profile...")
    hc_author = await client.get_author(hardcover_id)
    if hc_author is None:
        raise ValueError("Hardcover author not found")

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
        message = f"Created local author record for {hc_author.name}."
    else:
        author.name = hc_author.name
        author.hardcover_id = hc_author.id
        author.hardcover_slug = hc_author.slug
        author.bio = hc_author.bio
        if not author.manual_image_source:
            author.image_url = hc_author.image_url
        message = f"Updating existing local author record for {hc_author.name}."

    folder_name = _sanitize_author_folder_name(hc_author.name)
    await _ensure_author_directory_mapping(db, author, folder_name)

    author_add_status.update(
        progress=18.0,
        message=message,
        author_id=author.id,
        author_name=author.name,
    )
    return author


async def _add_author_from_hardcover(
    db: AsyncSession,
    hardcover_id: int,
) -> AuthorSummary:
    api_key = await get_api_key(db)
    if not api_key:
        raise ValueError("Hardcover API key is not configured")

    author_add_status.update(progress=5.0, message="Connecting to Hardcover...")
    client = HardcoverClient(api_key)
    usage_token = begin_api_usage_batch()
    try:
        logger.info("Add author requested from Hardcover: hardcover_id=%s", hardcover_id)
        author = await _prepare_author_from_hardcover(db, hardcover_id, client)

        author_add_status.update(progress=25.0, message=f"Fetching Hardcover catalog for {author.name}...")
        hc_books = await client.get_author_books(author.hardcover_id)
        canonical_books = [b for b in hc_books if b.is_canonical]
        valid_books = [b for b in canonical_books if _is_valid_title(b.title)]
        eligible_books = _deduplicate_books(valid_books)
        author.book_count_total = len(eligible_books)
        logger.info(
            "Importing Hardcover author %s (hc_id=%s): %d raw, %d canonical, %d valid, %d eligible",
            author.name,
            author.hardcover_id,
            len(hc_books),
            len(canonical_books),
            len(valid_books),
            len(eligible_books),
        )
        author_add_status.update(
            progress=35.0,
            message=f"Importing {len(eligible_books)} Hardcover book records for {author.name}...",
        )
        imported_book_ids: list[int] = []
        total_books = max(len(eligible_books), 1)
        for index, hc_book in enumerate(eligible_books, start=1):
            if index == 1 or index == len(eligible_books) or index % 10 == 0:
                author_add_status.update(
                    progress=35.0 + (index / total_books) * 35.0,
                    message=f"Importing book {index}/{len(eligible_books)}: {hc_book.title}",
                )
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

        author_add_status.update(progress=72.0, message="Saving imported catalog...")
        await db.commit()

        def enrichment_progress(stage: str, processed: int, total: int, title: str) -> None:
            phase_start = 74.0 if stage == "google" else 84.0
            phase_end = 84.0 if stage == "google" else 96.0
            label = "Google Books" if stage == "google" else "Open Library"
            author_add_status.update(
                progress=phase_start + (processed / max(total, 1)) * (phase_end - phase_start),
                message=f"Reconciling metadata with {label} {processed}/{total}: {title}",
            )

        author_add_status.update(progress=74.0, message="Reconciling imported metadata...")
        await enrich_imported_books_metadata(db, imported_book_ids, enrichment_progress)
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
        raise RuntimeError(f"Hardcover lookup failed: {exc}") from exc
    finally:
        clear_api_usage_batch(usage_token)
        await client.close()

    return await _build_author_summary(db, author)


async def _run_add_author_task(hardcover_id: int):
    try:
        async with async_session() as db:
            author = await _add_author_from_hardcover(db, hardcover_id)
    except Exception as exc:
        author_add_status.fail(str(exc))
        logger.exception("Add author from Hardcover failed: hardcover_id=%s", hardcover_id)
    else:
        author_add_status.complete(author)


@router.post("/add-from-hardcover")
async def add_author_from_hardcover(
    body: AuthorAddRequest,
    db: AsyncSession = Depends(get_db),
):
    if author_add_status.status == "adding":
        return {
            "status": "already_adding",
            "message": "An author import is already in progress",
            "add": author_add_status.to_dict(),
        }

    api_key = await get_api_key(db)
    if not api_key:
        raise HTTPException(status_code=400, detail="Hardcover API key is not configured")

    author_add_status.start(body.hardcover_id)
    client = HardcoverClient(api_key)
    usage_token = begin_api_usage_batch()
    try:
        author_add_status.update(progress=5.0, message="Connecting to Hardcover...")
        author = await _prepare_author_from_hardcover(db, body.hardcover_id, client)
        await flush_api_usage_batch(db)
        await db.commit()
        result = await db.execute(
            select(Author)
            .options(selectinload(Author.books))
            .where(Author.id == author.id)
        )
        author = result.scalar_one()
        author_summary = await _build_author_summary(db, author)
    except HardcoverLookupError as exc:
        await db.rollback()
        author_add_status.fail(f"Hardcover lookup failed: {exc}")
        raise HTTPException(status_code=502, detail=f"Hardcover lookup failed: {exc}") from exc
    except ValueError as exc:
        await db.rollback()
        author_add_status.fail(str(exc))
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        clear_api_usage_batch(usage_token)
        await client.close()

    asyncio.create_task(_run_add_author_task(body.hardcover_id))
    payload = author_summary.model_dump()
    payload.update({
        "status": "started",
        "message": "Author import started",
        "add": author_add_status.to_dict(),
    })
    return {
        **payload,
    }


@router.get("/add-from-hardcover/status")
async def get_add_author_status():
    return author_add_status.to_dict()


@router.post("/{author_id}/relink-hardcover")
async def relink_author_hardcover(
    author_id: int,
    body: AuthorRelinkRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Author).where(Author.id == author_id))
    author = result.scalar_one_or_none()
    if author is None:
        raise HTTPException(status_code=404, detail="Author not found")

    if author.hardcover_id == body.hardcover_id:
        return {
            "status": "already_linked",
            "message": "Author is already linked to the selected Hardcover match.",
            "hardcover_id": body.hardcover_id,
            "refresh": author_refresh_status.to_dict(),
        }

    existing_result = await db.execute(
        select(Author).where(
            Author.hardcover_id == body.hardcover_id,
            Author.id != author_id,
        )
    )
    existing_author = existing_result.scalar_one_or_none()
    if existing_author is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Hardcover author is already linked to local author '{existing_author.name}'",
        )

    api_key = await get_api_key(db)
    if not api_key:
        raise HTTPException(status_code=400, detail="Hardcover API key is not configured")

    client = HardcoverClient(api_key)
    usage_token = begin_api_usage_batch()
    try:
        logger.info(
            "Relink author requested: author_id=%s name=%r old_hardcover_id=%s new_hardcover_id=%s",
            author.id,
            author.name,
            author.hardcover_id,
            body.hardcover_id,
        )
        hc_author = await client.get_author(body.hardcover_id)
        if hc_author is None:
            raise HTTPException(status_code=404, detail="Hardcover author not found")

        # Repoint the existing author to the selected Hardcover profile. Linked
        # folders are left untouched so local library paths stay stable.
        author.name = hc_author.name
        author.hardcover_id = hc_author.id
        author.hardcover_slug = hc_author.slug
        author.bio = hc_author.bio
        author.last_synced_at = None
        if not author.manual_image_source:
            author.image_url = hc_author.image_url
        await db.commit()
    except HardcoverLookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"Hardcover lookup failed: {exc}") from exc
    finally:
        clear_api_usage_batch(usage_token)
        await client.close()

    started = trigger_author_refresh(author_id, mode="full")
    if not started:
        return {
            "status": "relinked_refresh_busy",
            "message": "Author relinked to the selected Hardcover match, but a refresh is already in progress. Run a full refresh once it finishes.",
            "hardcover_id": hc_author.id,
            "refresh": author_refresh_status.to_dict(),
        }

    return {
        "status": "started",
        "message": "Author relinked to the selected Hardcover match. Refreshing books...",
        "hardcover_id": hc_author.id,
        "refresh": author_refresh_status.to_dict(),
    }


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
async def refresh_author_route(
    author_id: int,
    mode: str = Query("full", pattern="^(full|new_releases)$"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Author.id).where(Author.id == author_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Author not found")

    started = trigger_author_refresh(author_id, mode=mode)
    if not started:
        return {
            "status": "already_refreshing",
            "message": "An author refresh is already in progress",
            "refresh": author_refresh_status.to_dict(),
        }

    return {"status": "started", "message": "Author refresh started", "refresh": author_refresh_status.to_dict()}


@router.get("/refresh/status")
async def get_author_refresh_status():
    return author_refresh_status.to_dict()


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


def _collect_current_author_local_files(author_directories: list[AuthorDirectory]) -> list[tuple[str, str, int | None, str | None]]:
    artifacts: dict[str, tuple[str, int | None, str | None]] = {}

    for directory in sorted(author_directories, key=lambda item: item.dir_path.lower()):
        author_root = BOOKS_DIR / directory.dir_path
        if not author_root.exists() or not author_root.is_dir():
            continue

        for entry in sorted(author_root.iterdir(), key=lambda item: item.name.lower()):
            if entry.name.startswith("."):
                continue

            if entry.is_file():
                file_format = _classify_standalone_file(entry)
                if file_format is None:
                    continue
                rel_path = str(entry.relative_to(BOOKS_DIR))
                artifacts.setdefault(rel_path, (entry.name, entry.stat().st_size, file_format))
                continue

            if not entry.is_dir():
                continue

            for rel_path, file_format in _collect_book_dir_artifacts(entry, BOOKS_DIR):
                source_path = BOOKS_DIR / rel_path
                file_size = source_path.stat().st_size if source_path.exists() and source_path.is_file() else None
                artifacts.setdefault(rel_path, (source_path.name, file_size, file_format))

    return [
        (file_path, file_name, file_size, file_format)
        for file_path, (file_name, file_size, file_format) in sorted(artifacts.items())
    ]


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
    visibility_settings = await get_book_visibility_settings(db)
    visible_filter = book_visibility_sql_filter(visibility_settings)
    visible_count = func.coalesce(func.sum(case((visible_filter, 1), else_=0)), 0)
    visible_owned_count = func.coalesce(
        func.sum(case((and_(visible_filter, Book.is_owned == True), 1), else_=0)),
        0,
    )
    author_columns = (
        Author.id,
        Author.name,
        Author.hardcover_id,
        Author.hardcover_slug,
        Author.bio,
        Author.image_url,
        Author.image_cached_path,
    )
    query = (
        select(
            *author_columns,
            visible_owned_count.label("book_count_local"),
            visible_count.label("book_count_total"),
        )
        .outerjoin(Book, Book.author_id == Author.id)
        .group_by(*author_columns)
        .having(visible_count > 0)
    )
    if search:
        query = query.where(Author.name.ilike(f"%{search}%"))
    result = await db.execute(query)
    summaries = [
        AuthorSummary(
            id=row.id,
            name=row.name,
            hardcover_id=row.hardcover_id,
            hardcover_slug=row.hardcover_slug,
            bio=row.bio,
            image_url=row.image_url,
            image_cached_path=row.image_cached_path,
            book_count_local=row.book_count_local,
            book_count_total=row.book_count_total,
        )
        for row in result.all()
    ]

    if sort == "name":
        summaries.sort(key=lambda author: author_sort_key(author.name))
    elif sort == "-name":
        summaries.sort(key=lambda author: author_sort_key(author.name), reverse=True)
    elif sort == "books":
        summaries.sort(key=lambda author: (author.book_count_total, author_sort_key(author.name)))
    elif sort == "-books":
        summaries.sort(key=lambda author: (author.book_count_total, author_sort_key(author.name)), reverse=True)
    elif sort == "owned":
        summaries.sort(key=lambda author: (author.book_count_local, author_sort_key(author.name)))
    elif sort == "-owned":
        summaries.sort(key=lambda author: (author.book_count_local, author_sort_key(author.name)), reverse=True)

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
    hidden_books_count = sum(1 for b in all_books if not is_book_visible(b, visibility_settings))
    visible_book_file_paths = {
        book_file.file_path
        for book in books
        for book_file in book.files
    }
    local_file_book_map = {
        book_file.file_path: book
        for book in all_books
        for book_file in book.files
    }
    unmatched_local_files = [
        UnmatchedLocalFile(
            file_path=file_path,
            file_name=file_name,
            file_size=file_size,
            file_format=file_format,
            linked_book_id=linked_book.id if linked_book else None,
            linked_book_title=linked_book.title if linked_book else None,
        )
        for file_path, file_name, file_size, file_format in _collect_current_author_local_files(author.author_directories)
        if file_path not in visible_book_file_paths
        for linked_book in [local_file_book_map.get(file_path)]
    ]

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
                title=effective_title(book),
                position=bs.position,
                is_owned=book.is_owned,
                cover_image_cached_path=book.cover_image_cached_path,
            ))

        books_out.append(BookInAuthor(
            id=book.id,
            title=effective_title(book),
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
        book_count_hidden=hidden_books_count,
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
        unmatched_local_files=unmatched_local_files,
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
