from pydantic import BaseModel, Field


class VisibilityCategories(BaseModel):
    standard_books: bool = True
    short_fiction: bool = True
    collections_and_compilations: bool = True
    likely_collections_by_title: bool = True
    graphic_and_alternate_formats: bool = False
    research_non_book_material: bool = False
    fan_fiction: bool = False
    valid_isbn: bool = False
    non_english_books: bool = False
    upcoming_unreleased: bool = False
    pending_hardcover_records: bool = False
    likely_excerpts: bool = False


class HiddenCategorySummary(BaseModel):
    key: str
    label: str
    count: int


class ScanSourceSummary(BaseModel):
    lookups_attempted: int = 0
    matched: int = 0
    failed: int = 0
    cached: int = 0
    deferred: int = 0
    failure_reasons: dict[str, int] = Field(default_factory=dict)


class ScanSummary(BaseModel):
    status: str
    mode: str
    message: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    files_total: int = 0
    files_new: int = 0
    files_deleted: int = 0
    files_unchanged: int = 0
    owned_books_found: int = 0
    authors_added: int = 0
    books_added: int = 0
    books_hidden: int = 0
    hidden_by_category: list[HiddenCategorySummary] = Field(default_factory=list)
    hardcover: ScanSourceSummary = Field(default_factory=ScanSourceSummary)
    google: ScanSourceSummary = Field(default_factory=ScanSourceSummary)
    openlibrary: ScanSourceSummary = Field(default_factory=ScanSourceSummary)


class SettingsResponse(BaseModel):
    hardcover_api_key: str
    hardcover_api_key_from_env: bool = False
    google_books_api_key: str
    google_books_api_key_from_env: bool = False
    library_path: str
    last_scan_at: str | None
    last_scan_summary: ScanSummary | None = None
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
