from pydantic import BaseModel


class AuthorSummary(BaseModel):
    id: int
    name: str
    hardcover_id: int | None
    hardcover_slug: str | None
    bio: str | None
    image_url: str | None
    image_cached_path: str | None
    book_count_local: int
    book_count_total: int

    class Config:
        from_attributes = True


class AuthorDetail(AuthorSummary):
    books: list["BookInAuthor"]
    series: list["SeriesInAuthor"]


class AuthorPortraitOption(BaseModel):
    key: str
    source: str
    label: str
    image_url: str | None
    cached_path: str | None
    page_url: str | None = None
    creator: str | None = None
    license: str | None = None
    width: int | None
    height: int | None
    aspect_ratio: float | None
    is_current: bool
    is_manual: bool


class AuthorPortraitOptionsResponse(BaseModel):
    author_id: int
    current_source: str | None
    manual_source: str | None
    options: list["AuthorPortraitOption"]


class AuthorPortraitSelectionRequest(BaseModel):
    source: str
    image_url: str
    page_url: str | None = None


class BookInAuthor(BaseModel):
    id: int
    title: str
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
    description: str | None
    release_date: str | None
    cover_image_url: str | None
    cover_image_cached_path: str | None
    cover_aspect_ratio: float | None
    rating: float | None
    pages: int | None
    is_owned: bool
    owned_copy_count: int
    series_info: list["SeriesPositionInfo"]

    class Config:
        from_attributes = True


class SeriesPositionInfo(BaseModel):
    series_id: int
    series_name: str
    position: float | None


class SeriesInAuthor(BaseModel):
    id: int
    name: str
    hardcover_id: int | None
    books: list["SeriesBookEntry"]


class SeriesBookEntry(BaseModel):
    book_id: int
    title: str
    position: float | None
    is_owned: bool
    cover_image_cached_path: str | None


# Resolve forward references
AuthorDetail.model_rebuild()
SeriesInAuthor.model_rebuild()
AuthorPortraitOptionsResponse.model_rebuild()
