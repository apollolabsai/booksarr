from backend.app.models import Author, Book, IrcSearchResult
from backend.app.services.irc_worker import (
    _choose_best_bulk_result,
    _classify_bulk_result_type,
    normalize_bulk_file_type_preferences,
)


def _make_result(
    *,
    result_id: int,
    display_name: str,
    file_format: str | None,
    file_size_text: str | None,
    normalized_title: str = "freakonomics",
    normalized_author: str = "steven d levitt",
) -> IrcSearchResult:
    return IrcSearchResult(
        id=result_id,
        search_job_id=1,
        result_index=result_id,
        raw_line=display_name,
        bot_name="artemis_serv",
        display_name=display_name,
        normalized_title=normalized_title,
        normalized_author=normalized_author,
        file_format=file_format,
        file_size_text=file_size_text,
        download_command=f"!download {result_id}",
        selected=False,
    )


def test_normalize_bulk_file_type_preferences_preserves_enabled_order():
    normalized = normalize_bulk_file_type_preferences([
        {"key": "mobi", "enabled": True},
        {"key": "epub", "enabled": True},
        {"key": "zip", "enabled": False},
        {"key": "rar", "enabled": False},
        {"key": "audiobook", "enabled": True},
    ])

    assert normalized == [
        {"key": "mobi", "enabled": True},
        {"key": "epub", "enabled": True},
        {"key": "zip", "enabled": False},
        {"key": "rar", "enabled": False},
        {"key": "audiobook", "enabled": True},
    ]


def test_classify_bulk_result_type_detects_audiobook_from_title_and_size():
    result = _make_result(
        result_id=1,
        display_name="Freakonomics Audio Book Complete.rar",
        file_format="rar",
        file_size_text="120MB",
    )

    assert _classify_bulk_result_type(result) == "audiobook"


def test_choose_best_bulk_result_respects_enabled_priority_order():
    author = Author(id=1, name="Steven D. Levitt")
    book = Book(id=1, author_id=1, title="Freakonomics", author=author, is_owned=False)
    epub_result = _make_result(
        result_id=1,
        display_name="Freakonomics - Steven D. Levitt.epub",
        file_format="epub",
        file_size_text="900KB",
    )
    mobi_result = _make_result(
        result_id=2,
        display_name="Freakonomics - Steven D. Levitt.mobi",
        file_format="mobi",
        file_size_text="1.2MB",
    )

    selected = _choose_best_bulk_result(
        book=book,
        results=[epub_result, mobi_result],
        attempted_ids=[],
        previous_result=None,
        prefer_different_bot=False,
        file_type_preferences=[
            {"key": "mobi", "enabled": True},
            {"key": "epub", "enabled": True},
            {"key": "zip", "enabled": False},
            {"key": "rar", "enabled": False},
            {"key": "audiobook", "enabled": False},
        ],
    )

    assert selected is not None
    assert selected.id == mobi_result.id


def test_choose_best_bulk_result_excludes_disabled_types():
    author = Author(id=1, name="Steven D. Levitt")
    book = Book(id=1, author_id=1, title="Freakonomics", author=author, is_owned=False)
    mobi_result = _make_result(
        result_id=2,
        display_name="Freakonomics - Steven D. Levitt.mobi",
        file_format="mobi",
        file_size_text="1.2MB",
    )

    selected = _choose_best_bulk_result(
        book=book,
        results=[mobi_result],
        attempted_ids=[],
        previous_result=None,
        prefer_different_bot=False,
        file_type_preferences=[
            {"key": "epub", "enabled": True},
            {"key": "mobi", "enabled": False},
            {"key": "zip", "enabled": False},
            {"key": "rar", "enabled": False},
            {"key": "audiobook", "enabled": False},
        ],
    )

    assert selected is None
