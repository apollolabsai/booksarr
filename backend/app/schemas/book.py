from pydantic import BaseModel


class SeriesPositionInfo(BaseModel):
    series_id: int
    series_name: str
    position: float | None


class BookSummary(BaseModel):
    id: int
    title: str
    author_id: int
    author_name: str
    hardcover_id: int | None
    hardcover_slug: str | None
    compilation: bool | None
    book_category_id: int | None
    book_category_name: str | None
    literary_type_id: int | None
    literary_type_name: str | None
    hardcover_state: str | None
    hardcover_isbn_10: str | None
    hardcover_isbn_13: str | None
    isbn: str | None
    google_isbn_10: str | None
    google_isbn_13: str | None
    ol_isbn_10: str | None
    ol_isbn_13: str | None
    has_valid_isbn: bool
    matched_google: bool
    matched_openlibrary: bool
    release_date: str | None
    cover_image_url: str | None
    cover_image_cached_path: str | None
    cover_aspect_ratio: float | None
    rating: float | None
    pages: int | None
    is_owned: bool
    series_info: list[SeriesPositionInfo]

    class Config:
        from_attributes = True


class BookDetail(BookSummary):
    description: str | None
    publisher: str | None
    language: str | None
    tags: str | None

    class Config:
        from_attributes = True


class HiddenCategoryTag(BaseModel):
    key: str
    label: str


class HiddenBookSummary(BookSummary):
    hidden_category_key: str
    hidden_category_label: str
    hidden_categories: list[HiddenCategoryTag]

    class Config:
        from_attributes = True


class CoverOption(BaseModel):
    key: str
    source: str
    label: str
    image_url: str | None
    cached_path: str | None
    width: int | None
    height: int | None
    aspect_ratio: float | None
    ratio_delta_percent: float | None
    is_current: bool
    is_manual: bool


class BookCoverOptionsResponse(BaseModel):
    book_id: int
    current_source: str | None
    manual_source: str | None
    options: list[CoverOption]


class BookCoverSelectionRequest(BaseModel):
    source: str


class BookVisibilityRequest(BaseModel):
    action: str
