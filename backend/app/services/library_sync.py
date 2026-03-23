import asyncio
import json
import logging
import re
import unicodedata
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import BOOKS_DIR
from backend.app.database import async_session
from backend.app.models import Author, Book, BookFile, BookSeries, Series, Setting
from backend.app.services.scanner import scan_library, ScanResult
from backend.app.services.hardcover import HardcoverClient
from backend.app.services.matcher import titles_match
from backend.app.services.image_cache import (
    cache_author_image,
    cache_best_local_cover,
    download_image_bytes,
    cache_cover_data,
    get_cached_cover_height,
)
from backend.app.services.openlibrary import OpenLibraryClient, OLBook
from backend.app.utils.hardcover_metadata import get_book_category_name, get_literary_type_name
from backend.app.utils.book_visibility import get_book_visibility_settings, is_book_visible
from backend.app.services.google_books import (
    GoogleBooksClient,
    GBook,
    GoogleBooksLookupError,
    GoogleBooksThrottledError,
)
from backend.app.utils.epub_cover import get_image_dimensions

logger = logging.getLogger("booksarr.sync")

# Articles to strip when comparing titles for deduplication
_ARTICLE_RE = re.compile(r"^(a|an|the)\s+", re.IGNORECASE)

# Cover height threshold — stop looking for better covers once met
COVER_HEIGHT_THRESHOLD = 2000


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


def _extract_year(date_str: str | None) -> int | None:
    """Extract year from a date string like '2024-01-15' or '2024'."""
    if not date_str or len(date_str) < 4:
        return None
    try:
        return int(date_str[:4])
    except ValueError:
        return None


def _reconcile_year_3way(
    hc_date: str | None,
    google_year: int | None,
    ol_year: int | None,
) -> str | None:
    """Reconcile publish year across up to 3 sources.

    Strategy:
    - HC date is preferred (may have full YYYY-MM-DD format)
    - If HC and Google agree (within 1 year), keep HC date
    - If HC and Google disagree, use OL as tiebreaker
    - If all three differ, use the latest year
    """
    hc_year = _extract_year(hc_date)

    sources = {}
    if hc_year:
        sources["HC"] = hc_year
    if google_year:
        sources["Google"] = google_year
    if ol_year:
        sources["OL"] = ol_year

    if not sources:
        return hc_date  # No data from any source

    if len(sources) == 1:
        if hc_year:
            return hc_date  # Preserve full HC date format
        return f"{list(sources.values())[0]}-01-01"

    # Multiple sources — check for agreement
    if hc_year and google_year:
        if abs(hc_year - google_year) <= 1:
            return hc_date  # HC and Google agree — keep HC

        # HC and Google disagree
        if ol_year:
            if abs(ol_year - hc_year) <= 1:
                return hc_date  # OL agrees with HC
            if abs(ol_year - google_year) <= 1:
                return f"{google_year}-01-01"  # OL agrees with Google
            # All three differ — use latest
            best = max(hc_year, google_year, ol_year)
            source = [k for k, v in sources.items() if v == best][0]
            logger.debug(
                "Year 3-way: HC=%s Google=%s OL=%s -> %d (%s)",
                hc_year, google_year, ol_year, best, source,
            )
            return hc_date if best == hc_year else f"{best}-01-01"

        # No OL data — use later year (common error is too-early dates)
        best = max(hc_year, google_year)
        return hc_date if best == hc_year else f"{google_year}-01-01"

    # HC + OL only (no Google key)
    if hc_year and ol_year:
        if abs(hc_year - ol_year) <= 1:
            return hc_date
        best = max(hc_year, ol_year)
        source = "HC" if best == hc_year else "OL"
        logger.debug("Year reconcile: HC=%s OL=%s -> %d (%s)", hc_year, ol_year, best, source)
        return hc_date if best == hc_year else f"{ol_year}-01-01"

    # Google + OL only (no HC date) — unlikely but handle it
    if google_year and ol_year:
        if abs(google_year - ol_year) <= 1:
            return f"{google_year}-01-01"
        best = max(google_year, ol_year)
        return f"{best}-01-01"

    return hc_date


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
    if filename.startswith("google_"):
        return "google"
    if filename.startswith("openlibrary_"):
        return "openlibrary"
    if filename.startswith("cover_"):
        return "legacy_remote"
    return "unknown"


class ScanStatus:
    def __init__(self):
        self.status: str = "idle"
        self.progress: float = 0.0
        self.message: str = ""

    def to_dict(self) -> dict:
        return {"status": self.status, "progress": self.progress, "message": self.message}


scan_status = ScanStatus()


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


async def run_full_sync(force: bool = False):
    """Run a library sync. Incremental by default; force=True refreshes all authors."""
    if scan_status.status == "scanning":
        return

    scan_status.status = "scanning"
    scan_status.progress = 0.0
    scan_status.message = "Starting scan..."

    try:
        async with async_session() as db:
            # Phase 1: Fast filesystem change detection
            scan_status.message = "Scanning filesystem..."
            scan_status.progress = 5.0
            scan_result = await scan_library(db, BOOKS_DIR)
            logger.info(
                "Scan result: %d new, %d deleted, %d unchanged, new authors: %s",
                len(scan_result.new_files), len(scan_result.deleted_files),
                scan_result.unchanged_files,
                scan_result.new_author_names or "(none)",
            )
            scan_status.progress = 20.0

            # If no changes and not forced, we can skip Hardcover phases
            has_changes = bool(scan_result.new_files or scan_result.deleted_files)
            if not has_changes and not force:
                logger.info("No filesystem changes detected — skipping Hardcover sync")
                scan_status.message = "No changes detected."
                scan_status.progress = 100.0
                scan_status.status = "idle"
                await _update_last_scan(db)
                return

            # Get API key
            api_key = await get_api_key(db)
            if not api_key:
                scan_status.message = "No Hardcover API key configured. Scan complete (local only)."
                scan_status.progress = 100.0
                scan_status.status = "idle"
                await _update_last_scan(db)
                return

            client = HardcoverClient(api_key)
            try:
                # Phase 2: Match new authors to Hardcover
                scan_status.message = "Matching authors to Hardcover..."
                result = await db.execute(select(Author))
                authors = result.scalars().all()
                total_authors = len(authors)

                new_author_count = 0
                for i, author in enumerate(authors):
                    if not author.hardcover_id:
                        new_author_count += 1
                        scan_status.message = f"Looking up author: {author.name}"
                        hc_author = await client.search_author(author.name)
                        if hc_author:
                            author.hardcover_id = hc_author.id
                            author.hardcover_slug = hc_author.slug
                            author.bio = hc_author.bio
                            author.image_url = hc_author.image_url

                            if hc_author.image_url:
                                cached = await cache_author_image(hc_author.id, hc_author.image_url)
                                if cached:
                                    author.image_cached_path = cached

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

                    scan_status.message = f"Fetching books for: {author.name}"
                    hc_books = await client.get_author_books(author.hardcover_id)

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
                                book.ol_edition_key = None
                                book.ol_first_publish_year = None
                                book.ol_cover_url = None
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

                # Phase 4: Match local files to Hardcover books (only unmatched)
                scan_status.message = "Matching local files to Hardcover books..."
                result = await db.execute(select(BookFile).where(BookFile.book_id.is_(None)))
                unmatched_files = result.scalars().all()

                matched_count = 0
                for bf in unmatched_files:
                    author_result = await db.execute(
                        select(Author).where(Author.name == bf.opf_author)
                    )
                    author = author_result.scalar_one_or_none()
                    if not author:
                        continue

                    books_result = await db.execute(
                        select(Book).where(Book.author_id == author.id)
                    )
                    author_books = books_result.scalars().all()

                    matched_book = None

                    # Strategy 1: ISBN match
                    if bf.opf_isbn:
                        for book in author_books:
                            if book.isbn and book.isbn == bf.opf_isbn:
                                matched_book = book
                                break

                    # Strategy 2: Title match
                    if not matched_book and bf.opf_title:
                        for book in author_books:
                            if titles_match(bf.opf_title, book.title):
                                matched_book = book
                                break

                    if matched_book:
                        bf.book_id = matched_book.id
                        matched_book.is_owned = True
                        if bf.opf_isbn and not matched_book.isbn:
                            matched_book.isbn = bf.opf_isbn
                            # ISBN gained — clear negative cache for retry
                            # (ISBN lookups are far more precise)
                            if matched_book.google_id == "_none":
                                matched_book.google_id = None
                            if matched_book.ol_edition_key == "_none":
                                matched_book.ol_edition_key = None
                            matched_book.publish_date_checked_at = None
                        matched_count += 1
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
                        bf.book_id = local_book.id

                await db.commit()
                if unmatched_files:
                    logger.info("Matched %d/%d unmatched file(s)", matched_count, len(unmatched_files))
                scan_status.progress = 80.0

                # Phase 5: Year reconciliation
                # Source priority: Hardcover → Google Books → Open Library
                # Google is secondary (if API key available), OL is tiebreaker only
                scan_status.message = "Reconciling publish dates..."
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
                    # publish date checked yet. Once a book's date has been
                    # reconciled, we do not revisit it unless its core metadata
                    # changes and clears publish_date_checked_at.
                    if google_api_key and books_to_reconcile:
                        # Load cached Google data for books already searched.
                        # google_id="_none" means "searched, no result" — skip
                        # unless force=True (user wants full re-fetch).
                        books_need_google = []
                        for book in books_to_reconcile:
                            if book.google_id == "_none" and not force:
                                pass  # Negative cache — skip unless forced
                            elif book.google_id and book.google_id != "_none":
                                # Positive cache — reconstruct GBook from DB
                                google_data[book.id] = GBook(
                                    title=book.title,
                                    published_date=book.google_published_date,
                                    cover_url=book.google_cover_url,
                                    google_id=book.google_id,
                                )
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
                                        if book.isbn:
                                            gbook = await google_client.search_by_isbn(book.isbn)
                                        if not gbook:
                                            author_name = author_map.get(book.author_id, "")
                                            gbook = await google_client.search_by_title_author(
                                                book.title, author_name
                                            )
                                        if gbook:
                                            google_data[book.id] = gbook
                                            # Persist Google data to DB
                                            book.google_id = gbook.google_id
                                            book.google_published_date = gbook.published_date
                                            book.google_cover_url = gbook.cover_url
                                            fetched += 1
                                        else:
                                            # Mark as searched so we don't retry
                                            book.google_id = "_none"
                                    except GoogleBooksThrottledError:
                                        throttled = True
                                        google_retry_ids.update(
                                            pending_book.id for pending_book in books_need_google[i:]
                                        )
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

                    # 5b: Identify books needing OL tiebreaker
                    # Determine which books need OL data for year reconciliation
                    ol_candidates = []
                    if google_api_key and books_to_reconcile:
                        # With Google: only need OL for HC/Google year disagreements
                        for book in books_to_reconcile:
                            hc_year = _extract_year(book.release_date)
                            gbook = google_data.get(book.id)
                            g_year = gbook.publish_year if gbook else None
                            if hc_year and g_year and abs(hc_year - g_year) > 1:
                                ol_candidates.append(book)
                        if ol_candidates:
                            logger.info(
                                "Year disagreements: %d book(s) need OL tiebreaker",
                                len(ol_candidates),
                            )
                    else:
                        # No Google key: fall back to HC vs OL for unchecked books
                        ol_candidates = list(books_to_reconcile)

                    # Load cached OL data; only fetch books not yet searched.
                    # ol_edition_key="_none" means "searched, no result" — skip
                    # unless force=True.
                    books_need_ol_fetch = []
                    for book in ol_candidates:
                        if book.ol_edition_key == "_none" and not force:
                            pass  # Negative cache — skip unless forced
                        elif book.ol_edition_key and book.ol_edition_key != "_none":
                            # Positive cache — reconstruct OLBook from persisted data
                            ol_data[book.id] = OLBook(
                                title=book.title,
                                first_publish_year=book.ol_first_publish_year,
                                cover_id=_extract_ol_cover_id(book.ol_cover_url),
                            )
                        else:
                            books_need_ol_fetch.append(book)

                    if books_need_ol_fetch:
                        ol_cached = len(ol_candidates) - len(books_need_ol_fetch)
                        scan_status.message = (
                            f"Verifying {len(books_need_ol_fetch)} date(s) with Open Library... "
                            f"({ol_cached} cached)"
                        )
                        ol_client = OpenLibraryClient()
                        try:
                            sem = asyncio.Semaphore(10)

                            async def _fetch_ol_year(book):
                                async with sem:
                                    try:
                                        if book.isbn:
                                            result = await ol_client.search_book_by_isbn(book.isbn)
                                            if result:
                                                return result
                                        author_name = author_map.get(book.author_id, "")
                                        return await ol_client.search_book(book.title, author_name)
                                    except Exception as e:
                                        logger.warning(
                                            "Open Library lookup failed for '%s': %s",
                                            book.title[:50], e,
                                        )
                                        return None

                            results = await asyncio.gather(
                                *[_fetch_ol_year(b) for b in books_need_ol_fetch]
                            )
                            fetched_ol = 0
                            for book, ol_book in zip(books_need_ol_fetch, results):
                                if ol_book:
                                    ol_data[book.id] = ol_book
                                    # Persist OL data to DB
                                    book.ol_edition_key = ol_book.cover_edition_key or "_found"
                                    book.ol_first_publish_year = ol_book.first_publish_year
                                    if ol_book.cover_id:
                                        book.ol_cover_url = ol_book.cover_url_large
                                    fetched_ol += 1
                                else:
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

                    # 5c: Apply reconciled dates
                    reconciled = 0
                    finalized = 0
                    for book in books_to_reconcile:
                        if book.id in google_retry_ids:
                            continue
                        gbook = google_data.get(book.id)
                        g_year = gbook.publish_year if gbook else None
                        ol_book = ol_data.get(book.id)
                        ol_year = ol_book.first_publish_year if ol_book else None

                        new_date = _reconcile_year_3way(book.release_date, g_year, ol_year)
                        if new_date and new_date != book.release_date:
                            logger.info(
                                "Date fix: '%s' %s -> %s (Google: %s, OL: %s)",
                                book.title, book.release_date, new_date, g_year, ol_year,
                            )
                            book.release_date = new_date
                            reconciled += 1
                        book.publish_date_checked_at = datetime.utcnow()
                        finalized += 1

                    if books_to_reconcile:
                        await db.commit()
                        if reconciled:
                            logger.info("Reconciled %d publish date(s)", reconciled)
                        logger.info(
                            "Publish dates finalized for %d book(s); future scans will skip them",
                            finalized,
                        )
                        if google_retry_ids:
                            logger.warning(
                                "Left %d book(s) unchecked so a later scan can retry Google Books",
                                len(google_retry_ids),
                            )
                    else:
                        logger.info("Publish dates already finalized for all books; skipping phase 5")

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

                # Track cover heights in memory to avoid re-reading cached files
                cover_heights = {}
                cover_sources = {}
                for book in all_books:
                    cover_heights[book.id] = get_cached_cover_height(
                        book.cover_image_cached_path
                    )
                    cover_sources[book.id] = _get_cached_cover_source(
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
                        dims = get_image_dimensions(data)
                        new_height = dims[1] if dims else 0
                        current_source = cover_sources.get(book.id)
                        current_height = cover_heights.get(book.id, 0)
                        should_replace = current_source in {None, "legacy_remote", "google", "openlibrary"}
                        if should_replace or new_height > current_height:
                            path = cache_cover_data(data, book.id, "hardcover")
                            if path:
                                book.cover_image_cached_path = path
                                cover_heights[book.id] = new_height
                                cover_sources[book.id] = "hardcover"
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
                            dims = get_image_dimensions(data)
                            new_height = dims[1] if dims else 0
                            if new_height > cover_heights.get(book.id, 0):
                                path = cache_cover_data(data, book.id, "google")
                                if path:
                                    book.cover_image_cached_path = path
                                    cover_heights[book.id] = new_height
                                    cover_sources[book.id] = "google"
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
                            pass  # Already in memory from Phase 5
                        elif book.ol_edition_key == "_none" and not force:
                            pass  # Negative cache — skip unless forced
                        elif book.ol_edition_key and book.ol_edition_key != "_none":
                            # Positive cache — reconstruct from DB
                            ol_data[book.id] = OLBook(
                                title=book.title,
                                first_publish_year=book.ol_first_publish_year,
                                cover_id=_extract_ol_cover_id(book.ol_cover_url),
                            )
                        else:
                            books_need_ol_search.append(book)

                    if books_need_ol_search:
                        ol_cover_map = {a.id: a.name for a in authors}
                        ol_client2 = OpenLibraryClient()
                        try:
                            sem = asyncio.Semaphore(10)

                            async def _fetch_ol_cover(book):
                                async with sem:
                                    try:
                                        if book.isbn:
                                            result = await ol_client2.search_book_by_isbn(
                                                book.isbn
                                            )
                                            if result:
                                                return result
                                        author_name = ol_cover_map.get(book.author_id, "")
                                        return await ol_client2.search_book(
                                            book.title, author_name
                                        )
                                    except Exception as e:
                                        logger.warning(
                                            "OL cover lookup failed for '%s': %s",
                                            book.title[:50], e,
                                        )
                                        return None

                            results = await asyncio.gather(
                                *[_fetch_ol_cover(b) for b in books_need_ol_search]
                            )
                            for book, ol_book in zip(books_need_ol_search, results):
                                if ol_book:
                                    ol_data[book.id] = ol_book
                                    # Persist OL data to DB
                                    book.ol_edition_key = ol_book.cover_edition_key or "_found"
                                    book.ol_first_publish_year = ol_book.first_publish_year
                                    if ol_book.cover_id:
                                        book.ol_cover_url = ol_book.cover_url_large
                                else:
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
                                path = cache_cover_data(data, book.id, "openlibrary")
                                if path:
                                    book.cover_image_cached_path = path
                                    ol_covers += 1

                    await db.commit()
                    if ol_covers:
                        logger.info("Cached %d cover(s) from Open Library", ol_covers)

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

            finally:
                await client.close()

            await _update_last_scan(db)

        scan_status.progress = 100.0
        scan_status.message = "Scan complete!"
        scan_status.status = "idle"

    except Exception as e:
        logger.exception("Sync failed: %s", e)
        scan_status.message = f"Error: {str(e)}"
        scan_status.status = "idle"
        scan_status.progress = 0.0


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
    now = datetime.utcnow().isoformat()
    if setting:
        setting.value = now
    else:
        db.add(Setting(key="last_scan_at", value=now))
    await db.commit()
