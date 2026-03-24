import json
import re
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Book, Setting
from backend.app.utils.isbn import has_any_valid_isbn

VISIBILITY_CATEGORY_DEFAULTS = {
    "standard_books": True,
    "short_fiction": True,
    "collections_and_compilations": True,
    "likely_collections_by_title": True,
    "graphic_and_alternate_formats": False,
    "research_non_book_material": False,
    "fan_fiction": False,
    "valid_isbn": False,
    "non_english_books": False,
    "upcoming_unreleased": False,
    "pending_hardcover_records": False,
    "likely_excerpts": False,
}

VISIBILITY_CATEGORY_LABELS = {
    "manual_hidden": "Manually Hidden",
    "standard_books": "Standard Books",
    "short_fiction": "Short Fiction",
    "collections_and_compilations": "Collections & Compilations",
    "likely_collections_by_title": "Likely Collections by Title Heuristic",
    "graphic_and_alternate_formats": "Graphic & Alternate Formats",
    "research_non_book_material": "Research / Non-Book Material",
    "fan_fiction": "Fan Fiction",
    "valid_isbn": "Valid ISBN",
    "non_english_books": "Non-English Books",
    "upcoming_unreleased": "Upcoming / Unreleased",
    "pending_hardcover_records": "Pending Hardcover Records",
    "likely_excerpts": "Likely Excerpts / Samples",
}

_COLLECTION_KEYWORD_RE = re.compile(
    r"\b("
    r"collection|value collection|boxed set|box set|omnibus|complete\b|"
    r"collected tales|sampler|anthology|condensed books|select editions|"
    r"trilogy|tetralogy|series box|ebook collection"
    r")\b",
    re.IGNORECASE,
)

_MULTI_WORK_SUFFIX_RE = re.compile(r":\s*.+(?:,|/|;).+(?:,|/|;).+", re.IGNORECASE)
_MULTI_BOOK_COUNT_RE = re.compile(r"\b\d+\s+(?:book|novel)s?\b", re.IGNORECASE)


def normalize_visibility_settings(raw: Any) -> dict[str, bool]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}

    merged = dict(VISIBILITY_CATEGORY_DEFAULTS)
    for key in VISIBILITY_CATEGORY_DEFAULTS:
        if key in raw:
            merged[key] = bool(raw[key])
    return merged


async def get_book_visibility_settings(db: AsyncSession) -> dict[str, bool]:
    result = await db.execute(select(Setting).where(Setting.key == "book_visibility_categories"))
    setting = result.scalar_one_or_none()
    if not setting:
        return dict(VISIBILITY_CATEGORY_DEFAULTS)
    return normalize_visibility_settings(setting.value)


def is_non_english(book: Book) -> bool:
    language = (book.language or "").strip().lower()
    if not language:
        return False
    return not (language.startswith("en") or language.startswith("english"))


def is_upcoming(book: Book, today: str | None = None) -> bool:
    if not book.release_date:
        return False
    today = today or date.today().isoformat()
    return book.release_date > today


def is_likely_collection_by_title(title: str | None) -> bool:
    if not title:
        return False
    if _COLLECTION_KEYWORD_RE.search(title):
        return True
    if _MULTI_BOOK_COUNT_RE.search(title):
        return True
    return bool(_MULTI_WORK_SUFFIX_RE.search(title))


def is_likely_excerpt(book: Book) -> bool:
    return (
        (book.hardcover_state or "").lower() == "pending"
        and book.book_category_id == 1
        and book.pages is not None
        and 0 < book.pages <= 50
        and not is_likely_collection_by_title(book.title)
    )


def get_primary_visibility_category(book: Book) -> str:
    if book.book_category_id == 5:
        return "fan_fiction"
    if book.book_category_id == 6:
        return "research_non_book_material"
    if book.book_category_id in {4, 7, 9, 10}:
        return "graphic_and_alternate_formats"
    if book.compilation or book.book_category_id == 8:
        return "collections_and_compilations"
    if is_likely_collection_by_title(book.title):
        return "likely_collections_by_title"
    if book.book_category_id in {2, 3}:
        return "short_fiction"
    return "standard_books"


def is_book_visible(book: Book, visibility_settings: dict[str, bool], today: str | None = None) -> bool:
    if book.manual_visibility == "hidden":
        return False
    if book.manual_visibility == "visible":
        return True
    if visibility_settings["valid_isbn"] and not has_any_valid_isbn(
        book.isbn,
        book.hardcover_isbn_10,
        book.hardcover_isbn_13,
        book.google_isbn_10,
        book.google_isbn_13,
        book.ol_isbn_10,
        book.ol_isbn_13,
    ):
        return False

    if book.is_owned:
        return True

    if is_non_english(book) and not visibility_settings["non_english_books"]:
        return False
    if is_upcoming(book, today=today) and not visibility_settings["upcoming_unreleased"]:
        return False
    if is_likely_excerpt(book):
        return visibility_settings["likely_excerpts"]
    if (book.hardcover_state or "").lower() == "pending" and not visibility_settings["pending_hardcover_records"]:
        return False

    return visibility_settings.get(get_primary_visibility_category(book), True)


def get_hidden_category(book: Book, visibility_settings: dict[str, bool], today: str | None = None) -> tuple[str, str] | None:
    categories = get_hidden_categories(book, visibility_settings, today=today)
    return categories[0] if categories else None


def get_hidden_categories(
    book: Book,
    visibility_settings: dict[str, bool],
    today: str | None = None,
) -> list[tuple[str, str]]:
    categories: list[tuple[str, str]] = []

    if book.manual_visibility == "hidden":
        key = "manual_hidden"
        categories.append((key, VISIBILITY_CATEGORY_LABELS[key]))
    if book.manual_visibility == "visible":
        return []
    if visibility_settings["valid_isbn"] and not has_any_valid_isbn(
        book.isbn,
        book.hardcover_isbn_10,
        book.hardcover_isbn_13,
        book.google_isbn_10,
        book.google_isbn_13,
        book.ol_isbn_10,
        book.ol_isbn_13,
    ):
        key = "valid_isbn"
        categories.append((key, VISIBILITY_CATEGORY_LABELS[key]))

    if book.is_owned:
        return categories

    if is_non_english(book) and not visibility_settings["non_english_books"]:
        key = "non_english_books"
        categories.append((key, VISIBILITY_CATEGORY_LABELS[key]))
    if is_upcoming(book, today=today) and not visibility_settings["upcoming_unreleased"]:
        key = "upcoming_unreleased"
        categories.append((key, VISIBILITY_CATEGORY_LABELS[key]))
    if is_likely_excerpt(book) and not visibility_settings["likely_excerpts"]:
        key = "likely_excerpts"
        categories.append((key, VISIBILITY_CATEGORY_LABELS[key]))
    if (book.hardcover_state or "").lower() == "pending" and not visibility_settings["pending_hardcover_records"]:
        key = "pending_hardcover_records"
        categories.append((key, VISIBILITY_CATEGORY_LABELS[key]))

    key = get_primary_visibility_category(book)
    if not visibility_settings.get(key, True):
        categories.append((key, VISIBILITY_CATEGORY_LABELS[key]))
    return categories
