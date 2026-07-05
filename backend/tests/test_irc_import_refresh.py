import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from backend.app.models import Author, Book, BookFile, IrcDownloadJob
from backend.app.services import irc_worker, library_sync


class StubMetadata:
    def __init__(
        self,
        *,
        title: str,
        author: str,
        isbn: str | None = None,
        publisher: str | None = None,
        description: str | None = None,
    ):
        self.title = title
        self.author = author
        self.isbn = isbn
        self.series = None
        self.series_index = None
        self.publisher = publisher
        self.description = description


class StubSessionFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


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
async def test_expire_stale_download_jobs_uses_first_byte_timeout(db_session, monkeypatch):
    now = datetime.utcnow()
    stalled_zero_byte_job = IrcDownloadJob(
        status="downloading",
        bytes_downloaded=0,
        updated_at=now - timedelta(
            seconds=irc_worker.IRC_DCC_BOOK_FIRST_BYTE_TIMEOUT_SECONDS + 1
        ),
    )
    active_transfer_job = IrcDownloadJob(
        status="downloading",
        bytes_downloaded=1,
        updated_at=now - timedelta(
            seconds=irc_worker.IRC_DCC_BOOK_FIRST_BYTE_TIMEOUT_SECONDS + 1
        ),
    )
    waiting_offer_job = IrcDownloadJob(
        status="waiting_dcc",
        updated_at=now - timedelta(seconds=irc_worker.IRC_DCC_WAIT_TIMEOUT_SECONDS + 1),
    )
    db_session.add_all([stalled_zero_byte_job, active_transfer_job, waiting_offer_job])
    await db_session.commit()

    monkeypatch.setattr(irc_worker, "async_session", StubSessionFactory(db_session))

    await irc_worker._expire_stale_download_jobs()

    assert stalled_zero_byte_job.status == "failed"
    assert stalled_zero_byte_job.completed_at is not None
    assert (
        stalled_zero_byte_job.error_message
        == "Timed out after 30 seconds waiting for the first DCC book bytes"
    )
    assert active_transfer_job.status == "downloading"
    assert active_transfer_job.error_message is None
    assert waiting_offer_job.status == "failed"
    assert (
        waiting_offer_job.error_message
        == "Timed out after 30 seconds waiting for the DCC book transfer"
    )


@pytest.mark.asyncio
async def test_repair_local_file_links_reports_progress_and_commits_in_chunks(
    db_session,
    monkeypatch,
    tmp_path,
):
    author = Author(name="Progress Author")
    db_session.add(author)
    await db_session.flush()

    for index in range(101):
        relative_path = f"Progress Author/Book {index:03d}/Book {index:03d}.epub"
        book_path = tmp_path / relative_path
        book_path.parent.mkdir(parents=True, exist_ok=True)
        book_path.write_text("placeholder", encoding="utf-8")
        db_session.add(
            BookFile(
                file_path=relative_path,
                file_name=book_path.name,
                file_format="epub",
                opf_title=f"Book {index:03d}",
                opf_author="Progress Author",
            )
        )
    await db_session.commit()

    monkeypatch.setattr(library_sync, "BOOKS_DIR", tmp_path)
    monkeypatch.setattr(
        library_sync,
        "extract_best_metadata",
        lambda path, *_args, **_kwargs: StubMetadata(
            title=path.stem,
            author="Progress Author",
        ),
    )

    original_commit = db_session.commit
    commit_count = 0

    async def counting_commit():
        nonlocal commit_count
        commit_count += 1
        await original_commit()

    monkeypatch.setattr(db_session, "commit", counting_commit)
    progress_updates: list[tuple[int, int, int, int, int]] = []

    matched_count, repaired_count, books_added = await library_sync._repair_local_file_links(
        db_session,
        progress_callback=lambda *args: progress_updates.append(args),
    )

    assert matched_count == 0
    assert repaired_count == 0
    assert books_added == 101
    assert commit_count == 2
    assert progress_updates[0] == (0, 101, 0, 0, 0)
    assert (100, 101, 0, 0, 100) in progress_updates
    assert progress_updates[-1] == (101, 101, 0, 0, 101)


@pytest.mark.asyncio
async def test_repair_local_file_links_continues_when_metadata_extraction_fails(
    db_session,
    monkeypatch,
    tmp_path,
    caplog,
):
    author = Author(name="Fallback Author")
    db_session.add(author)
    await db_session.flush()

    relative_path = "Fallback Author/Fallback Book/Fallback Book.epub"
    book_path = tmp_path / relative_path
    book_path.parent.mkdir(parents=True, exist_ok=True)
    book_path.write_text("placeholder", encoding="utf-8")
    db_session.add(
        BookFile(
            file_path=relative_path,
            file_name=book_path.name,
            file_format="epub",
            opf_title="Fallback Book",
            opf_author="Fallback Author",
        )
    )
    await db_session.commit()

    def raise_metadata_error(*_args, **_kwargs):
        raise RuntimeError("broken metadata")

    monkeypatch.setattr(library_sync, "BOOKS_DIR", tmp_path)
    monkeypatch.setattr(library_sync, "extract_best_metadata", raise_metadata_error)

    with caplog.at_level(logging.WARNING, logger="booksarr.sync"):
        matched_count, repaired_count, books_added = await library_sync._repair_local_file_links(db_session)

    refreshed_file = await db_session.get(BookFile, 1)

    assert matched_count == 0
    assert repaired_count == 0
    assert books_added == 1
    assert refreshed_file.book_id is not None
    assert "Skipping unreadable metadata while repairing local file link" in caplog.text
    assert relative_path in caplog.text


@pytest.mark.asyncio
async def test_repair_local_file_links_uses_path_title_when_opf_title_is_front_matter(
    db_session,
    monkeypatch,
    tmp_path,
):
    author = Author(name="Lee Child")
    db_session.add(author)
    await db_session.flush()

    hard_way = Book(
        title="The Hard Way",
        author_id=author.id,
        hardcover_id=384169,
        is_owned=False,
    )
    bad_local_book = Book(
        title="Scanned & Semi-Proofed by Cozette",
        author_id=author.id,
        is_owned=True,
    )
    db_session.add_all([hard_way, bad_local_book])
    await db_session.flush()

    relative_path = "Lee Child/The Hard Way/Child, Lee - The Hard Way.epub"
    book_path = tmp_path / relative_path
    book_path.parent.mkdir(parents=True, exist_ok=True)
    book_path.write_text("placeholder", encoding="utf-8")

    db_session.add(
        BookFile(
            file_path=relative_path,
            file_name=book_path.name,
            book_id=bad_local_book.id,
            file_format="epub",
            opf_title="Scanned & Semi-Proofed by Cozette",
            opf_author="The Hard Way",
        )
    )
    await db_session.commit()

    monkeypatch.setattr(library_sync, "BOOKS_DIR", tmp_path)
    monkeypatch.setattr(
        library_sync,
        "extract_best_metadata",
        lambda *_args, **_kwargs: StubMetadata(
            title="Scanned & Semi-Proofed by Cozette",
            author="The Hard Way",
        ),
    )

    matched_count, repaired_count, books_added = await library_sync._repair_local_file_links(
        db_session,
        file_paths={relative_path},
    )

    refreshed_file = await db_session.get(BookFile, 1)
    refreshed_hard_way = await db_session.get(Book, hard_way.id)
    removed_bad_book = await db_session.get(Book, bad_local_book.id)

    assert matched_count == 1
    assert repaired_count == 1
    assert books_added == 0
    assert refreshed_file.book_id == hard_way.id
    assert refreshed_hard_way.is_owned is True
    assert removed_bad_book is None


@pytest.mark.asyncio
async def test_repair_local_file_links_prefers_path_title_when_opf_title_matches_wrong_book(
    db_session,
    monkeypatch,
    tmp_path,
):
    author = Author(name="Matt Dinniman")
    db_session.add(author)
    await db_session.flush()

    dungeon_crawler_carl = Book(
        title="Dungeon Crawler Carl",
        author_id=author.id,
        hardcover_id=390,
        is_owned=True,
    )
    carls_doomsday = Book(
        title="Carl's Doomsday Scenario",
        author_id=author.id,
        hardcover_id=391,
        is_owned=False,
    )
    db_session.add_all([dungeon_crawler_carl, carls_doomsday])
    await db_session.flush()

    relative_path = (
        "Matt Dinniman/Carls Doomsday Scenario (391)/"
        "Carls Doomsday Scenario - Matt Dinniman.epub"
    )
    book_path = tmp_path / relative_path
    book_path.parent.mkdir(parents=True, exist_ok=True)
    book_path.write_text("placeholder", encoding="utf-8")

    db_session.add(
        BookFile(
            file_path=relative_path,
            file_name=book_path.name,
            book_id=dungeon_crawler_carl.id,
            file_format="epub",
            opf_title="Dungeon Crawler Carl",
            opf_author="Matt Dinniman",
        )
    )
    await db_session.commit()

    monkeypatch.setattr(library_sync, "BOOKS_DIR", tmp_path)
    monkeypatch.setattr(
        library_sync,
        "extract_best_metadata",
        lambda *_args, **_kwargs: StubMetadata(
            title="Dungeon Crawler Carl",
            author="Matt Dinniman",
        ),
    )

    matched_count, repaired_count, books_added = await library_sync._repair_local_file_links(
        db_session,
        file_paths={relative_path},
    )

    refreshed_file = await db_session.get(BookFile, 1)
    refreshed_dungeon_crawler_carl = await db_session.get(Book, dungeon_crawler_carl.id)
    refreshed_carls_doomsday = await db_session.get(Book, carls_doomsday.id)

    assert matched_count == 1
    assert repaired_count == 1
    assert books_added == 0
    assert refreshed_file.book_id == carls_doomsday.id
    assert refreshed_dungeon_crawler_carl.is_owned is False
    assert refreshed_carls_doomsday.is_owned is True


@pytest.mark.asyncio
async def test_repair_local_file_links_keeps_existing_hardcover_match_when_opf_title_is_bad(
    db_session,
    monkeypatch,
    tmp_path,
):
    author = Author(name="Lee Child")
    db_session.add(author)
    await db_session.flush()

    without_fail = Book(
        title="Without Fail",
        author_id=author.id,
        hardcover_id=85656,
        is_owned=True,
    )
    db_session.add(without_fail)
    await db_session.flush()

    relative_path = "Lee Child/Without Fail/child, lee - without fail.epub"
    book_path = tmp_path / relative_path
    book_path.parent.mkdir(parents=True, exist_ok=True)
    book_path.write_text("placeholder", encoding="utf-8")

    db_session.add(
        BookFile(
            file_path=relative_path,
            file_name=book_path.name,
            book_id=without_fail.id,
            file_format="epub",
            opf_title="ONE",
            opf_author="THEY FOUND OUT ABOUT HIM IN JULY",
        )
    )
    await db_session.commit()

    monkeypatch.setattr(library_sync, "BOOKS_DIR", tmp_path)
    monkeypatch.setattr(
        library_sync,
        "extract_best_metadata",
        lambda *_args, **_kwargs: StubMetadata(
            title="ONE",
            author="THEY FOUND OUT ABOUT HIM IN JULY",
        ),
    )

    matched_count, repaired_count, books_added = await library_sync._repair_local_file_links(
        db_session,
        file_paths={relative_path},
    )

    refreshed_file = await db_session.get(BookFile, 1)
    books = (await db_session.execute(select(Book))).scalars().all()

    assert matched_count == 1
    assert repaired_count == 0
    assert books_added == 0
    assert refreshed_file.book_id == without_fail.id
    assert [book.title for book in books] == ["Without Fail"]


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
