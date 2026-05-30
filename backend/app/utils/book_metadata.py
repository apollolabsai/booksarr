from backend.app.models import Book
from backend.app.utils.isbn import has_any_valid_isbn


def _clean_manual_value(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def effective_title(book: Book) -> str:
    return _clean_manual_value(book.manual_title) or book.title


def effective_author_name(book: Book) -> str:
    return _clean_manual_value(book.manual_author_name) or (book.author.name if book.author else "Unknown")


def effective_isbn(book: Book) -> str | None:
    return _clean_manual_value(book.manual_isbn) or book.isbn


def effective_publisher(book: Book) -> str | None:
    return _clean_manual_value(book.manual_publisher) or book.publisher


def effective_description(book: Book) -> str | None:
    return _clean_manual_value(book.manual_description) or book.description


def effective_release_date(book: Book) -> str | None:
    return _clean_manual_value(book.manual_release_date) or book.release_date


def effective_language(book: Book) -> str | None:
    return _clean_manual_value(book.manual_language) or book.language


def effective_has_valid_isbn(book: Book) -> bool:
    return has_any_valid_isbn(
        effective_isbn(book),
        book.hardcover_isbn_10,
        book.hardcover_isbn_13,
        book.google_isbn_10,
        book.google_isbn_13,
        book.ol_isbn_10,
        book.ol_isbn_13,
    )
