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


class AuthorDirectoryEntry(BaseModel):
    id: int
    dir_path: str
    is_primary: bool


class AuthorDetail(AuthorSummary):
    author_directories: list["AuthorDirectoryEntry"]
    books: list["BookInAuthor"]
    series: list["SeriesInAuthor"]
    unmatched_local_files: list["UnmatchedLocalFile"]


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


class AuthorPortraitSearchResult(BaseModel):
    url: str
    thumbnail_url: str
    width: int | None
    height: int | None
    title: str
    source_url: str


class AuthorPortraitSearchResponse(BaseModel):
    author_id: int
    query: str
    results: list["AuthorPortraitSearchResult"]


class AuthorPortraitSelectionRequest(BaseModel):
    source: str
    image_url: str
    page_url: str | None = None


class AuthorSearchCandidate(BaseModel):
    hardcover_id: int
    name: str
    slug: str | None = None
    bio: str | None = None
    image_url: str | None = None
    books_count: int = 0


class AuthorSearchResponse(BaseModel):
    query: str
    candidates: list["AuthorSearchCandidate"]


class AuthorAddRequest(BaseModel):
    hardcover_id: int


class AuthorDirectoryMergeRequest(BaseModel):
    target_directory_id: int


class AuthorDirectoryMergeResponse(BaseModel):
    status: str
    message: str
    kept_directory: str
    removed_directories: list[str]
    moved_items: int


class LocalBookFile(BaseModel):
    id: int
    file_path: str
    file_name: str
    file_size: int | None
    file_format: str | None


class UnmatchedLocalFile(BaseModel):
    file_path: str
    file_name: str
    file_size: int | None
    file_format: str | None
    linked_book_id: int | None = None
    linked_book_title: str | None = None
    author_id: int | None = None
    author_name: str | None = None


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
    local_files: list["LocalBookFile"]
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
AuthorPortraitSearchResponse.model_rebuild()
