from pathlib import Path

import pytest

from backend.app.models import Author, Book, BookFile
from backend.app.services import irc_worker, library_sync


@pytest.mark.asyncio
async def test_trigger_library_scan_after_irc_import_refreshes_immediately_when_idle(monkeypatch):
    calls: list[tuple[Path, int | None]] = []

    async def fake_refresh(moved_path: Path, job_id: int | None = None):
        calls.append((moved_path, job_id))

    monkeypatch.setattr(library_sync.scan_status, "status", "idle")
    monkeypatch.setattr(irc_worker, "_refresh_library_state_for_import", fake_refresh)

    moved_path = Path("/books/Nir Eyal/Indistractable/Indistractable.epub")
    await irc_worker._trigger_library_scan_after_irc_import(moved_path, job_id=238)

    assert calls == [(moved_path, 238)]
    assert not irc_worker._pending_import_refresh_tasks


@pytest.mark.asyncio
async def test_repair_local_file_links_honors_expected_book_id_for_mislinked_hardcover_book(
    db_session,
    monkeypatch,
    tmp_path,
):
    author_selected = Author(name="Nir   Eyal")
    author_wrong = Author(name="Nir Eyal")
    db_session.add_all([author_selected, author_wrong])
    await db_session.flush()

    selected_book = Book(
        title="Indistractable: How to Control Your Attention and Choose Your Life",
        author_id=author_selected.id,
        hardcover_id=427787,
        hardcover_isbn_13="9781948836531",
        is_owned=False,
    )
    wrong_book = Book(
        title="Indistractable",
        author_id=author_wrong.id,
        hardcover_id=475267,
        hardcover_isbn_13="9781526610201",
        is_owned=True,
    )
    db_session.add_all([selected_book, wrong_book])
    await db_session.flush()

    relative_path = (
        "Nir Eyal/Indistractable How to Control Your Attention and Choose Your Life/"
        "Nir Eyal, Julie Li - Indistractable- How to Control Your Attention and Choose Your Life (Retail).epub"
    )
    book_path = tmp_path / relative_path
    book_path.parent.mkdir(parents=True, exist_ok=True)
    book_path.write_text("placeholder", encoding="utf-8")

    db_session.add(
        BookFile(
            file_path=relative_path,
            file_name=book_path.name,
            book_id=wrong_book.id,
            opf_title="Indistractable",
            opf_author="Nir Eyal",
            opf_isbn="9781526610201",
        )
    )
    await db_session.commit()

    class StubMetadata:
        title = "Indistractable"
        author = "Nir Eyal"
        isbn = "9781526610201"
        series = None
        series_index = None
        publisher = None
        description = None

    monkeypatch.setattr(library_sync, "BOOKS_DIR", tmp_path)
    monkeypatch.setattr(library_sync, "extract_best_metadata", lambda *_args, **_kwargs: StubMetadata())

    matched_count, repaired_count, books_added = await library_sync._repair_local_file_links(
        db_session,
        file_paths={relative_path},
        expected_book_ids={relative_path: selected_book.id},
    )

    refreshed_file = await db_session.get(BookFile, 1)
    refreshed_selected = await db_session.get(Book, selected_book.id)
    refreshed_wrong = await db_session.get(Book, wrong_book.id)

    assert matched_count == 1
    assert repaired_count == 1
    assert books_added == 0
    assert refreshed_file.book_id == selected_book.id
    assert refreshed_selected.is_owned is True
    assert refreshed_wrong.is_owned is False


@pytest.mark.asyncio
async def test_repair_local_file_links_prefers_canonical_author_for_normalized_name_match(
    db_session,
    monkeypatch,
    tmp_path,
):
    author_selected = Author(name="Nir   Eyal", book_count_local=1, book_count_total=13)
    author_wrong = Author(name="Nir Eyal", book_count_local=0, book_count_total=6)
    db_session.add_all([author_selected, author_wrong])
    await db_session.flush()

    selected_book = Book(
        title="Indistractable: How to Control Your Attention and Choose Your Life",
        author_id=author_selected.id,
        hardcover_id=427787,
        hardcover_isbn_13="9781948836531",
        is_owned=True,
    )
    wrong_book = Book(
        title="Indistractable",
        author_id=author_wrong.id,
        hardcover_id=475267,
        hardcover_isbn_13="9781526610201",
        is_owned=False,
    )
    db_session.add_all([selected_book, wrong_book])
    await db_session.flush()

    relative_path = (
        "Nir Eyal/Indistractable How to Control Your Attention and Choose Your Life/"
        "Eyal, Nir - Indistractable How to Control Your Attention and Choose Your Life (audiobook).zip"
    )
    book_path = tmp_path / relative_path
    book_path.parent.mkdir(parents=True, exist_ok=True)
    book_path.write_text("placeholder", encoding="utf-8")

    db_session.add(
        BookFile(
            file_path=relative_path,
            file_name=book_path.name,
            book_id=None,
            file_format="audiobook",
            opf_title="Indistractable How to Control Your Attention and Choose Your Life",
            opf_author="Nir Eyal",
            opf_isbn=None,
        )
    )
    await db_session.commit()

    class StubMetadata:
        title = "Indistractable How to Control Your Attention and Choose Your Life"
        author = "Nir Eyal"
        isbn = None
        series = None
        series_index = None
        publisher = None
        description = None

    monkeypatch.setattr(library_sync, "BOOKS_DIR", tmp_path)
    monkeypatch.setattr(library_sync, "extract_best_metadata", lambda *_args, **_kwargs: StubMetadata())

    matched_count, repaired_count, books_added = await library_sync._repair_local_file_links(
        db_session,
        file_paths={relative_path},
    )

    refreshed_file = await db_session.get(BookFile, 1)

    assert matched_count == 1
    assert repaired_count == 0
    assert books_added == 0
    assert refreshed_file.book_id == selected_book.id


@pytest.mark.asyncio
async def test_repair_local_file_links_prefers_shown_sibling_book_in_same_folder(
    db_session,
    monkeypatch,
    tmp_path,
):
    author = Author(name="Dan Brown")
    db_session.add(author)
    await db_session.flush()

    hidden_book = Book(
        title="Angels and Demons",
        author_id=author.id,
        hardcover_id=201,
        hardcover_isbn_13="9780000000201",
        manual_visibility="hidden",
        is_owned=True,
    )
    shown_book = Book(
        title="Angels & Demons",
        author_id=author.id,
        hardcover_id=202,
        hardcover_isbn_13="9780000000202",
        is_owned=True,
    )
    db_session.add_all([hidden_book, shown_book])
    await db_session.flush()

    epub_path = (
        "Dan Brown/Angels & Demons/"
        "Dan Brown - Angels & Demons.epub"
    )
    audio_path = (
        "Dan Brown/Angels & Demons/"
        "Brown, Dan - Angels and Demons (audiobook).zip"
    )
    (tmp_path / epub_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / epub_path).write_text("epub", encoding="utf-8")
    (tmp_path / audio_path).write_text("audio", encoding="utf-8")

    db_session.add_all([
        BookFile(
            file_path=epub_path,
            file_name="Dan Brown - Angels & Demons.epub",
            book_id=shown_book.id,
            file_format="epub",
            opf_title="Angels & Demons",
            opf_author="Dan Brown",
            opf_isbn="9780000000202",
        ),
        BookFile(
            file_path=audio_path,
            file_name="Brown, Dan - Angels and Demons (audiobook).zip",
            book_id=hidden_book.id,
            file_format="audiobook",
            opf_title="Angels and Demons",
            opf_author="Dan Brown",
            opf_isbn="9780000000201",
        ),
    ])
    await db_session.commit()

    class AudioStubMetadata:
        title = "Angels and Demons"
        author = "Dan Brown"
        isbn = "9780000000201"
        series = None
        series_index = None
        publisher = None
        description = None

    monkeypatch.setattr(library_sync, "BOOKS_DIR", tmp_path)
    monkeypatch.setattr(library_sync, "extract_best_metadata", lambda *_args, **_kwargs: AudioStubMetadata())

    matched_count, repaired_count, books_added = await library_sync._repair_local_file_links(
        db_session,
        file_paths={audio_path},
    )

    refreshed_audio = (
        await db_session.execute(select(BookFile).where(BookFile.file_path == audio_path))
    ).scalar_one()
    refreshed_hidden = await db_session.get(Book, hidden_book.id)
    refreshed_shown = await db_session.get(Book, shown_book.id)

    assert matched_count == 1
    assert repaired_count == 1
    assert books_added == 0
    assert refreshed_audio.book_id == shown_book.id
    assert refreshed_shown.is_owned is True
    assert refreshed_hidden.is_owned is False


@pytest.mark.asyncio
async def test_trigger_library_scan_after_irc_import_waits_for_active_scan(monkeypatch):
    calls: list[tuple[Path, int | None]] = []
    original_sleep = irc_worker.asyncio.sleep

    async def fake_refresh(moved_path: Path, job_id: int | None = None):
        calls.append((moved_path, job_id))

    async def fake_sleep(_seconds: float):
        monkeypatch.setattr(library_sync.scan_status, "status", "idle")
        await original_sleep(0)

    monkeypatch.setattr(library_sync.scan_status, "status", "scanning")
    monkeypatch.setattr(irc_worker, "_refresh_library_state_for_import", fake_refresh)
    monkeypatch.setattr(irc_worker.asyncio, "sleep", fake_sleep)

    moved_path = Path("/books/Nir Eyal/Indistractable/Indistractable.epub")
    await irc_worker._trigger_library_scan_after_irc_import(moved_path, job_id=238)

    assert len(irc_worker._pending_import_refresh_tasks) == 1
    task = next(iter(irc_worker._pending_import_refresh_tasks.values()))
    await task

    assert calls == [(moved_path, 238)]
    assert not irc_worker._pending_import_refresh_tasks
