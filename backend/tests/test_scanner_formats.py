import logging

import pytest

from backend.app.models import BookFile
from backend.app.services import scanner
from backend.app.services.scanner import _classify_standalone_file, _collect_book_dir_artifacts


def test_scanner_classifies_pdf_as_standalone_book_file(tmp_path):
    pdf_path = tmp_path / "Author Name" / "Book Title.pdf"
    pdf_path.parent.mkdir()
    pdf_path.write_bytes(b"%PDF-1.4")

    assert _classify_standalone_file(pdf_path) == "pdf"


def test_scanner_collects_pdf_book_dir_artifacts(tmp_path):
    book_dir = tmp_path / "Author Name" / "Book Title"
    book_dir.mkdir(parents=True)
    pdf_path = book_dir / "Book Title.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    assert _collect_book_dir_artifacts(book_dir, tmp_path) == [
        ("Author Name/Book Title/Book Title.pdf", "pdf"),
    ]


@pytest.mark.asyncio
async def test_scan_library_reports_filesystem_walk_progress(db_session, tmp_path, monkeypatch, caplog):
    rel_path = "Author Name/Book Title/Book Title.epub"
    book_path = tmp_path / rel_path
    book_path.parent.mkdir(parents=True)
    book_path.write_bytes(b"known")
    db_session.add(BookFile(
        file_path=rel_path,
        file_name="Book Title.epub",
        file_format="epub",
    ))
    await db_session.commit()

    monkeypatch.setattr(scanner, "FILESYSTEM_SCAN_PROGRESS_INTERVAL", 1)
    caplog.set_level(logging.INFO, logger="booksarr.scanner")
    progress = []

    result = await scanner.scan_library(db_session, tmp_path, progress_callback=progress.append)

    assert result.total_files == 1
    assert result.unchanged_files == 1
    assert progress[0].known_files == 1
    assert any(item.artifacts_seen == 1 and item.unchanged_files == 1 for item in progress)
    assert progress[-1].deleted_files == 0
    assert "Filesystem scan progress" in caplog.text
    assert "Filesystem scan complete" in caplog.text
