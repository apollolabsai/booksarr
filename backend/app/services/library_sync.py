import asyncio
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.config import BOOKS_DIR
from backend.app.database import async_session
from backend.app.models import Author, Book, BookFile, BookSeries, Series, Setting
from backend.app.services.scanner import scan_library, extract_best_metadata, _clean_author_text
from backend.app.services.hardcover import HardcoverClient, HardcoverLookupError
from backend.app.services.matcher import titles_match
from backend.app.services.image_cache import (
    cache_author_image,
    cache_best_local_cover,
    download_image_bytes,
    cache_cover_data,
    get_cached_cover_dimensions,
    get_cached_cover_height,
    get_cached_cover_aspect_ratio,
)
from backend.app.services.openlibrary import OpenLibraryClient, OLBook
from backend.app.services.wikimedia import WikimediaClient
from backend.app.utils.hardcover_metadata import get_book_category_name, get_literary_type_name
from backend.app.utils.book_visibility import (
    get_book_visibility_settings,
    get_hidden_category,
    is_book_visible,
)
from backend.app.services.google_books import (
    GoogleBooksClient,
    GBook,
    GoogleBooksLookupError,
    GoogleBooksThrottledError,
)
from backend.app.utils.epub_cover import get_image_dimensions
from backend.app.utils.api_usage import begin_api_usage_batch, clear_api_usage_batch, flush_api_usage_batch
from backend.app.utils.isbn import normalize_isbn, normalized_valid_isbn, extract_isbn_variants

logger = logging.getLogger("booksarr.sync")

# Articles to strip when comparing titles for deduplication
_ARTICLE_RE = re.compile(r"^(a|an|the)\s+", re.IGNORECASE)

# Cover height threshold — stop looking for better covers once met
COVER_HEIGHT_THRESHOLD = 2000
SUFFICIENT_COVER_HEIGHT = 500
TARGET_COVER_RATIO = 2 / 3


def _is_valid_title(title: str) -> bool:
    """Check if a title is usable — has real Latin-script content.

    Filters out:
    - Non-Latin scripts (CJK, Arabic, Cyrillic, etc.)
    - Corrupted titles that are mostly question marks
    """
    if not title:
        return False

    # Reject titles that are mostly question marks (corrupted data from API)
    alpha_or_q = sum(1 for ch in title if ch.isalpha() or ch == "?")
    if alpha_or_q > 0:
        q_ratio = title.count("?") / alpha_or_q
        if q_ratio > 0.3:
            return False

    latin_count = 0
    letter_count = 0
    for ch in title:
        if unicodedata.category(ch).startswith("L"):  # Any letter
            letter_count += 1
            script = unicodedata.name(ch, "").split(" ")[0]
            if script in ("LATIN", "DIGIT"):
                latin_count += 1
    if letter_count == 0:
        return True  # No letters (e.g. "1984") — allow
    return (latin_count / letter_count) > 0.5


def _normalize_title(title: str) -> str:
    """Normalize a title for dedup comparison: lowercase, strip articles and punctuation."""
    t = title.lower().strip()
    t = _ARTICLE_RE.sub("", t)
    t = re.sub(r"[^\w\s]", "", t)  # strip punctuation
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _metadata_score(book) -> tuple:
    """Score a Hardcover book by metadata richness. Higher is better."""
    return (
        book.users_count or 0,
        1 if book.rating and book.rating > 0 else 0,
        1 if book.description else 0,
        book.pages or 0,
        book.rating or 0,
    )


def _deduplicate_books(books: list) -> list:
    """Deduplicate books using three strategies:
    1. Normalized title match (catches 'A Time for Mercy' vs 'Time for Mercy')
    2. Same series + same position (catches 'The Exchange' vs 'The Exchange After the Firm')
    3. Title prefix — one title starts with another (catches 'Camino Ghosts' vs
       'Camino Ghosts The New Thrilling Novel from...')
    In all cases, the book with the best metadata (users_count, rating, etc.) wins.
    """
    total_removed = 0

    # Pass 1: Deduplicate by normalized title
    title_groups: dict[str, list] = {}
    for book in books:
        key = _normalize_title(book.title)
        title_groups.setdefault(key, []).append(book)

    after_title_dedup = []
    for key, group in title_groups.items():
        if len(group) == 1:
            after_title_dedup.append(group[0])
        else:
            group.sort(key=_metadata_score, reverse=True)
            after_title_dedup.append(group[0])
            total_removed += len(group) - 1
            logger.debug(
                "Dedup (title): kept '%s' (hc=%d, users=%d), dropped %d variant(s)",
                group[0].title, group[0].id, group[0].users_count, len(group) - 1,
            )

    # Pass 2: Deduplicate by series + position
    series_groups: dict[tuple, list] = {}
    no_series = []
    for book in after_title_dedup:
        if book.series_refs:
            for sr in book.series_refs:
                if sr.position is not None:
                    key = (sr.id, sr.position)
                    series_groups.setdefault(key, []).append(book)
                    break
            else:
                no_series.append(book)
        else:
            no_series.append(book)

    seen_ids = set()
    after_series_dedup = list(no_series)
    for key, group in series_groups.items():
        if len(group) == 1:
            if group[0].id not in seen_ids:
                after_series_dedup.append(group[0])
                seen_ids.add(group[0].id)
        else:
            group.sort(key=_metadata_score, reverse=True)
            if group[0].id not in seen_ids:
                after_series_dedup.append(group[0])
                seen_ids.add(group[0].id)
            total_removed += len(group) - 1
            logger.debug(
                "Dedup (series): kept '%s' (hc=%d, users=%d), dropped %d variant(s) at series %s pos %s",
                group[0].title, group[0].id, group[0].users_count,
                len(group) - 1, key[0], key[1],
            )

    # Pass 3: Title prefix — if one normalized title starts with another, they're dupes
    after_series_dedup.sort(key=lambda b: len(_normalize_title(b.title)))
    result = []
    for book in after_series_dedup:
        norm = _normalize_title(book.title)
        is_dup = False
        for kept in result:
            kept_norm = _normalize_title(kept.title)
            # Check if the shorter title is a prefix of the longer one
            if norm.startswith(kept_norm) or kept_norm.startswith(norm):
                # Keep the one with better metadata
                if _metadata_score(book) > _metadata_score(kept):
                    result.remove(kept)
                    result.append(book)
                    logger.debug(
                        "Dedup (prefix): replaced '%s' with '%s' (better metadata)",
                        kept.title, book.title,
                    )
                else:
                    logger.debug(
                        "Dedup (prefix): kept '%s', dropped '%s'",
                        kept.title, book.title,
                    )
                is_dup = True
                total_removed += 1
                break
        if not is_dup:
            result.append(book)

    if total_removed:
        logger.info("Deduplicated %d book(s) total", total_removed)
    return result


def _extract_ol_cover_id(cover_url: str | None) -> int | None:
    """Extract the OL cover ID from a URL like .../id/12345-L.jpg."""
    if not cover_url:
        return None
    # URL format: https://covers.openlibrary.org/b/id/12345-L.jpg
    try:
        part = cover_url.rsplit("/", 1)[-1]  # "12345-L.jpg"
        return int(part.split("-")[0])
    except (ValueError, IndexError):
        return None


def _get_cached_cover_source(cached_path: str | None) -> str | None:
    if not cached_path:
        return None

    filename = cached_path.rsplit("/", 1)[-1]
    if filename.startswith("local_"):
        return "local"
    if filename.startswith("hc_") or filename.startswith("hardcover_"):
        return "hardcover"
    if filename.startswith("google_image_"):
        return "google_image"
    if filename.startswith("google_"):
        return "google"
    if filename.startswith("openlibrary_"):
        return "openlibrary"
    if filename.startswith("cover_"):
        return "legacy_remote"
    return "unknown"


def _cover_ratio_distance(ratio: float | None) -> float:
    if ratio is None or ratio <= 0:
        return float("inf")
    return abs(ratio - TARGET_COVER_RATIO)


def _get_author_image_source(url: str | None) -> str:
    normalized = (url or "").lower()
    if "openlibrary.org" in normalized:
        return "ol"
    if "wikimedia.org" in normalized or "wikipedia.org" in normalized:
        return "wm"
    return "hc"


def _measure_cover_data(data: bytes) -> tuple[int, float | None]:
    dims = get_image_dimensions(data)
    if not dims or dims[0] <= 0 or dims[1] <= 0:
        return 0, None
    width, height = dims
    return height, width / height


def _cover_source_rank(source: str | None) -> int:
    ranks = {
        "local": 4,
        "hardcover": 3,
        "google": 2,
        "openlibrary": 1,
        "legacy_remote": 0,
        "unknown": 0,
        None: 0,
    }
    return ranks.get(source, 0)


def _cover_source_label(source: str) -> str:
    labels = {
        "local": "Local",
        "hardcover": "Hardcover",
        "google": "Google Books",
        "openlibrary": "Open Library",
        "google_image": "Google Images",
    }
    return labels.get(source, source.title())


def _cover_ratio_delta_percent(ratio: float | None) -> float | None:
    if ratio is None or ratio <= 0:
        return None
    return round((abs(ratio - TARGET_COVER_RATIO) / TARGET_COVER_RATIO) * 100, 1)


def _get_book_source_cover_url(book: Book, source: str) -> str | None:
    if source == "hardcover":
        return book.cover_image_url
    if source == "google":
        return book.google_cover_url
    if source == "openlibrary":
        return book.ol_cover_url
    return None


def _get_local_cached_cover_path(book: Book) -> str | None:
    current_source = _get_cached_cover_source(book.cover_image_cached_path)
    if current_source == "local" and get_cached_cover_dimensions(book.cover_image_cached_path):
        return book.cover_image_cached_path

    if not book.files:
        return None

    book_file = book.files[0]
    epub_path = BOOKS_DIR / book_file.file_path if book_file.file_format == "epub" else None
    return cache_best_local_cover(
        book_file.local_cover_path,
        epub_path,
        book.id,
        existing_cached_path=None,
    )


async def get_book_cover_options(book: Book) -> list[dict]:
    options: list[dict] = []
    current_source = _get_cached_cover_source(book.cover_image_cached_path)

    local_cached_path = _get_local_cached_cover_path(book)
    if local_cached_path:
        dims = get_cached_cover_dimensions(local_cached_path)
        ratio = get_cached_cover_aspect_ratio(local_cached_path)
        options.append({
            "key": "local",
            "source": "local",
            "label": _cover_source_label("local"),
            "image_url": None,
            "cached_path": local_cached_path,
            "width": dims[0] if dims else None,
            "height": dims[1] if dims else None,
            "aspect_ratio": ratio,
            "ratio_delta_percent": _cover_ratio_delta_percent(ratio),
            "is_current": current_source == "local",
            "is_manual": book.manual_cover_source == "local",
        })

    for source in ("hardcover", "google", "openlibrary"):
        image_url = _get_book_source_cover_url(book, source)
        if not image_url:
            continue
        data = await download_image_bytes(image_url)
        if not data:
            continue
        dims = get_image_dimensions(data)
        ratio = (dims[0] / dims[1]) if dims and dims[0] > 0 and dims[1] > 0 else None
        options.append({
            "key": source,
            "source": source,
            "label": _cover_source_label(source),
            "image_url": image_url,
            "cached_path": None,
            "width": dims[0] if dims else None,
            "height": dims[1] if dims else None,
            "aspect_ratio": ratio,
            "ratio_delta_percent": _cover_ratio_delta_percent(ratio),
            "is_current": current_source == source,
            "is_manual": book.manual_cover_source == source,
        })

    return options


async def _apply_cover_source(book: Book, source: str, *, override_url: str | None = None) -> bool:
    if source == "local":
        local_cached_path = _get_local_cached_cover_path(book)
        if not local_cached_path:
            return False
        book.cover_image_cached_path = local_cached_path
        return True

    image_url = override_url or _get_book_source_cover_url(book, source)
    if not image_url:
        return False

    data = await download_image_bytes(image_url)
    if not data:
        return False

    cached_path = cache_cover_data(data, book.id, source)
    if not cached_path:
        return False

    book.cover_image_cached_path = cached_path
    return True


async def apply_manual_cover_selection(book: Book) -> bool:
    source = (book.manual_cover_source or "").strip().lower()
    if source not in {"local", "hardcover", "google", "openlibrary", "google_image"}:
        return False

    current_source = _get_cached_cover_source(book.cover_image_cached_path)
    if current_source == source and get_cached_cover_dimensions(book.cover_image_cached_path):
        return True

    override_url = book.manual_cover_url if source != "local" else None
    return await _apply_cover_source(book, source, override_url=override_url)


async def set_book_cover_selection(
    book: Book, source: str, *, url: str | None = None,
) -> bool:
    normalized_source = source.strip().lower()
    valid_sources = {"local", "hardcover", "google", "openlibrary", "google_image"}
    if normalized_source not in valid_sources:
        return False

    if normalized_source == "google_image":
        if not url:
            return False
        override_url = url
    elif normalized_source == "local":
        override_url = None
    else:
        override_url = _get_book_source_cover_url(book, normalized_source)
        if not override_url:
            return False

    applied = await _apply_cover_source(book, normalized_source, override_url=override_url)
    if not applied:
        return False

    book.manual_cover_source = normalized_source
    book.manual_cover_url = override_url
    return True


def _should_replace_cover(
    *,
    current_source: str | None,
    current_height: int,
    current_ratio: float | None,
    new_source: str | None,
    new_height: int,
    new_ratio: float | None,
) -> bool:
    if new_height <= 0:
        return False
    if current_height <= 0:
        return True

    current_sufficient = current_height >= SUFFICIENT_COVER_HEIGHT
    new_sufficient = new_height >= SUFFICIENT_COVER_HEIGHT

    if new_sufficient and not current_sufficient:
        return True
    if current_sufficient and not new_sufficient:
        return False

    if new_sufficient and current_sufficient:
        current_distance = _cover_ratio_distance(current_ratio)
        new_distance = _cover_ratio_distance(new_ratio)
        current_rank = _cover_source_rank(current_source)
        new_rank = _cover_source_rank(new_source)

        # Allow a meaningfully better source (for example Hardcover replacing
        # Open Library) to win if the ratio penalty is modest and resolution is
        # not worse.
        if new_rank >= current_rank + 2:
            if new_height >= current_height and new_distance <= current_distance + 0.08:
                return True

        # Do not let a lower-quality remote source replace a good current cover
        # unless the ratio improvement is material and the resolution is not worse.
        if current_rank > new_rank:
            if new_distance + 0.06 < current_distance and new_height >= int(current_height * 0.95):
                return True
            return False

        if new_distance + 0.01 < current_distance:
            return True
        if current_distance + 0.01 < new_distance:
            return False

    return new_height > current_height


def _preferred_google_isbns(book: Book) -> list[str]:
    local_file_isbns = [
        normalized_valid_isbn(book_file.opf_isbn)
        for book_file in sorted(book.files, key=lambda bf: bf.id)
    ]
    ordered = [
        *local_file_isbns,
        book.isbn,
        book.hardcover_isbn_13,
        book.hardcover_isbn_10,
        book.ol_isbn_13,
        book.ol_isbn_10,
    ]
    seen: set[str] = set()
    result: list[str] = []
    for value in ordered:
        if not value:
            continue
        normalized = value.replace("-", "").replace(" ", "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _reparse_book_files(book: Book) -> tuple[str | None, str | None, str | None, str | None]:
    primary_title = None
    primary_isbn = None
    primary_publisher = None
    primary_description = None

    for book_file in sorted(book.files, key=lambda bf: bf.id):
        ebook_path = BOOKS_DIR / book_file.file_path
        path_parts = book_file.file_path.split("/")
        fallback_author = path_parts[0] if path_parts else (book_file.opf_author or "")
        fallback_book_dir = path_parts[1] if len(path_parts) > 1 else book_file.file_name

        if not ebook_path.exists():
            continue

        opf = extract_best_metadata(ebook_path, fallback_author, fallback_book_dir)
        book_file.opf_title = opf.title or None
        book_file.opf_author = opf.author or fallback_author
        book_file.opf_isbn = opf.isbn or None
        book_file.opf_series = opf.series or None
        book_file.opf_series_index = opf.series_index
        book_file.opf_publisher = opf.publisher or None
        book_file.opf_description = opf.description or None
        book_file.last_scanned_at = datetime.utcnow()

        if primary_title is None and book_file.opf_title:
            primary_title = book_file.opf_title
        if primary_isbn is None:
            primary_isbn = normalized_valid_isbn(book_file.opf_isbn)
        if primary_publisher is None and book_file.opf_publisher:
            primary_publisher = book_file.opf_publisher
        if primary_description is None and book_file.opf_description:
            primary_description = book_file.opf_description

    return primary_title, primary_isbn, primary_publisher, primary_description


def _linked_book_matches_local_metadata(
    book: Book,
    local_title: str | None,
    local_isbn: str | None,
) -> bool:
    if local_title and not titles_match(local_title, book.title):
        return False

    normalized_local_isbn = normalize_isbn(local_isbn)
    if normalized_local_isbn:
        trusted_book_isbns = (
            {
                normalize_isbn(book.hardcover_isbn_13),
                normalize_isbn(book.hardcover_isbn_10),
            }
            if book.hardcover_id
            else {normalize_isbn(book.isbn)}
        )
        trusted_book_isbns.discard("")
        if trusted_book_isbns and normalized_local_isbn in trusted_book_isbns:
            return True

    if local_title:
        return True

    if not normalized_local_isbn and not local_title:
        return True

    return False


async def _count_local_match_candidates(db: AsyncSession) -> int:
    result = await db.execute(
        select(BookFile).options(selectinload(BookFile.book))
    )
    count = 0
    for book_file in result.scalars().all():
        if book_file.book_id is None or (book_file.book and book_file.book.hardcover_id is None):
            count += 1
            continue
        if book_file.book and not _linked_book_matches_local_metadata(
            book_file.book,
            book_file.opf_title,
            book_file.opf_isbn,
        ):
            count += 1
    return count


async def _count_authors_needing_images(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count(Author.id)).where(
            (Author.image_cached_path.is_(None)) | (Author.image_cached_path == "")
        )
    )
    return result.scalar() or 0


async def _repair_local_file_links(
    db: AsyncSession,
    author: Author | None = None,
    file_paths: set[str] | None = None,
) -> tuple[int, int, int]:
    result = await db.execute(
        select(BookFile).options(selectinload(BookFile.book))
    )
    candidate_files = [
        bf for bf in result.scalars().all()
        if (
            bf.book_id is None
            or (bf.book and bf.book.hardcover_id is None)
            or (bf.book and not _linked_book_matches_local_metadata(bf.book, bf.opf_title, bf.opf_isbn))
        )
    ]
    if file_paths is not None:
        candidate_files = [bf for bf in candidate_files if bf.file_path in file_paths]
    if author is not None:
        author_dir_paths = {directory.dir_path for directory in author.author_directories}
        candidate_files = [
            bf for bf in candidate_files
            if (
                (bf.book and bf.book.author_id == author.id)
                or ((bf.opf_author or "").strip() == author.name)
                or (bf.file_path and bf.file_path.split("/")[0] in author_dir_paths)
                or (
                    bf.file_path
                    and _clean_author_text(bf.file_path.split("/")[0]) == author.name
                )
            )
        ]

    matched_count = 0
    repaired_count = 0
    books_added = 0

    for bf in candidate_files:
        current_book = bf.book
        ebook_path = BOOKS_DIR / bf.file_path
        path_parts = bf.file_path.split("/")
        fallback_author = path_parts[0] if path_parts else (bf.opf_author or "")
        fallback_book_dir = path_parts[1] if len(path_parts) > 1 else (current_book.title if current_book else bf.file_name)

        if ebook_path.exists():
            opf = extract_best_metadata(ebook_path, fallback_author, fallback_book_dir)
            bf.opf_title = opf.title or None
            bf.opf_author = opf.author or fallback_author
            bf.opf_isbn = opf.isbn or None
            bf.opf_series = opf.series or None
            bf.opf_series_index = opf.series_index
            bf.opf_publisher = opf.publisher or None
            bf.opf_description = opf.description or None

        author_result = await db.execute(
            select(Author).where(Author.name == bf.opf_author)
        )
        author = author_result.scalar_one_or_none()
        if not author:
            continue

        books_result = await db.execute(
            select(Book).where(Book.author_id == author.id)
        )
        author_books = sorted(
            books_result.scalars().all(),
            key=lambda candidate: (candidate.hardcover_id is None, candidate.id),
        )
        candidate_books = [
            book for book in author_books
            if not current_book or book.id != current_book.id
        ]

        matched_book = None

        if bf.opf_isbn:
            target_isbn = normalize_isbn(bf.opf_isbn)
            for book in candidate_books:
                book_isbns = (
                    [
                        normalize_isbn(book.hardcover_isbn_13),
                        normalize_isbn(book.hardcover_isbn_10),
                    ]
                    if book.hardcover_id
                    else [normalize_isbn(book.isbn)]
                )
                if target_isbn and target_isbn in {value for value in book_isbns if value}:
                    matched_book = book
                    break

        if not matched_book and bf.opf_title:
            for book in candidate_books:
                if titles_match(bf.opf_title, book.title):
                    matched_book = book
                    break

        if matched_book:
            previous_book_id = bf.book_id
            bf.book = matched_book
            matched_book.is_owned = True
            if bf.opf_isbn and (
                not matched_book.isbn
                or (previous_book_id and previous_book_id != matched_book.id)
            ):
                matched_book.isbn = bf.opf_isbn
                if matched_book.google_id == "_none":
                    matched_book.google_id = None
                if matched_book.ol_edition_key == "_none":
                    matched_book.ol_edition_key = None
                matched_book.publish_date_checked_at = None
            matched_count += 1
            if previous_book_id and previous_book_id != matched_book.id:
                repaired_count += 1
                previous_result = await db.execute(
                    select(Book).where(Book.id == previous_book_id)
                )
                previous_book = previous_result.scalar_one_or_none()
                if previous_book and not previous_book.hardcover_id:
                    remaining = await db.execute(
                        select(func.count(BookFile.id)).where(
                            BookFile.book_id == previous_book_id,
                            BookFile.id != bf.id,
                        )
                    )
                    if (remaining.scalar() or 0) == 0:
                        await db.delete(previous_book)
        else:
            if current_book and not current_book.hardcover_id:
                current_book.title = bf.opf_title or current_book.title
                current_book.author_id = author.id
                current_book.isbn = bf.opf_isbn or current_book.isbn
                current_book.publisher = bf.opf_publisher or current_book.publisher
                current_book.description = bf.opf_description or current_book.description
                current_book.is_owned = True
            else:
                local_book = Book(
                    title=bf.opf_title or bf.file_name,
                    author_id=author.id,
                    isbn=bf.opf_isbn,
                    publisher=bf.opf_publisher,
                    description=bf.opf_description,
                    is_owned=True,
                )
                db.add(local_book)
                await db.flush()
                bf.book = local_book
                books_added += 1

    await db.commit()
    if candidate_files:
        logger.info(
            "Matched %d/%d candidate file(s); repaired %d existing local link(s)",
            matched_count,
            len(candidate_files),
            repaired_count,
        )
    return matched_count, repaired_count, books_added


async def refresh_imported_library_file(moved_path) -> bool:
    try:
        relative_path = str(moved_path.relative_to(BOOKS_DIR))
    except Exception:
        logger.warning("Imported file is not inside BOOKS_DIR; skipping targeted refresh: %s", moved_path)
        return False

    async with async_session() as db:
        await scan_library(db, BOOKS_DIR)
        matched_count, repaired_count, books_added = await _repair_local_file_links(
            db,
            file_paths={relative_path},
        )

        result = await db.execute(
            select(BookFile)
            .options(selectinload(BookFile.book))
            .where(BookFile.file_path == relative_path)
        )
        book_file = result.scalar_one_or_none()
        if book_file is None:
            logger.warning("Targeted import refresh could not find scanned file: %s", relative_path)
            return False

        linked_book = book_file.book
        logger.info(
            "Targeted import refresh complete: file=%s matched=%d repaired=%d local_books_added=%d linked_book_id=%s owned=%s",
            relative_path,
            matched_count,
            repaired_count,
            books_added,
            linked_book.id if linked_book else None,
            linked_book.is_owned if linked_book else None,
        )
        return linked_book is not None and bool(linked_book.is_owned)


async def _sync_author_hardcover_catalog(
    db: AsyncSession,
    author: Author,
    client: HardcoverClient,
) -> tuple[int, int]:
    books_added = 0
    books_removed = 0

    if not author.hardcover_id:
        hc_author = await client.search_author(author.name)
        if not hc_author:
            logger.info("No Hardcover author match found during author refresh: %s", author.name)
            return 0, 0
        author.hardcover_id = hc_author.id
        author.hardcover_slug = hc_author.slug
        author.bio = hc_author.bio
        if not author.manual_image_source:
            author.image_url = hc_author.image_url

    hc_books = await client.get_author_books(author.hardcover_id)
    canonical_books = [b for b in hc_books if b.is_canonical]
    valid_books = [b for b in canonical_books if _is_valid_title(b.title)]
    eligible_books = _deduplicate_books(valid_books)
    eligible_hardcover_ids = {book.id for book in eligible_books}
    author.book_count_total = len(eligible_books)

    existing_author_books_result = await db.execute(
        select(Book)
        .where(Book.author_id == author.id, Book.hardcover_id.is_not(None))
        .options(selectinload(Book.files), selectinload(Book.book_series))
    )
    existing_author_books = existing_author_books_result.scalars().all()
    stale_books = [
        book for book in existing_author_books
        if book.hardcover_id and book.hardcover_id not in eligible_hardcover_ids
    ]

    for stale_book in stale_books:
        if stale_book.files or stale_book.is_owned:
            logger.warning(
                "Skipping stale Hardcover book cleanup because the book has local ownership data: book_id=%s title=%r author=%r files=%s is_owned=%s hardcover_id=%s",
                stale_book.id,
                stale_book.title,
                author.name,
                len(stale_book.files),
                stale_book.is_owned,
                stale_book.hardcover_id,
            )
            continue

        for book_series in list(stale_book.book_series):
            await db.delete(book_series)
        await db.delete(stale_book)
        books_removed += 1
        logger.info(
            "Removed stale Hardcover book from author during refresh: book_id=%s title=%r author=%r hardcover_id=%s",
            stale_book.id,
            stale_book.title,
            author.name,
            stale_book.hardcover_id,
        )

    for hc_book in eligible_books:
        existing = await db.execute(select(Book).where(Book.hardcover_id == hc_book.id))
        book = existing.scalar_one_or_none()
        tags_json = json.dumps(hc_book.tags) if hc_book.tags else None

        if book:
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
            books_added += 1

        for sr in hc_book.series_refs:
            series = await _get_or_create_series(db, sr.id, sr.name)
            existing_bs = await db.execute(
                select(BookSeries).where(
                    BookSeries.book_id == book.id,
                    BookSeries.series_id == series.id,
                )
            )
            if not existing_bs.scalar_one_or_none():
                db.add(BookSeries(
                    book_id=book.id,
                    series_id=series.id,
                    position=sr.position,
                ))

    author.last_synced_at = datetime.utcnow()
    return books_added, books_removed


class ScanStatus:
    def __init__(self):
        self.status: str = "idle"
        self.progress: float = 0.0
        self.message: str = ""

    def to_dict(self) -> dict:
        return {"status": self.status, "progress": self.progress, "message": self.message}


scan_status = ScanStatus()


@dataclass
class SourceRunSummary:
    lookups_attempted: int = 0
    matched: int = 0
    failed: int = 0
    cached: int = 0
    deferred: int = 0
    failure_reasons: dict[str, int] = field(default_factory=dict)

    def record_match(self, count: int = 1):
        self.lookups_attempted += count
        self.matched += count

    def record_failure(self, reason: str, count: int = 1, attempted: bool = True):
        if attempted:
            self.lookups_attempted += count
        self.failed += count
        self.failure_reasons[reason] = self.failure_reasons.get(reason, 0) + count

    def record_cached(self, count: int = 1):
        self.cached += count

    def record_deferred(self, reason: str, count: int = 1):
        self.deferred += count
        self.failure_reasons[reason] = self.failure_reasons.get(reason, 0) + count

    def to_dict(self) -> dict:
        return {
            "lookups_attempted": self.lookups_attempted,
            "matched": self.matched,
            "failed": self.failed,
            "cached": self.cached,
            "deferred": self.deferred,
            "failure_reasons": dict(sorted(self.failure_reasons.items())),
        }


@dataclass
class ScanRunSummary:
    mode: str
    started_at: str
    status: str = "completed"
    message: str = ""
    completed_at: str | None = None
    files_total: int = 0
    files_new: int = 0
    files_deleted: int = 0
    files_unchanged: int = 0
    owned_books_found: int = 0
    authors_added: int = 0
    books_added: int = 0
    books_hidden: int = 0
    hidden_by_category: list[dict[str, str | int]] = field(default_factory=list)
    hardcover: SourceRunSummary = field(default_factory=SourceRunSummary)
    google: SourceRunSummary = field(default_factory=SourceRunSummary)
    openlibrary: SourceRunSummary = field(default_factory=SourceRunSummary)
    wikimedia: SourceRunSummary = field(default_factory=SourceRunSummary)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "mode": self.mode,
            "message": self.message,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "files_total": self.files_total,
            "files_new": self.files_new,
            "files_deleted": self.files_deleted,
            "files_unchanged": self.files_unchanged,
            "owned_books_found": self.owned_books_found,
            "authors_added": self.authors_added,
            "books_added": self.books_added,
            "books_hidden": self.books_hidden,
            "hidden_by_category": self.hidden_by_category,
            "hardcover": self.hardcover.to_dict(),
            "google": self.google.to_dict(),
            "openlibrary": self.openlibrary.to_dict(),
            "wikimedia": self.wikimedia.to_dict(),
        }


async def get_api_key(db: AsyncSession) -> str:
    """Get Hardcover API key from env var (via config) or database settings."""
    from backend.app.config import HARDCOVER_API_KEY
    if HARDCOVER_API_KEY:
        return HARDCOVER_API_KEY

    result = await db.execute(select(Setting).where(Setting.key == "hardcover_api_key"))
    setting = result.scalar_one_or_none()
    return setting.value if setting else ""


async def get_google_api_key(db: AsyncSession) -> str:
    """Get Google Books API key from env var or database settings."""
    from backend.app.config import GOOGLE_BOOKS_API_KEY
    if GOOGLE_BOOKS_API_KEY:
        return GOOGLE_BOOKS_API_KEY

    result = await db.execute(select(Setting).where(Setting.key == "google_books_api_key"))
    setting = result.scalar_one_or_none()
    return setting.value if setting else ""


def _author_needs_hardcover_lookup(author: Author) -> bool:
    author_has_manual_image = bool(author.manual_image_source and author.manual_image_url)
    author_needs_cached_image = not author.image_cached_path
    return (
        not author.hardcover_id
        or (
            author.hardcover_id
            and author_needs_cached_image
            and not author.image_url
            and not author_has_manual_image
        )
    )


def _author_needs_hardcover_books_sync(
    author: Author,
    force: bool,
    authors_with_new_files: set[str],
) -> bool:
    if not author.hardcover_id:
        return False
    if force:
        return True
    if not author.last_synced_at:
        return True
    if author.name in authors_with_new_files:
        return True
    return False


async def run_full_sync(force: bool = False):
    """Run a library sync. Incremental by default; force=True refreshes all authors."""
    if scan_status.status == "scanning":
        return

    usage_batch_token = begin_api_usage_batch()
    summary = ScanRunSummary(
        mode="full_refresh" if force else "scan_library",
        started_at=_now_iso(),
    )
    scan_status.status = "scanning"
    scan_status.progress = 0.0
    scan_status.message = "Starting scan..."

    try:
        async with async_session() as db:
            # Phase 1: Fast filesystem change detection
            scan_status.message = "Scanning filesystem..."
            scan_status.progress = 5.0
            scan_result = await scan_library(db, BOOKS_DIR)
            summary.files_total = scan_result.total_files
            summary.files_new = len(scan_result.new_files)
            summary.files_deleted = len(scan_result.deleted_files)
            summary.files_unchanged = scan_result.unchanged_files
            summary.authors_added = len(scan_result.new_author_names)
            logger.info(
                "Scan result: %d new, %d deleted, %d unchanged, new authors: %s",
                len(scan_result.new_files), len(scan_result.deleted_files),
                scan_result.unchanged_files,
                scan_result.new_author_names or "(none)",
            )
            scan_status.progress = 20.0

            # If no changes and not forced, we can skip Hardcover phases
            has_changes = bool(scan_result.new_files or scan_result.deleted_files)
            repair_candidates = await _count_local_match_candidates(db)
            author_image_candidates = await _count_authors_needing_images(db)
            if not has_changes and not force and repair_candidates == 0 and author_image_candidates == 0:
                logger.info("No filesystem changes detected — skipping Hardcover sync")
                scan_status.message = "No changes detected."
                scan_status.progress = 100.0
                scan_status.status = "idle"
                await flush_api_usage_batch(db)
                await _update_last_scan(db)
                await _finalize_scan_summary(
                    db,
                    summary,
                    message="No changes detected.",
                )
                return
            if not has_changes and not force and (repair_candidates > 0 or author_image_candidates > 0):
                logger.info(
                    "No filesystem changes detected, but %d local file link(s) need repair and %d author image(s) need refresh",
                    repair_candidates,
                    author_image_candidates,
                )

            # Get API key
            api_key = await get_api_key(db)
            if not api_key:
                if repair_candidates > 0:
                    scan_status.message = "Repairing local file matches..."
                    matched_count, repaired_count, new_local_books = await _repair_local_file_links(db)
                    summary.books_added += new_local_books
                    logger.info(
                        "Local-only repair without Hardcover API key: matched %d candidate file(s), repaired %d link(s)",
                        matched_count,
                        repaired_count,
                    )
                scan_status.message = "No Hardcover API key configured. Scan complete (local only)."
                scan_status.progress = 100.0
                scan_status.status = "idle"
                await flush_api_usage_batch(db)
                await _update_last_scan(db)
                summary.message = "No Hardcover API key configured. Scan complete (local only)."
                summary.owned_books_found = await _count_owned_books(db)
                await _finalize_scan_summary(db, summary)
                return

            client = HardcoverClient(api_key)
            ol_client = OpenLibraryClient()
            wikimedia_client = WikimediaClient()
            try:
                hardcover_throttled = False
                # Phase 2: Match new authors to Hardcover
                scan_status.message = "Matching authors to Hardcover..."
                result = await db.execute(select(Author))
                authors = result.scalars().all()
                total_authors = len(authors)

                new_author_count = 0
                books_added = 0
                for i, author in enumerate(authors):
                    author_has_manual_image = bool(author.manual_image_source and author.manual_image_url)
                    author_needs_cached_image = not author.image_cached_path
                    if hardcover_throttled:
                        progress = 20.0 + (30.0 * (i + 1) / max(total_authors, 1))
                        scan_status.progress = progress
                        continue
                    if not author.hardcover_id:
                        new_author_count += 1
                        scan_status.message = f"Looking up author: {author.name}"
                        try:
                            hc_author = await client.search_author(author.name)
                        except HardcoverLookupError as e:
                            summary.hardcover.record_failure(e.reason)
                            if e.reason == "throttled":
                                hardcover_throttled = True
                                remaining = sum(
                                    1 for remaining_author in authors[i + 1:]
                                    if _author_needs_hardcover_lookup(remaining_author)
                                )
                                if remaining:
                                    summary.hardcover.record_deferred("throttled", remaining)
                                logger.warning(
                                    "Hardcover throttled during author matching at %r; "
                                    "deferring %d remaining author lookup(s) for this run",
                                    author.name,
                                    remaining,
                                )
                                scan_status.message = "Hardcover throttled; deferring remaining Hardcover author lookups..."
                                continue
                            raise
                        if hc_author:
                            summary.hardcover.record_match()
                            author.hardcover_id = hc_author.id
                            author.hardcover_slug = hc_author.slug
                            author.bio = hc_author.bio
                            if not author_has_manual_image:
                                author.image_url = hc_author.image_url
                        else:
                            summary.hardcover.record_failure("no_result")
                    elif author_needs_cached_image and not author.image_url:
                        try:
                            hc_author = await client.search_author(author.name)
                        except HardcoverLookupError as e:
                            summary.hardcover.record_failure(e.reason)
                            if e.reason == "throttled":
                                hardcover_throttled = True
                                remaining = sum(
                                    1 for remaining_author in authors[i + 1:]
                                    if _author_needs_hardcover_lookup(remaining_author)
                                )
                                if remaining:
                                    summary.hardcover.record_deferred("throttled", remaining)
                                logger.warning(
                                    "Hardcover throttled while refreshing author images at %r; "
                                    "deferring %d remaining author lookup(s) for this run",
                                    author.name,
                                    remaining,
                                )
                                scan_status.message = "Hardcover throttled; deferring remaining Hardcover author lookups..."
                                continue
                            raise
                        if hc_author and hc_author.image_url and not author_has_manual_image:
                            author.image_url = hc_author.image_url
                            if not author.bio:
                                author.bio = hc_author.bio
                            if not author.hardcover_slug:
                                author.hardcover_slug = hc_author.slug

                    if author_has_manual_image:
                        author.image_url = author.manual_image_url

                    if author.image_url and not author.image_cached_path:
                        source = _get_author_image_source(author.image_url)
                        cached = await cache_author_image(author.id, author.image_url, source=source)
                        if cached:
                            author.image_cached_path = cached

                    if not author.image_cached_path and not author_has_manual_image:
                        summary.openlibrary.lookups_attempted += 1
                        ol_author = await ol_client.search_author(author.name)
                        if ol_author and ol_author.photo_url_large:
                            cached = await cache_author_image(author.id, ol_author.photo_url_large, source="ol")
                            if cached:
                                author.image_url = ol_author.photo_url_large
                                author.image_cached_path = cached
                                summary.openlibrary.matched += 1
                            else:
                                summary.openlibrary.record_failure("cache_failed", attempted=False)
                        else:
                            summary.openlibrary.record_failure("no_result", attempted=False)

                    if not author.image_cached_path and not author_has_manual_image:
                        wikimedia_lookup = await wikimedia_client.search_author_with_result(author.name)
                        if wikimedia_lookup.author and wikimedia_lookup.author.image_url:
                            summary.wikimedia.record_match()
                            cached = await cache_author_image(author.id, wikimedia_lookup.author.image_url, source="wm")
                            if cached:
                                author.image_url = wikimedia_lookup.author.image_url
                                author.image_cached_path = cached
                            else:
                                summary.wikimedia.record_failure("cache_failed", attempted=False)
                        else:
                            summary.wikimedia.record_failure(wikimedia_lookup.reason)

                    progress = 20.0 + (30.0 * (i + 1) / max(total_authors, 1))
                    scan_status.progress = progress

                await db.commit()
                if new_author_count:
                    logger.info("Matched %d new author(s) to Hardcover", new_author_count)

                # Phase 3: Fetch books from Hardcover
                # - force=True: refresh ALL authors
                # - New authors (no last_synced_at): always fetch
                # - Authors with new files: always fetch (re-match needed)
                # - Other authors: skip if within cooldown
                scan_status.message = "Fetching books from Hardcover..."
                authors_synced = 0
                authors_skipped = 0

                # Build set of author names that have new files
                authors_with_new_files = scan_result.new_author_names.copy()
                for rel_path in scan_result.new_files:
                    # rel_path is like "Author Name/Book Title/file.epub"
                    parts = rel_path.split("/")
                    if parts:
                        authors_with_new_files.add(parts[0])

                if hardcover_throttled:
                    deferred_book_syncs = sum(
                        1 for author in authors
                        if _author_needs_hardcover_books_sync(author, force, authors_with_new_files)
                    )
                    if deferred_book_syncs:
                        summary.hardcover.record_deferred("throttled", deferred_book_syncs)
                        logger.warning(
                            "Skipping %d Hardcover author book lookup(s) for this run because Hardcover is throttled",
                            deferred_book_syncs,
                        )

                for i, author in enumerate(authors):
                    if not author.hardcover_id:
                        continue

                    needs_sync = False
                    if force:
                        needs_sync = True
                    elif not author.last_synced_at:
                        # Never synced — always fetch
                        needs_sync = True
                    elif author.name in authors_with_new_files:
                        # Has new local files — need to re-fetch for matching
                        needs_sync = True

                    if not needs_sync:
                        authors_skipped += 1
                        progress = 50.0 + (25.0 * (i + 1) / max(total_authors, 1))
                        scan_status.progress = progress
                        continue

                    if hardcover_throttled:
                        authors_skipped += 1
                        progress = 50.0 + (25.0 * (i + 1) / max(total_authors, 1))
                        scan_status.progress = progress
                        continue

                    scan_status.message = f"Fetching books for: {author.name}"
                    try:
                        hc_books = await client.get_author_books(author.hardcover_id)
                    except HardcoverLookupError as e:
                        summary.hardcover.record_failure(e.reason)
                        if e.reason == "throttled":
                            hardcover_throttled = True
                            remaining = sum(
                                1 for remaining_author in authors[i + 1:]
                                if _author_needs_hardcover_books_sync(remaining_author, force, authors_with_new_files)
                            )
                            if remaining:
                                summary.hardcover.record_deferred("throttled", remaining)
                            logger.warning(
                                "Hardcover throttled during book sync at author %r; "
                                "deferring %d remaining Hardcover author book lookup(s) for this run",
                                author.name,
                                remaining,
                            )
                            scan_status.message = "Hardcover throttled; deferring remaining Hardcover book lookups..."
                            continue
                        raise
                    summary.hardcover.record_match()

                    # Filter to canonical, Latin-titled books and deduplicate
                    canonical_books = [b for b in hc_books if b.is_canonical]
                    valid_books = [b for b in canonical_books if _is_valid_title(b.title)]
                    eligible_books = _deduplicate_books(valid_books)
                    author.book_count_total = len(eligible_books)
                    authors_synced += 1
                    skipped = len(hc_books) - len(eligible_books)
                    if skipped:
                        logger.info(
                            "Author %s: %d total, %d eligible (skipped %d non-canonical, %d non-Latin)",
                            author.name, len(hc_books), len(eligible_books),
                            len(hc_books) - len(canonical_books),
                            len(canonical_books) - len(eligible_books),
                        )

                    for hc_book in eligible_books:
                        existing = await db.execute(
                            select(Book).where(Book.hardcover_id == hc_book.id)
                        )
                        book = existing.scalar_one_or_none()
                        tags_json = json.dumps(hc_book.tags) if hc_book.tags else None

                        if book:
                            # If title changed, clear cached Google/OL matches so
                            # title-based metadata and cover lookups are rebuilt.
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
                            book.description = hc_book.description
                            book.release_date = hc_book.release_date
                            book.cover_image_url = hc_book.image_url
                            book.tags = tags_json
                            book.rating = hc_book.rating
                            book.pages = hc_book.pages
                            book.hardcover_slug = hc_book.slug
                            book.compilation = hc_book.compilation
                            book.book_category_id = hc_book.book_category_id
                            book.book_category_name = get_book_category_name(hc_book.book_category_id)
                            book.literary_type_id = hc_book.literary_type_id
                            book.literary_type_name = get_literary_type_name(hc_book.literary_type_id)
                            book.hardcover_state = hc_book.state or None
                            book.hardcover_isbn_10 = normalized_valid_isbn(hc_book.isbn_10)
                            book.hardcover_isbn_13 = normalized_valid_isbn(hc_book.isbn_13)
                            book.language = hc_book.language or book.language
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
                            books_added += 1

                        for sr in hc_book.series_refs:
                            series = await _get_or_create_series(db, sr.id, sr.name)
                            existing_bs = await db.execute(
                                select(BookSeries).where(
                                    BookSeries.book_id == book.id,
                                    BookSeries.series_id == series.id,
                                )
                            )
                            if not existing_bs.scalar_one_or_none():
                                bs = BookSeries(
                                    book_id=book.id,
                                    series_id=series.id,
                                    position=sr.position,
                                )
                                db.add(bs)

                    author.last_synced_at = datetime.utcnow()
                    progress = 50.0 + (25.0 * (i + 1) / max(total_authors, 1))
                    scan_status.progress = progress

                await db.commit()
                logger.info(
                    "Hardcover sync: %d author(s) fetched, %d skipped (no changes / recently synced)",
                    authors_synced, authors_skipped,
                )

                # Phase 4: Match local files to Hardcover books and repair
                # existing local-only links using freshly parsed file metadata.
                scan_status.message = "Matching local files to Hardcover books..."
                matched_count, repaired_count, new_local_books = await _repair_local_file_links(db)
                books_added += new_local_books
                summary.books_added = books_added
                scan_status.progress = 80.0

                # Phase 5: Publish date enrichment
                # Hardcover remains the authoritative release_date.
                # Google Books and Open Library dates are stored separately.
                scan_status.message = "Fetching publish dates..."
                google_api_key = await get_google_api_key(db)
                visibility_settings = await get_book_visibility_settings(db)
                synced_author_ids = [a.id for a in authors if a.hardcover_id]
                google_data = {}  # book_id -> GBook (reused for cover URLs in Phase 6)
                ol_data = {}      # book_id -> OLBook
                google_retry_ids: set[int] = set()

                if synced_author_ids:
                    books_result = await db.execute(
                        select(Book).where(
                            Book.author_id.in_(synced_author_ids),
                            Book.hardcover_id.isnot(None),
                        )
                    )
                    all_hc_books = books_result.scalars().all()
                    books_to_reconcile = [
                        book for book in all_hc_books
                        if book.publish_date_checked_at is None
                        and is_book_visible(book, visibility_settings)
                    ]
                    author_map = {a.id: a.name for a in authors}

                    # 5a: Fetch Google data for books that have not had their
                    # publish-date sources checked yet. Hardcover remains the
                    # source-of-truth release_date.
                    if google_api_key and books_to_reconcile:
                        # Load cached Google data for books already searched.
                        # google_id="_none" means "searched, no result" — skip
                        # unless force=True (user wants full re-fetch).
                        books_need_google = []
                        for book in books_to_reconcile:
                            if book.google_id == "_none" and not force:
                                summary.google.record_cached()
                            elif book.google_id and book.google_id != "_none":
                                # Positive cache — reconstruct GBook from DB
                                google_data[book.id] = GBook(
                                    title=book.title,
                                    published_date=book.google_published_date,
                                    cover_url=book.google_cover_url,
                                    google_id=book.google_id,
                                    isbn_10=book.google_isbn_10,
                                    isbn_13=book.google_isbn_13,
                                )
                                summary.google.record_cached()
                            else:
                                books_need_google.append(book)

                        if books_need_google:
                            scan_status.message = (
                                f"Fetching dates from Google Books... "
                                f"0/{len(books_need_google)} "
                                f"({len(books_to_reconcile) - len(books_need_google)} cached)"
                            )
                            google_client = GoogleBooksClient(google_api_key)
                            try:
                                fetched = 0
                                throttled = False
                                for i, book in enumerate(books_need_google):
                                    try:
                                        gbook = None
                                        final_reason = "no_result"
                                        for isbn in _preferred_google_isbns(book):
                                            isbn_result = await google_client.search_by_isbn_result(isbn)
                                            gbook = isbn_result.book
                                            final_reason = isbn_result.reason
                                            if gbook or final_reason not in {"no_result"}:
                                                break
                                        if not gbook:
                                            author_name = author_map.get(book.author_id, "")
                                            title_result = await google_client.search_by_title_author_result(
                                                book.title, author_name
                                            )
                                            gbook = title_result.book
                                            final_reason = title_result.reason
                                        if gbook:
                                            summary.google.record_match()
                                            google_data[book.id] = gbook
                                            # Persist Google data to DB
                                            book.google_id = gbook.google_id
                                            book.google_published_date = gbook.published_date
                                            book.google_cover_url = gbook.cover_url
                                            book.google_isbn_10 = normalized_valid_isbn(gbook.isbn_10)
                                            book.google_isbn_13 = normalized_valid_isbn(gbook.isbn_13)
                                            fetched += 1
                                        else:
                                            summary.google.record_failure(final_reason)
                                            # Mark as searched so we don't retry
                                            book.google_id = "_none"
                                    except GoogleBooksThrottledError as e:
                                        summary.google.record_failure(e.reason)
                                        throttled = True
                                        google_retry_ids.update(
                                            pending_book.id for pending_book in books_need_google[i:]
                                        )
                                        remaining = len(books_need_google) - (i + 1)
                                        if remaining > 0:
                                            summary.google.record_deferred("throttled", remaining)
                                        logger.warning(
                                            "Google Books throttled after %d/%d uncached lookup(s); "
                                            "deferring the remaining %d book(s) for a later scan",
                                            i,
                                            len(books_need_google),
                                            len(books_need_google) - i,
                                        )
                                        scan_status.message = (
                                            "Google Books throttled; deferring remaining lookups"
                                        )
                                        break
                                    except GoogleBooksLookupError as e:
                                        summary.google.record_failure(e.reason)
                                        google_retry_ids.add(book.id)
                                        logger.warning(
                                            "Google Books lookup failed for '%s': %s",
                                            book.title[:50], e,
                                        )
                                    scan_status.message = (
                                        f"Fetching dates from Google Books... "
                                        f"{i + 1}/{len(books_need_google)} "
                                        f"({len(books_to_reconcile) - len(books_need_google)} cached)"
                                    )
                                await db.commit()
                                logger.info(
                                    "Google Books: fetched %d new, %d cached, %d total of %d books",
                                    fetched,
                                    len(books_to_reconcile) - len(books_need_google),
                                    len(google_data),
                                    len(books_to_reconcile),
                                )
                                if throttled or google_retry_ids:
                                    logger.warning(
                                        "Google Books: deferred finalization for %d book(s) due to "
                                        "throttling/request failures",
                                        len(google_retry_ids),
                                    )
                            finally:
                                await google_client.close()
                        else:
                            logger.info(
                                "Google Books: all %d books already cached, 0 API calls",
                                len(google_data),
                            )

                    # 5b: Fetch Open Library dates for the same eligible books so
                    # we retain source-specific metadata without overriding Hardcover.
                    ol_candidates = list(books_to_reconcile)

                    # Load cached OL data; only fetch books not yet searched.
                    # ol_edition_key="_none" means "searched, no result" — skip
                    # unless force=True.
                    books_need_ol_fetch = []
                    for book in ol_candidates:
                        if book.ol_edition_key == "_none" and not force:
                            summary.openlibrary.record_cached()
                        elif book.ol_edition_key and book.ol_edition_key != "_none":
                            # Positive cache — reconstruct OLBook from persisted data
                            ol_data[book.id] = OLBook(
                                title=book.title,
                                first_publish_year=book.ol_first_publish_year,
                                cover_id=_extract_ol_cover_id(book.ol_cover_url),
                                isbn_list=[isbn for isbn in [book.ol_isbn_10, book.ol_isbn_13] if isbn],
                            )
                            summary.openlibrary.record_cached()
                        else:
                            books_need_ol_fetch.append(book)

                    if books_need_ol_fetch:
                        ol_cached = len(ol_candidates) - len(books_need_ol_fetch)
                        scan_status.message = (
                            f"Fetching dates from Open Library... "
                            f"{len(books_need_ol_fetch)} remaining "
                            f"({ol_cached} cached)"
                        )
                        ol_client = OpenLibraryClient()
                        try:
                            sem = asyncio.Semaphore(10)

                            async def _fetch_ol_year(book):
                                async with sem:
                                    for isbn in _preferred_google_isbns(book):
                                        isbn_lookup = await ol_client.search_book_by_isbn_with_result(isbn)
                                        if isbn_lookup.book:
                                            return isbn_lookup
                                        if isbn_lookup.reason not in {"no_result"}:
                                            return isbn_lookup
                                    author_name = author_map.get(book.author_id, "")
                                    return await ol_client.search_book_with_result(book.title, author_name)

                            results = await asyncio.gather(
                                *[_fetch_ol_year(b) for b in books_need_ol_fetch]
                            )
                            fetched_ol = 0
                            for book, ol_lookup in zip(books_need_ol_fetch, results):
                                if ol_lookup.book:
                                    summary.openlibrary.record_match()
                                    ol_isbn_10, ol_isbn_13 = extract_isbn_variants(ol_lookup.book.isbn_list)
                                    ol_data[book.id] = ol_lookup.book
                                    # Persist OL data to DB
                                    book.ol_edition_key = ol_lookup.book.cover_edition_key or "_found"
                                    book.ol_first_publish_year = ol_lookup.book.first_publish_year
                                    if not book.hardcover_isbn_10 and not book.google_isbn_10:
                                        book.ol_isbn_10 = ol_isbn_10
                                    if not book.hardcover_isbn_13 and not book.google_isbn_13:
                                        book.ol_isbn_13 = ol_isbn_13
                                    if ol_lookup.book.cover_id:
                                        book.ol_cover_url = ol_lookup.book.cover_url_large
                                    fetched_ol += 1
                                else:
                                    summary.openlibrary.record_failure(ol_lookup.reason)
                                    book.ol_edition_key = "_none"
                            await db.commit()
                            logger.info(
                                "Open Library: fetched %d new, %d cached, %d no result",
                                fetched_ol,
                                len(ol_candidates) - len(books_need_ol_fetch),
                                len(books_need_ol_fetch) - fetched_ol,
                            )
                        finally:
                            await ol_client.close()
                    elif ol_candidates:
                        logger.info(
                            "Open Library: all %d books already cached, 0 API calls",
                            len(ol_data),
                        )

                    # 5c: Finalize publish-date source fetch state
                    finalized = 0
                    for book in books_to_reconcile:
                        if book.id in google_retry_ids:
                            continue
                        book.publish_date_checked_at = datetime.utcnow()
                        finalized += 1

                    if books_to_reconcile:
                        await db.commit()
                        logger.info(
                            "Stored Google/Open Library publish dates for %d book(s); Hardcover dates retained",
                            finalized,
                        )
                        if google_retry_ids:
                            logger.warning(
                                "Left %d book(s) unchecked so a later scan can retry Google Books",
                                len(google_retry_ids),
                            )
                    else:
                        logger.info("Publish date sources already finalized for all books; skipping phase 5")

                scan_status.progress = 87.0

                # Phase 6: Cover pipeline
                # Source priority: local → Hardcover → Google → Open Library
                # Stop per-book once cover height >= 2000px
                scan_status.message = "Processing book covers..."

                result = await db.execute(select(Book))
                all_books = result.scalars().all()
                visible_books = [
                    book for book in all_books
                    if is_book_visible(book, visibility_settings)
                ]
                hidden_counts: dict[str, dict[str, str | int]] = {}
                for book in all_books:
                    hidden = get_hidden_category(book, visibility_settings)
                    if not hidden:
                        continue
                    key, label = hidden
                    entry = hidden_counts.setdefault(
                        key,
                        {"key": key, "label": label, "count": 0},
                    )
                    entry["count"] = int(entry["count"]) + 1
                summary.books_hidden = sum(int(item["count"]) for item in hidden_counts.values())
                summary.hidden_by_category = sorted(
                    hidden_counts.values(),
                    key=lambda item: (-int(item["count"]), str(item["label"])),
                )

                # Track cover heights in memory to avoid re-reading cached files
                cover_heights = {}
                cover_sources = {}
                cover_ratios = {}
                for book in all_books:
                    cover_heights[book.id] = get_cached_cover_height(
                        book.cover_image_cached_path
                    )
                    cover_sources[book.id] = _get_cached_cover_source(
                        book.cover_image_cached_path
                    )
                    cover_ratios[book.id] = get_cached_cover_aspect_ratio(
                        book.cover_image_cached_path
                    )

                # 6a: Local covers (cover.jpg + EPUB embedded) for owned books
                scan_status.message = "Checking local covers..."
                local_cached = 0
                for book in all_books:
                    if not book.is_owned:
                        continue
                    if cover_heights.get(book.id, 0) >= COVER_HEIGHT_THRESHOLD:
                        continue
                    if not book.files:
                        continue
                    bf = book.files[0]
                    local_cover = bf.local_cover_path
                    epub_path = (
                        BOOKS_DIR / bf.file_path if bf.file_format == "epub" else None
                    )
                    cached = cache_best_local_cover(
                        local_cover, epub_path, book.id,
                        existing_cached_path=book.cover_image_cached_path,
                    )
                    if cached:
                        book.cover_image_cached_path = cached
                        cover_heights[book.id] = get_cached_cover_height(cached)
                        cover_sources[book.id] = _get_cached_cover_source(cached)
                        cover_ratios[book.id] = get_cached_cover_aspect_ratio(cached)
                        local_cached += 1
                if local_cached:
                    logger.info("Cached/upgraded %d local cover(s)", local_cached)
                await db.commit()

                # 6b: Hardcover covers — concurrent download for books under threshold.
                # Hardcover should reclaim books from legacy/Google/OL remote covers.
                scan_status.message = "Downloading covers from Hardcover..."
                books_for_hc = [
                    b for b in all_books
                    if cover_heights.get(b.id, 0) < COVER_HEIGHT_THRESHOLD
                    and b.cover_image_url
                    and cover_sources.get(b.id) != "hardcover"
                ]
                hc_covers = 0
                if books_for_hc:
                    sem = asyncio.Semaphore(20)

                    async def _dl_hc(book):
                        async with sem:
                            return await download_image_bytes(book.cover_image_url)

                    hc_results = await asyncio.gather(
                        *[_dl_hc(b) for b in books_for_hc]
                    )
                    for book, data in zip(books_for_hc, hc_results):
                        if not data:
                            continue
                        current_height = cover_heights.get(book.id, 0)
                        current_ratio = cover_ratios.get(book.id)
                        new_height, new_ratio = _measure_cover_data(data)
                        if _should_replace_cover(
                            current_source=cover_sources.get(book.id),
                            current_height=current_height,
                            current_ratio=current_ratio,
                            new_source="hardcover",
                            new_height=new_height,
                            new_ratio=new_ratio,
                        ):
                            path = cache_cover_data(data, book.id, "hardcover")
                            if path:
                                book.cover_image_cached_path = path
                                cover_heights[book.id] = new_height
                                cover_sources[book.id] = "hardcover"
                                cover_ratios[book.id] = new_ratio
                                hc_covers += 1
                    await db.commit()
                if hc_covers:
                    logger.info("Cached %d cover(s) from Hardcover", hc_covers)
                scan_status.progress = 90.0

                # 6c: Google covers — only use fresh Google matches from this scan
                # and only for books that still have no cover and no Hardcover art.
                google_cover_books = [
                    b for b in visible_books
                    if b.id in google_data and google_data[b.id].cover_url
                ]
                if google_cover_books:
                    scan_status.message = "Downloading covers from Google Books..."
                    books_for_google = [
                        b for b in google_cover_books
                        if not b.cover_image_cached_path and not b.cover_image_url
                    ]
                    google_covers = 0
                    if books_for_google:
                        sem = asyncio.Semaphore(20)

                        async def _dl_google(book):
                            async with sem:
                                gbook = google_data.get(book.id)
                                if not gbook or not gbook.cover_url:
                                    return None
                                return await download_image_bytes(gbook.cover_url)

                        g_results = await asyncio.gather(
                            *[_dl_google(b) for b in books_for_google]
                        )
                        for book, data in zip(books_for_google, g_results):
                            if not data:
                                continue
                            current_height = cover_heights.get(book.id, 0)
                            current_ratio = cover_ratios.get(book.id)
                            new_height, new_ratio = _measure_cover_data(data)
                            if _should_replace_cover(
                                current_source=cover_sources.get(book.id),
                                current_height=current_height,
                                current_ratio=current_ratio,
                                new_source="google",
                                new_height=new_height,
                                new_ratio=new_ratio,
                            ):
                                path = cache_cover_data(data, book.id, "google")
                                if path:
                                    book.cover_image_cached_path = path
                                    cover_heights[book.id] = new_height
                                    cover_sources[book.id] = "google"
                                    cover_ratios[book.id] = new_ratio
                                    google_covers += 1
                        await db.commit()
                    if google_covers:
                        logger.info("Cached %d cover(s) from Google Books", google_covers)
                scan_status.progress = 93.0

                # 6d: Open Library covers — last resort for books with NO cover
                books_no_cover = [
                    b for b in visible_books
                    if not b.cover_image_cached_path and b.hardcover_id
                ]
                if books_no_cover:
                    scan_status.message = "Fetching missing covers from Open Library..."
                    ol_covers = 0

                    # Load cached OL data for books that have it;
                    # only search OL for books never searched before.
                    books_need_ol_search = []
                    for book in books_no_cover:
                        if book.id in ol_data:
                            pass  # Already looked up earlier in this scan
                        elif book.ol_edition_key == "_none" and not force:
                            summary.openlibrary.record_cached()
                        elif book.ol_edition_key and book.ol_edition_key != "_none":
                            # Positive cache — reconstruct from DB
                            ol_data[book.id] = OLBook(
                                title=book.title,
                                first_publish_year=book.ol_first_publish_year,
                                cover_id=_extract_ol_cover_id(book.ol_cover_url),
                                isbn_list=[isbn for isbn in [book.ol_isbn_10, book.ol_isbn_13] if isbn],
                            )
                            summary.openlibrary.record_cached()
                        else:
                            books_need_ol_search.append(book)

                    if books_need_ol_search:
                        ol_cover_map = {a.id: a.name for a in authors}
                        ol_client2 = OpenLibraryClient()
                        try:
                            sem = asyncio.Semaphore(10)

                            async def _fetch_ol_cover(book):
                                async with sem:
                                    if book.isbn:
                                        isbn_lookup = await ol_client2.search_book_by_isbn_with_result(
                                            book.isbn
                                        )
                                        if isbn_lookup.book:
                                            return isbn_lookup
                                        if isbn_lookup.reason not in {"no_result"}:
                                            return isbn_lookup
                                    author_name = ol_cover_map.get(book.author_id, "")
                                    return await ol_client2.search_book_with_result(
                                        book.title, author_name
                                    )

                            results = await asyncio.gather(
                                *[_fetch_ol_cover(b) for b in books_need_ol_search]
                            )
                            for book, ol_lookup in zip(books_need_ol_search, results):
                                if ol_lookup.book:
                                    summary.openlibrary.record_match()
                                    ol_isbn_10, ol_isbn_13 = extract_isbn_variants(ol_lookup.book.isbn_list)
                                    ol_data[book.id] = ol_lookup.book
                                    # Persist OL data to DB
                                    book.ol_edition_key = ol_lookup.book.cover_edition_key or "_found"
                                    book.ol_first_publish_year = ol_lookup.book.first_publish_year
                                    if not book.hardcover_isbn_10 and not book.google_isbn_10:
                                        book.ol_isbn_10 = ol_isbn_10
                                    if not book.hardcover_isbn_13 and not book.google_isbn_13:
                                        book.ol_isbn_13 = ol_isbn_13
                                    if ol_lookup.book.cover_id:
                                        book.ol_cover_url = ol_lookup.book.cover_url_large
                                else:
                                    summary.openlibrary.record_failure(ol_lookup.reason)
                                    book.ol_edition_key = "_none"
                        finally:
                            await ol_client2.close()

                    # Download OL covers concurrently
                    ol_download_books = []
                    ol_download_urls = []
                    for book in books_no_cover:
                        ol_book = ol_data.get(book.id)
                        if ol_book and ol_book.cover_id:
                            ol_download_books.append(book)
                            ol_download_urls.append(ol_book.cover_url_large)

                    if ol_download_urls:
                        sem = asyncio.Semaphore(10)

                        async def _dl_ol(url):
                            async with sem:
                                return await download_image_bytes(url)

                        ol_dl_results = await asyncio.gather(
                            *[_dl_ol(u) for u in ol_download_urls]
                        )
                        for book, data in zip(ol_download_books, ol_dl_results):
                            if data:
                                current_height = cover_heights.get(book.id, 0)
                                current_ratio = cover_ratios.get(book.id)
                                new_height, new_ratio = _measure_cover_data(data)
                                if _should_replace_cover(
                                    current_source=cover_sources.get(book.id),
                                    current_height=current_height,
                                    current_ratio=current_ratio,
                                    new_source="openlibrary",
                                    new_height=new_height,
                                    new_ratio=new_ratio,
                                ):
                                    path = cache_cover_data(data, book.id, "openlibrary")
                                    if path:
                                        book.cover_image_cached_path = path
                                        cover_heights[book.id] = new_height
                                        cover_sources[book.id] = "openlibrary"
                                        cover_ratios[book.id] = new_ratio
                                        ol_covers += 1

                    await db.commit()
                    if ol_covers:
                        logger.info("Cached %d cover(s) from Open Library", ol_covers)

                manual_overrides = 0
                for book in all_books:
                    if not book.manual_cover_source:
                        continue
                    if await apply_manual_cover_selection(book):
                        manual_overrides += 1

                if manual_overrides:
                    await db.commit()
                    logger.info("Reapplied %d manual cover override(s)", manual_overrides)

                scan_status.progress = 96.0

                # Update author local book counts
                for author in authors:
                    count_result = await db.execute(
                        select(func.count(Book.id)).where(
                            Book.author_id == author.id,
                            Book.is_owned == True,
                        )
                    )
                    author.book_count_local = count_result.scalar() or 0

                await db.commit()
                summary.owned_books_found = await _count_owned_books(db)

            finally:
                await ol_client.close()
                await wikimedia_client.close()
                await client.close()

            await flush_api_usage_batch(db)
            await _update_last_scan(db)
            final_message = (
                "Scan complete with some Hardcover work deferred due to rate limiting."
                if summary.hardcover.deferred > 0 and summary.hardcover.failure_reasons.get("throttled")
                else "Scan complete!"
            )
            await _finalize_scan_summary(db, summary, message=final_message)

        scan_status.progress = 100.0
        scan_status.message = (
            "Scan complete with some Hardcover work deferred due to rate limiting."
            if summary.hardcover.deferred > 0 and summary.hardcover.failure_reasons.get("throttled")
            else "Scan complete!"
        )
        scan_status.status = "idle"

    except Exception as e:
        logger.exception("Sync failed: %s", e)
        scan_status.message = f"Error: {str(e)}"
        scan_status.status = "idle"
        scan_status.progress = 0.0
        summary.status = "error"
        summary.message = f"Error: {str(e)}"
        summary.completed_at = _now_iso()
        try:
            async with async_session() as db:
                await flush_api_usage_batch(db)
                summary.owned_books_found = await _count_owned_books(db)
                await _populate_hidden_summary(db, summary)
                await _persist_scan_summary(db, summary)
        except Exception:
            logger.exception("Failed to persist scan summary after sync error")
    finally:
        clear_api_usage_batch(usage_batch_token)


async def refresh_single_book(book_id: int):
    usage_batch_token = begin_api_usage_batch()
    try:
        async with async_session() as db:
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
                raise ValueError("Book not found")

            author_name = book.author.name if book.author else ""
            tags_json = None
            gbook: GBook | None = None
            ol_book: OLBook | None = None
            google_retry = False
            local_title, local_isbn, local_publisher, local_description = _reparse_book_files(book)

            # Clear imported metadata so this behaves like a fresh re-import.
            # The attached local file(s) are reparsed first and become the
            # starting point before Hardcover/Google/Open Library run again.
            book.title = local_title or book.title
            book.isbn = local_isbn
            book.publisher = local_publisher
            book.description = local_description
            book.release_date = None
            book.tags = None
            book.rating = None
            book.pages = None
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
            book.cover_image_cached_path = None
            book.is_owned = bool(book.files)

            api_key = await get_api_key(db)
            if book.hardcover_id and api_key:
                client = HardcoverClient(api_key)
                try:
                    hc_book = await client.get_book(book.hardcover_id)
                finally:
                    await client.close()

                if hc_book:
                    tags_json = json.dumps(hc_book.tags) if hc_book.tags else None
                    book.title = hc_book.title
                    book.hardcover_slug = hc_book.slug
                    book.description = hc_book.description
                    book.release_date = hc_book.release_date
                    book.cover_image_url = hc_book.image_url
                    book.tags = tags_json
                    book.rating = hc_book.rating
                    book.pages = hc_book.pages
                    book.compilation = hc_book.compilation
                    book.book_category_id = hc_book.book_category_id
                    book.book_category_name = get_book_category_name(hc_book.book_category_id)
                    book.literary_type_id = hc_book.literary_type_id
                    book.literary_type_name = get_literary_type_name(hc_book.literary_type_id)
                    book.hardcover_state = hc_book.state or None
                    book.hardcover_isbn_10 = normalized_valid_isbn(hc_book.isbn_10)
                    book.hardcover_isbn_13 = normalized_valid_isbn(hc_book.isbn_13)
                    book.language = hc_book.language or book.language

                    for existing_bs in list(book.book_series):
                        await db.delete(existing_bs)
                    await db.flush()

                    for sr in hc_book.series_refs:
                        series = await _get_or_create_series(db, sr.id, sr.name)
                        db.add(BookSeries(
                            book_id=book.id,
                            series_id=series.id,
                            position=sr.position,
                        ))

            google_api_key = await get_google_api_key(db)
            if google_api_key:
                google_client = GoogleBooksClient(google_api_key)
                try:
                    final_reason = "no_result"
                    for isbn in _preferred_google_isbns(book):
                        isbn_result = await google_client.search_by_isbn_result(isbn)
                        gbook = isbn_result.book
                        final_reason = isbn_result.reason
                        if gbook or final_reason not in {"no_result"}:
                            break

                    if not gbook:
                        title_result = await google_client.search_by_title_author_result(
                            book.title,
                            author_name,
                        )
                        gbook = title_result.book
                        final_reason = title_result.reason

                    if gbook:
                        book.google_id = gbook.google_id
                        book.google_published_date = gbook.published_date
                        book.google_cover_url = gbook.cover_url
                        book.google_isbn_10 = normalized_valid_isbn(gbook.isbn_10)
                        book.google_isbn_13 = normalized_valid_isbn(gbook.isbn_13)
                    elif final_reason in {"no_result", "title_mismatch", "author_mismatch"}:
                        book.google_id = "_none"
                except (GoogleBooksThrottledError, GoogleBooksLookupError):
                    google_retry = True
                    logger.warning("Single-book Google refresh failed for '%s'", book.title)
                finally:
                    await google_client.close()

            ol_client = OpenLibraryClient()
            try:
                for isbn in _preferred_google_isbns(book):
                    lookup = await ol_client.search_book_by_isbn_with_result(isbn)
                    if lookup.book:
                        ol_book = lookup.book
                        break
                    if lookup.reason not in {"no_result"}:
                        break

                if not ol_book:
                    lookup = await ol_client.search_book_with_result(book.title, author_name)
                    if lookup.book:
                        ol_book = lookup.book
                    elif lookup.reason == "no_result":
                        book.ol_edition_key = "_none"

                if ol_book:
                    ol_isbn_10, ol_isbn_13 = extract_isbn_variants(ol_book.isbn_list)
                    book.ol_edition_key = ol_book.cover_edition_key or "_found"
                    book.ol_first_publish_year = ol_book.first_publish_year
                    if not book.hardcover_isbn_10 and not book.google_isbn_10:
                        book.ol_isbn_10 = ol_isbn_10
                    if not book.hardcover_isbn_13 and not book.google_isbn_13:
                        book.ol_isbn_13 = ol_isbn_13
                    if ol_book.cover_id:
                        book.ol_cover_url = ol_book.cover_url_large
            finally:
                await ol_client.close()

            if not google_retry:
                book.publish_date_checked_at = datetime.utcnow()

            cover_height = get_cached_cover_height(book.cover_image_cached_path)
            cover_source = _get_cached_cover_source(book.cover_image_cached_path)
            cover_ratio = get_cached_cover_aspect_ratio(book.cover_image_cached_path)

            if book.is_owned and book.files:
                bf = book.files[0]
                epub_path = BOOKS_DIR / bf.file_path if bf.file_format == "epub" else None
                cached = cache_best_local_cover(
                    bf.local_cover_path,
                    epub_path,
                    book.id,
                    existing_cached_path=book.cover_image_cached_path,
                )
                if cached:
                    book.cover_image_cached_path = cached
                    cover_height = get_cached_cover_height(cached)
                    cover_source = _get_cached_cover_source(cached)
                    cover_ratio = get_cached_cover_aspect_ratio(cached)

            if book.cover_image_url:
                data = await download_image_bytes(book.cover_image_url)
                if data:
                    new_height, new_ratio = _measure_cover_data(data)
                    if _should_replace_cover(
                        current_source=cover_source,
                        current_height=cover_height,
                        current_ratio=cover_ratio,
                        new_source="hardcover",
                        new_height=new_height,
                        new_ratio=new_ratio,
                    ):
                        path = cache_cover_data(data, book.id, "hardcover")
                        if path:
                            book.cover_image_cached_path = path
                            cover_height = new_height
                            cover_source = "hardcover"
                            cover_ratio = new_ratio

            if gbook and gbook.cover_url:
                data = await download_image_bytes(gbook.cover_url)
                if data:
                    new_height, new_ratio = _measure_cover_data(data)
                    if _should_replace_cover(
                        current_source=cover_source,
                        current_height=cover_height,
                        current_ratio=cover_ratio,
                        new_source="google",
                        new_height=new_height,
                        new_ratio=new_ratio,
                    ):
                        path = cache_cover_data(data, book.id, "google")
                        if path:
                            book.cover_image_cached_path = path
                            cover_height = new_height
                            cover_source = "google"
                            cover_ratio = new_ratio

            if ol_book and ol_book.cover_id:
                data = await download_image_bytes(ol_book.cover_url_large)
                if data:
                    new_height, new_ratio = _measure_cover_data(data)
                    if _should_replace_cover(
                        current_source=cover_source,
                        current_height=cover_height,
                        current_ratio=cover_ratio,
                        new_source="openlibrary",
                        new_height=new_height,
                        new_ratio=new_ratio,
                    ):
                        path = cache_cover_data(data, book.id, "openlibrary")
                        if path:
                            book.cover_image_cached_path = path
                            cover_height = new_height
                            cover_source = "openlibrary"
                            cover_ratio = new_ratio

            if book.manual_cover_source:
                await apply_manual_cover_selection(book)

            await flush_api_usage_batch(db)
            await db.commit()
    finally:
        clear_api_usage_batch(usage_batch_token)


async def refresh_single_author(author_id: int):
    usage_batch_token = begin_api_usage_batch()
    try:
        async with async_session() as db:
            await scan_library(db, BOOKS_DIR)

            result = await db.execute(
                select(Author)
                .where(Author.id == author_id)
                .options(
                    selectinload(Author.books).selectinload(Book.files),
                    selectinload(Author.author_directories),
                )
            )
            author = result.scalar_one_or_none()
            if not author:
                raise ValueError("Author not found")

            api_key = await get_api_key(db)
            books_added = 0
            books_removed = 0
            if api_key:
                client = HardcoverClient(api_key)
                try:
                    books_added, books_removed = await _sync_author_hardcover_catalog(db, author, client)
                finally:
                    await client.close()

            matched_count, repaired_count, new_local_books = await _repair_local_file_links(db, author=author)
            books_added += new_local_books

            count_result = await db.execute(
                select(func.count(Book.id)).where(
                    Book.author_id == author.id,
                    Book.is_owned == True,
                )
            )
            author.book_count_local = count_result.scalar() or 0

            await db.commit()
            logger.info(
                "Author refresh complete: author_id=%s name=%r books_added=%d books_removed=%d matched=%d repaired=%d",
                author.id,
                author.name,
                books_added,
                books_removed,
                matched_count,
                repaired_count,
            )
    finally:
        clear_api_usage_batch(usage_batch_token)


async def _get_or_create_series(db: AsyncSession, hardcover_id: int, name: str) -> Series:
    result = await db.execute(select(Series).where(Series.hardcover_id == hardcover_id))
    series = result.scalar_one_or_none()
    if not series:
        series = Series(hardcover_id=hardcover_id, name=name)
        db.add(series)
        await db.flush()
    return series


async def _update_last_scan(db: AsyncSession):
    result = await db.execute(select(Setting).where(Setting.key == "last_scan_at"))
    setting = result.scalar_one_or_none()
    now = _now_iso()
    if setting:
        setting.value = now
    else:
        db.add(Setting(key="last_scan_at", value=now))
    await db.commit()


async def _count_owned_books(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count(Book.id)).where(Book.is_owned == True)
    )
    return result.scalar() or 0


async def _populate_hidden_summary(db: AsyncSession, summary: ScanRunSummary):
    visibility_settings = await get_book_visibility_settings(db)
    result = await db.execute(select(Book))
    all_books = result.scalars().all()
    hidden_counts: dict[str, dict[str, str | int]] = {}
    for book in all_books:
        hidden = get_hidden_category(book, visibility_settings)
        if not hidden:
            continue
        key, label = hidden
        entry = hidden_counts.setdefault(
            key,
            {"key": key, "label": label, "count": 0},
        )
        entry["count"] = int(entry["count"]) + 1
    summary.books_hidden = sum(int(item["count"]) for item in hidden_counts.values())
    summary.hidden_by_category = sorted(
        hidden_counts.values(),
        key=lambda item: (-int(item["count"]), str(item["label"])),
    )


async def _persist_scan_summary(db: AsyncSession, summary: ScanRunSummary):
    payload = json.dumps(summary.to_dict(), sort_keys=True)
    result = await db.execute(select(Setting).where(Setting.key == "last_scan_summary"))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = payload
    else:
        db.add(Setting(key="last_scan_summary", value=payload))
    await db.commit()


async def _finalize_scan_summary(db: AsyncSession, summary: ScanRunSummary, message: str | None = None):
    summary.status = "completed"
    summary.message = message or summary.message
    summary.completed_at = _now_iso()
    summary.owned_books_found = await _count_owned_books(db)
    await _populate_hidden_summary(db, summary)
    await _persist_scan_summary(db, summary)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
