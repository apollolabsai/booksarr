import logging
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Author, AuthorDirectory, Book, BookFile
from backend.app.utils.opf_parser import OPFMetadata, parse_epub_opf, parse_opf

logger = logging.getLogger("booksarr.scanner")

EBOOK_EXTENSIONS = {".epub"}
_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")
_SERIES_BRACKET_RE = re.compile(r"\s*-\s*\[[^\]]+\]\s*")
_LEADING_SERIES_TOKEN_RE = re.compile(r"^\s*(?:\[[^\]]+\]|\([^)]*\))\s*-\s*")


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
    # Map rel_path -> (author_name, fallback_book_name, standalone_in_author_root)
    file_context: dict[str, tuple[str, str, bool]] = {}

    for author_dir in sorted(library_path.iterdir()):
        if not author_dir.is_dir() or author_dir.name.startswith("."):
            continue

        author_name = _clean_author_text(author_dir.name) or author_dir.name
        author = await _get_or_create_author(db, author_name)
        await _register_author_directory(db, author, author_dir.name)

        # Support standalone ebooks directly inside the author folder.
        for ebook_file in sorted(author_dir.iterdir()):
            if (
                not ebook_file.is_file()
                or ebook_file.name.startswith(".")
                or ebook_file.suffix.lower() not in EBOOK_EXTENSIONS
            ):
                continue

            rel_path = str(ebook_file.relative_to(library_path))
            current_paths.add(rel_path)
            if rel_path not in known_paths:
                file_context[rel_path] = (
                    author_name,
                    _clean_title_text(ebook_file.stem) or ebook_file.stem,
                    True,
                )

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
                    file_context[rel_path] = (author_name, book_dir.name, False)

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
            author_name, fallback_book_name, is_standalone = file_context[rel_path]

            # Track new authors
            if author_name not in known_authors:
                result.new_author_names.add(author_name)

            known_authors.add(author_name)  # avoid re-flagging

            ebook_file = library_path / rel_path

            opf = extract_best_metadata(ebook_file, author_name, fallback_book_name)

            local_cover = _find_local_cover(ebook_file, standalone_in_author_root=is_standalone)

            file_size = ebook_file.stat().st_size

            book_file = BookFile(
                file_path=rel_path,
                file_name=ebook_file.name,
                file_size=file_size,
                file_format=ebook_file.suffix.lstrip(".").lower(),
                opf_title=opf.title or None,
                opf_author=opf.author or author_name,
                opf_isbn=opf.isbn or None,
                opf_series=opf.series or None,
                opf_series_index=opf.series_index,
                opf_publisher=opf.publisher or None,
                opf_description=opf.description or None,
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


async def _register_author_directory(db: AsyncSession, author: Author, dir_name: str):
    result = await db.execute(select(AuthorDirectory).where(AuthorDirectory.dir_path == dir_name))
    author_dir = result.scalar_one_or_none()
    primary_result = await db.execute(
        select(func.count(AuthorDirectory.id)).where(
            AuthorDirectory.author_id == author.id,
            AuthorDirectory.is_primary == True,
        )
    )
    has_primary = bool(primary_result.scalar() or 0)
    if author_dir is None:
        author_dir = AuthorDirectory(
            author_id=author.id,
            dir_path=dir_name,
            is_primary=not has_primary,
            last_seen_at=datetime.utcnow(),
        )
        db.add(author_dir)
        return

    author_dir.author_id = author.id
    author_dir.last_seen_at = datetime.utcnow()
    if not has_primary:
        author_dir.is_primary = True


def extract_best_metadata(ebook_file: Path, author_name: str, book_dir_name: str) -> OPFMetadata:
    opf_path = ebook_file.parent / "metadata.opf"
    named_opf_path = ebook_file.with_suffix(".opf")
    sidecar_meta = parse_opf(opf_path) if opf_path.exists() else None
    if not _has_useful_metadata(sidecar_meta) and named_opf_path.exists():
        sidecar_meta = parse_opf(named_opf_path)
    epub_meta = parse_epub_opf(ebook_file) if ebook_file.suffix.lower() == ".epub" else None
    if _has_useful_metadata(sidecar_meta):
        return _normalize_metadata(sidecar_meta, author_name, book_dir_name, ebook_file)
    if _has_useful_metadata(epub_meta):
        return _normalize_metadata(epub_meta, author_name, book_dir_name, ebook_file)
    return _filename_fallback_metadata(ebook_file, author_name, book_dir_name)


def _has_useful_metadata(meta: OPFMetadata | None) -> bool:
    return bool(meta and (meta.title or meta.author or meta.isbn))


def _normalize_metadata(meta: OPFMetadata, author_name: str, book_dir_name: str, ebook_file: Path) -> OPFMetadata:
    title = _clean_title_text(meta.title or "")
    author = _clean_author_text((meta.author or "").strip()) or author_name
    if not title or title.lower() == author_name.strip().lower():
        fallback = _filename_fallback_metadata(ebook_file, author_name, book_dir_name)
        title = fallback.title
    meta.title = title
    meta.author = author
    return meta


def _filename_fallback_metadata(ebook_file: Path, author_name: str, book_dir_name: str) -> OPFMetadata:
    stem = ebook_file.stem
    stem = _SERIES_BRACKET_RE.sub(" - ", stem)
    parts = [part.strip() for part in stem.split(" - ") if part.strip()]

    title = ""
    if len(parts) >= 2:
        title = parts[-1]
    elif parts:
        title = parts[0]

    title = _clean_title_text(title)

    if not title or title.lower() == author_name.strip().lower():
        title = book_dir_name.strip()
    if not title:
        title = ebook_file.stem

    return OPFMetadata(title=title.strip(), author=author_name.strip())


def _clean_title_text(title: str) -> str:
    cleaned = title.strip()
    while True:
        stripped = _LEADING_SERIES_TOKEN_RE.sub("", cleaned).strip()
        if stripped == cleaned:
            break
        cleaned = stripped

    while True:
        stripped = _TRAILING_PAREN_RE.sub("", cleaned).strip()
        if stripped == cleaned:
            break
        cleaned = stripped

    return cleaned


def _clean_author_text(author: str) -> str:
    cleaned = author.strip()
    if "," in cleaned:
        parts = [part.strip() for part in cleaned.split(",") if part.strip()]
        if len(parts) == 2:
            cleaned = f"{parts[1]} {parts[0]}"
    cleaned = cleaned.rstrip(" ;,")
    return re.sub(r"\s+", " ", cleaned).strip()


def _find_local_cover(ebook_file: Path, standalone_in_author_root: bool) -> str | None:
    if standalone_in_author_root:
        for ext in (".jpg", ".jpeg", ".png"):
            candidate = ebook_file.with_suffix(ext)
            if candidate.exists():
                return str(candidate)
        return None

    for name in ("cover.jpg", "cover.jpeg", "cover.png"):
        candidate = ebook_file.parent / name
        if candidate.exists():
            return str(candidate)

    return None
