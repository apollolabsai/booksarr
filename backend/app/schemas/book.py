from pydantic import BaseModel


class SeriesPositionInfo(BaseModel):
    series_id: int
    series_name: str
    position: float | None


class LocalBookFile(BaseModel):
    id: int
    file_path: str
    file_name: str
    file_size: int | None
    file_format: str | None


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
    manual_title: str | None = None
    manual_author_name: str | None = None
    manual_isbn: str | None = None
    manual_publisher: str | None = None
    manual_description: str | None = None
    manual_release_date: str | None = None
    manual_language: str | None = None
    manual_series_name: str | None = None
    manual_series_position: float | None = None
    cover_image_url: str | None
    cover_image_cached_path: str | None
    cover_aspect_ratio: float | None
    rating: float | None
    pages: int | None
    is_owned: bool
    owned_copy_count: int
    local_files: list[LocalBookFile]
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
    url: str | None = None


class BookVisibilityRequest(BaseModel):
    action: str


class CoverSearchResult(BaseModel):
    url: str
    thumbnail_url: str
    width: int | None
    height: int | None
    title: str
    source_url: str


class BookCoverSearchResponse(BaseModel):
    book_id: int
    query: str
    results: list[CoverSearchResult]


class BookOpfMetadataFile(BaseModel):
    id: int
    file_path: str
    file_name: str
    file_format: str | None
    file_size: int | None
    opf_title: str | None
    opf_author: str | None
    opf_isbn: str | None
    opf_publisher: str | None
    opf_description: str | None
    opf_date: str | None
    opf_language: str | None
    opf_series: str | None
    opf_series_index: float | None


class BookMetadataValues(BaseModel):
    title: str | None
    author_name: str | None
    isbn: str | None
    publisher: str | None
    description: str | None
    release_date: str | None
    language: str | None
    series_name: str | None
    series_position: float | None


class BookMetadataInfoResponse(BaseModel):
    book_id: int
    hardcover_id: int | None
    hardcover_slug: str | None
    current: BookMetadataValues
    original: BookMetadataValues
    manual: BookMetadataValues
    files: list[BookOpfMetadataFile]
    editable_fields: list[str]


class BookMetadataUpdateRequest(BaseModel):
    title: str | None = None
    author_name: str | None = None
    isbn: str | None = None
    publisher: str | None = None
    description: str | None = None
    release_date: str | None = None
    language: str | None = None
    series_name: str | None = None
    series_position: float | None = None
    clear_fields: list[str] = []


class BookMetadataApplyOpfRequest(BaseModel):
    book_file_id: int
    fields: list[str]


class BookMetadataWriteOpfRequest(BaseModel):
    book_file_id: int
    fields: list[str]
    values: BookMetadataValues
    delete_backup: bool = False


class BookMetadataWriteOpfResponse(BaseModel):
    status: str
    message: str
    backup_path: str
