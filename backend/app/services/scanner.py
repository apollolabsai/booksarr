import logging
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Author, BookFile
from backend.app.utils.opf_parser import parse_opf

logger = logging.getLogger("booksarr.scanner")

EBOOK_EXTENSIONS = {".epub"}


async def scan_library(db: AsyncSession, library_path: Path) -> dict:
    """Scan the library directory for ebook files and metadata."""
    stats = {"authors_found": 0, "files_found": 0, "files_new": 0, "files_updated": 0}

    if not library_path.exists():
        logger.warning("Library path does not exist: %s", library_path)
        return stats

    logger.info("Starting library scan at: %s", library_path)

    # Walk the library directory
    for author_dir in sorted(library_path.iterdir()):
        if not author_dir.is_dir() or author_dir.name.startswith("."):
            continue

        author_name = author_dir.name
        author = await _get_or_create_author(db, author_name)
        stats["authors_found"] += 1

        for book_dir in sorted(author_dir.iterdir()):
            if not book_dir.is_dir() or book_dir.name.startswith("."):
                continue

            # Find ebook files
            ebook_files = [
                f for f in book_dir.iterdir()
                if f.is_file() and f.suffix.lower() in EBOOK_EXTENSIONS
            ]

            if not ebook_files:
                continue

            # Parse OPF metadata if available
            opf_path = book_dir / "metadata.opf"
            opf = parse_opf(opf_path) if opf_path.exists() else None

            # Check for cover
            cover_path = book_dir / "cover.jpg"
            local_cover = str(cover_path) if cover_path.exists() else None

            for ebook_file in ebook_files:
                rel_path = str(ebook_file.relative_to(library_path))
                stats["files_found"] += 1

                # Check if file already exists in DB
                result = await db.execute(
                    select(BookFile).where(BookFile.file_path == rel_path)
                )
                existing = result.scalar_one_or_none()

                file_size = ebook_file.stat().st_size

                if existing:
                    existing.file_size = file_size
                    existing.last_scanned_at = datetime.utcnow()
                    if opf:
                        existing.opf_title = opf.title
                        existing.opf_author = opf.author or author_name
                        existing.opf_isbn = opf.isbn or None
                        existing.opf_series = opf.series or None
                        existing.opf_series_index = opf.series_index
                        existing.opf_publisher = opf.publisher or None
                        existing.opf_description = opf.description or None
                        existing.local_cover_path = local_cover
                    stats["files_updated"] += 1
                else:
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
                    stats["files_new"] += 1

    await db.commit()
    logger.info(
        "Scan complete: %d authors, %d files found (%d new, %d updated)",
        stats["authors_found"], stats["files_found"], stats["files_new"], stats["files_updated"],
    )
    return stats


async def _get_or_create_author(db: AsyncSession, name: str) -> Author:
    result = await db.execute(select(Author).where(Author.name == name))
    author = result.scalar_one_or_none()
    if not author:
        author = Author(name=name)
        db.add(author)
        await db.flush()
    return author
