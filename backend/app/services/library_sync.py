import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import BOOKS_DIR
from backend.app.database import async_session
from backend.app.models import Author, Book, BookFile, BookSeries, Series, Setting
from backend.app.services.scanner import scan_library
from backend.app.services.hardcover import HardcoverClient
from backend.app.services.matcher import titles_match
from backend.app.services.image_cache import cache_author_image, cache_book_image, cache_local_cover

logger = logging.getLogger("booksarr.sync")

# Authors synced within this window are skipped on incremental scans
SYNC_COOLDOWN_HOURS = 168  # 7 days


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
            # Phase 1: Filesystem scan (always runs — fast local IO)
            scan_status.message = "Scanning filesystem..."
            scan_status.progress = 5.0
            stats = await scan_library(db, BOOKS_DIR)
            logger.info("Scan stats: %s", stats)
            scan_status.progress = 15.0

            # Phase 1b: Clean up deleted files
            scan_status.message = "Checking for removed files..."
            removed = await _cleanup_deleted_files(db)
            if removed:
                logger.info("Cleaned up %d removed file(s)", removed)
            scan_status.progress = 20.0

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
                # Phase 2: Match authors to Hardcover (only new authors)
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

                # Phase 3: Fetch books from Hardcover (incremental)
                cutoff = datetime.utcnow() - timedelta(hours=SYNC_COOLDOWN_HOURS)
                scan_status.message = "Fetching books from Hardcover..."
                authors_synced = 0
                authors_skipped = 0

                for i, author in enumerate(authors):
                    if not author.hardcover_id:
                        continue

                    # Skip recently synced authors unless force
                    if not force and author.last_synced_at and author.last_synced_at > cutoff:
                        authors_skipped += 1
                        progress = 50.0 + (25.0 * (i + 1) / max(total_authors, 1))
                        scan_status.progress = progress
                        continue

                    scan_status.message = f"Fetching books for: {author.name}"
                    hc_books = await client.get_author_books(author.hardcover_id)

                    # Filter to canonical books only (skip translations/alternate editions)
                    canonical_books = [b for b in hc_books if b.is_canonical]
                    author.book_count_total = len(canonical_books)
                    authors_synced += 1
                    if len(hc_books) != len(canonical_books):
                        logger.info(
                            "Author %s: %d total, %d canonical (skipped %d non-canonical)",
                            author.name, len(hc_books), len(canonical_books),
                            len(hc_books) - len(canonical_books),
                        )

                    for hc_book in canonical_books:
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
                    "Hardcover sync: %d author(s) fetched, %d skipped (recently synced)",
                    authors_synced, authors_skipped,
                )

                # Phase 4: Match local files to Hardcover books
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


async def _cleanup_deleted_files(db: AsyncSession) -> int:
    """Remove BookFile records for files no longer on disk and update ownership."""
    result = await db.execute(select(BookFile))
    all_files = result.scalars().all()
    removed = 0

    for bf in all_files:
        full_path = BOOKS_DIR / bf.file_path
        if not full_path.exists():
            book_id = bf.book_id
            await db.delete(bf)
            removed += 1

            # If this was the last file for a book, mark it not owned
            if book_id:
                remaining = await db.execute(
                    select(func.count(BookFile.id)).where(
                        BookFile.book_id == book_id,
                        BookFile.id != bf.id,
                    )
                )
                if remaining.scalar() == 0:
                    book_result = await db.execute(select(Book).where(Book.id == book_id))
                    book = book_result.scalar_one_or_none()
                    if book:
                        if book.hardcover_id:
                            book.is_owned = False
                        else:
                            await db.delete(book)

    if removed:
        await db.commit()
    return removed


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
