import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Author, Book, BookFile
from backend.app.utils.opf_parser import parse_opf

logger = logging.getLogger("booksarr.scanner")

EBOOK_EXTENSIONS = {".epub"}


class ScanResult:
    """Result of a filesystem scan with change detection."""

    def __init__(self):
        self.new_files: list[str] = []          # relative paths of newly added files
        self.deleted_files: list[str] = []      # relative paths of removed files
        self.new_author_names: set[str] = set() # author folder names seen for the first time
        self.total_files: int = 0
        self.unchanged_files: int = 0


async def scan_library(db: AsyncSession, library_path: Path) -> ScanResult:
    """Scan the library directory using fast set-diff change detection.

    Instead of checking every file against the DB individually, we:
    1. Load all known file_path values from BookFile into a set (single query)
    2. Walk the filesystem and collect current paths
    3. Compute new = current - known, deleted = known - current
    4. Only create BookFile records and parse OPF for new files
    """
    result = ScanResult()

    if not library_path.exists():
        logger.warning("Library path does not exist: %s", library_path)
        return result

    logger.info("Starting library scan at: %s", library_path)

    # Step 1: Load all known file paths from DB in one query
    db_result = await db.execute(select(BookFile.file_path))
    known_paths: set[str] = {row[0] for row in db_result.all()}
    logger.info("Known files in DB: %d", len(known_paths))

    # Also load known author names
    author_result = await db.execute(select(Author.name))
    known_authors: set[str] = {row[0] for row in author_result.all()}

    # Step 2: Walk filesystem and collect current paths + metadata
    current_paths: set[str] = set()
    # Map rel_path -> (author_name, book_dir) for new files only
    file_context: dict[str, tuple[str, Path]] = {}

    for author_dir in sorted(library_path.iterdir()):
        if not author_dir.is_dir() or author_dir.name.startswith("."):
            continue

        author_name = author_dir.name

        for book_dir in sorted(author_dir.iterdir()):
            if not book_dir.is_dir() or book_dir.name.startswith("."):
                continue

            ebook_files = [
                f for f in book_dir.iterdir()
                if f.is_file() and f.suffix.lower() in EBOOK_EXTENSIONS
            ]

            for ebook_file in ebook_files:
                rel_path = str(ebook_file.relative_to(library_path))
                current_paths.add(rel_path)
                if rel_path not in known_paths:
                    file_context[rel_path] = (author_name, book_dir)

    result.total_files = len(current_paths)

    # Step 3: Compute diffs
    new_paths = current_paths - known_paths
    deleted_paths = known_paths - current_paths
    result.unchanged_files = len(current_paths & known_paths)
    result.new_files = sorted(new_paths)
    result.deleted_files = sorted(deleted_paths)

    logger.info(
        "Change detection: %d total, %d new, %d deleted, %d unchanged",
        result.total_files, len(new_paths), len(deleted_paths), result.unchanged_files,
    )

    # Step 4: Process deletions — remove BookFile records and update ownership
    if deleted_paths:
        await _process_deletions(db, deleted_paths)

    # Step 5: Process new files — create authors, parse OPF, create BookFile records
    if new_paths:
        for rel_path in sorted(new_paths):
            author_name, book_dir = file_context[rel_path]

            # Track new authors
            if author_name not in known_authors:
                result.new_author_names.add(author_name)

            author = await _get_or_create_author(db, author_name)
            known_authors.add(author_name)  # avoid re-flagging

            ebook_file = library_path / rel_path

            # Parse OPF metadata if available
            opf_path = book_dir / "metadata.opf"
            opf = parse_opf(opf_path) if opf_path.exists() else None

            # Check for cover
            cover_path = book_dir / "cover.jpg"
            local_cover = str(cover_path) if cover_path.exists() else None

            file_size = ebook_file.stat().st_size

            book_file = BookFile(
                file_path=rel_path,
                file_name=ebook_file.name,
                file_size=file_size,
                file_format=ebook_file.suffix.lstrip(".").lower(),
                opf_title=opf.title if opf else ebook_file.stem.split(" - ")[0].strip(),
                opf_author=opf.author if opf else author_name,
                opf_isbn=opf.isbn if opf and opf.isbn else None,
                opf_series=opf.series if opf else None,
                opf_series_index=opf.series_index if opf else None,
                opf_publisher=opf.publisher if opf else None,
                opf_description=opf.description if opf else None,
                local_cover_path=local_cover,
                last_scanned_at=datetime.utcnow(),
            )
            db.add(book_file)

    await db.commit()

    if new_paths or deleted_paths:
        logger.info(
            "Scan complete: %d new file(s) added, %d file(s) removed",
            len(new_paths), len(deleted_paths),
        )
    else:
        logger.info("Scan complete: no changes detected")

    return result


async def _process_deletions(db: AsyncSession, deleted_paths: set[str]):
    """Remove BookFile records for deleted files and update book ownership."""
    from backend.app.config import BOOKS_DIR

    for rel_path in deleted_paths:
        result = await db.execute(
            select(BookFile).where(BookFile.file_path == rel_path)
        )
        bf = result.scalar_one_or_none()
        if not bf:
            continue

        book_id = bf.book_id
        await db.delete(bf)

        # If this was the last file for a book, update ownership
        if book_id:
            remaining = await db.execute(
                select(func.count(BookFile.id)).where(
                    BookFile.book_id == book_id,
                    BookFile.file_path != rel_path,
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

    await db.commit()
    logger.info("Processed %d file deletion(s)", len(deleted_paths))


async def _get_or_create_author(db: AsyncSession, name: str) -> Author:
    result = await db.execute(select(Author).where(Author.name == name))
    author = result.scalar_one_or_none()
    if not author:
        author = Author(name=name)
        db.add(author)
        await db.flush()
    return author
