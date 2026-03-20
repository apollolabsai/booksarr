import json
import logging
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import BOOKS_DIR
from backend.app.database import async_session
from backend.app.models import Author, Book, BookFile, BookSeries, Series, Setting
from backend.app.services.scanner import scan_library, ScanResult
from backend.app.services.hardcover import HardcoverClient
from backend.app.services.matcher import titles_match
from backend.app.services.image_cache import cache_author_image, cache_book_image, cache_local_cover

import re
import unicodedata

logger = logging.getLogger("booksarr.sync")

# Articles to strip when comparing titles for deduplication
_ARTICLE_RE = re.compile(r"^(a|an|the)\s+", re.IGNORECASE)


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
    """Deduplicate books using two strategies:
    1. Normalized title match (catches 'A Time for Mercy' vs 'Time for Mercy')
    2. Same series + same position (catches 'The Exchange' vs 'The Exchange After the Firm')
    In both cases, the book with the best metadata (users_count, rating, etc.) wins.
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
    # Books sharing the same series and position are almost certainly duplicates
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
    result = list(no_series)
    for key, group in series_groups.items():
        if len(group) == 1:
            if group[0].id not in seen_ids:
                result.append(group[0])
                seen_ids.add(group[0].id)
        else:
            group.sort(key=_metadata_score, reverse=True)
            if group[0].id not in seen_ids:
                result.append(group[0])
                seen_ids.add(group[0].id)
            total_removed += len(group) - 1
            logger.debug(
                "Dedup (series): kept '%s' (hc=%d, users=%d), dropped %d variant(s) at series %s pos %s",
                group[0].title, group[0].id, group[0].users_count,
                len(group) - 1, key[0], key[1],
            )

    if total_removed:
        logger.info("Deduplicated %d book(s) total", total_removed)
    return result



class ScanStatus:
    def __init__(self):
        self.status: str = "idle"
        self.progress: float = 0.0
        self.message: str = ""

    def to_dict(self) -> dict:
        return {"status": self.status, "progress": self.progress, "message": self.message}


scan_status = ScanStatus()


async def get_api_key(db: AsyncSession) -> str:
    """Get API key from env var (via config) or database settings."""
    from backend.app.config import HARDCOVER_API_KEY
    if HARDCOVER_API_KEY:
        return HARDCOVER_API_KEY

    result = await db.execute(select(Setting).where(Setting.key == "hardcover_api_key"))
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
                            book.title = hc_book.title
                            book.description = hc_book.description
                            book.release_date = hc_book.release_date
                            book.cover_image_url = hc_book.image_url
                            book.tags = tags_json
                            book.rating = hc_book.rating
                            book.pages = hc_book.pages
                            book.hardcover_slug = hc_book.slug
                            book.language = hc_book.language or book.language
                        else:
                            book = Book(
                                title=hc_book.title,
                                author_id=author.id,
                                hardcover_id=hc_book.id,
                                hardcover_slug=hc_book.slug,
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
                scan_status.progress = 85.0

                # Phase 5: Cache book cover images (only uncached)
                scan_status.message = "Caching book covers..."
                result = await db.execute(
                    select(Book).where(
                        Book.cover_image_url.isnot(None),
                        Book.cover_image_cached_path.is_(None),
                        Book.hardcover_id.isnot(None),
                    )
                )
                books_needing_covers = result.scalars().all()
                total_covers = len(books_needing_covers)

                for i, book in enumerate(books_needing_covers):
                    cached = await cache_book_image(book.hardcover_id, book.cover_image_url)
                    if cached:
                        book.cover_image_cached_path = cached
                    if (i + 1) % 50 == 0:
                        await db.commit()
                        scan_status.progress = 85.0 + (10.0 * (i + 1) / max(total_covers, 1))

                # Cache local covers for unmatched books
                result = await db.execute(
                    select(Book).where(
                        Book.hardcover_id.is_(None),
                        Book.cover_image_cached_path.is_(None),
                    )
                )
                local_books = result.scalars().all()
                for book in local_books:
                    if book.files:
                        for bf in book.files:
                            if bf.local_cover_path:
                                cached = cache_local_cover(bf.local_cover_path, book.id)
                                if cached:
                                    book.cover_image_cached_path = cached
                                break

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
