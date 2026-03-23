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
    isbn: str | None
    description: str | None
    release_date: str | None
    cover_image_url: str | None
    cover_image_cached_path: str | None
    rating: float | None
    pages: int | None
    is_owned: bool
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
