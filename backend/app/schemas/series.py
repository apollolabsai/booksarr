from pydantic import BaseModel


class SeriesDetail(BaseModel):
    id: int
    hardcover_id: int | None
    name: str
    description: str | None
    is_completed: bool
    book_count: int
    books: list["SeriesBookEntry"]

    class Config:
        from_attributes = True


class SeriesBookEntry(BaseModel):
    book_id: int
    title: str
    position: float | None
    is_owned: bool
    cover_image_cached_path: str | None
    author_name: str


SeriesDetail.model_rebuild()
