from pydantic import BaseModel


class VisibilityCategories(BaseModel):
    standard_books: bool = True
    short_fiction: bool = True
    collections_and_compilations: bool = True
    likely_collections_by_title: bool = True
    graphic_and_alternate_formats: bool = False
    research_non_book_material: bool = False
    fan_fiction: bool = False
    non_english_books: bool = False
    upcoming_unreleased: bool = False
    pending_hardcover_records: bool = False
    likely_excerpts: bool = False


class SettingsResponse(BaseModel):
    hardcover_api_key: str
    hardcover_api_key_from_env: bool = False
    google_books_api_key: str
    google_books_api_key_from_env: bool = False
    library_path: str
    last_scan_at: str | None
    scan_interval_hours: int
    visibility_categories: VisibilityCategories


class SettingsUpdate(BaseModel):
    hardcover_api_key: str | None = None
    google_books_api_key: str | None = None
    scan_interval_hours: int | None = None
    visibility_categories: VisibilityCategories | None = None


class ApiUsageDay(BaseModel):
    day: str
    total: int
    hardcover: int
    google: int
    openlibrary: int
