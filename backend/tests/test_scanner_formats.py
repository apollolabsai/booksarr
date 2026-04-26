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
