from pydantic import BaseModel


class BookSummary(BaseModel):
    id: int
    title: str
    author_id: int
    author_name: str
    hardcover_id: int | None
    hardcover_slug: str | None
    isbn: str | None
    release_date: str | None
    cover_image_url: str | None
    cover_image_cached_path: str | None
    rating: float | None
    pages: int | None
    is_owned: bool

    class Config:
        from_attributes = True


class BookDetail(BookSummary):
    description: str | None
    publisher: str | None
    language: str | None
    tags: str | None
    series_info: list["SeriesPositionInfo"]

    class Config:
        from_attributes = True


class SeriesPositionInfo(BaseModel):
    series_id: int
    series_name: str
    position: float | None


BookDetail.model_rebuild()
