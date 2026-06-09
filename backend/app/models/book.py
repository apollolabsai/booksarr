from datetime import datetime

from sqlalchemy import Integer, String, Text, DateTime, Boolean, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from backend.app.database import Base
from backend.app.utils.title_sort import effective_title_sort_key


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    title_sort_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey("authors.id"), nullable=False, index=True)
    hardcover_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    hardcover_slug: Mapped[str | None] = mapped_column(String, nullable=True)
    compilation: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    book_category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    book_category_name: Mapped[str | None] = mapped_column(String, nullable=True)
    literary_type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    literary_type_name: Mapped[str | None] = mapped_column(String, nullable=True)
    hardcover_state: Mapped[str | None] = mapped_column(String, nullable=True)
    hardcover_isbn_10: Mapped[str | None] = mapped_column(String, nullable=True)
    hardcover_isbn_13: Mapped[str | None] = mapped_column(String, nullable=True)
    google_id: Mapped[str | None] = mapped_column(String, nullable=True)
    google_published_date: Mapped[str | None] = mapped_column(String, nullable=True)
    google_cover_url: Mapped[str | None] = mapped_column(String, nullable=True)
    google_isbn_10: Mapped[str | None] = mapped_column(String, nullable=True)
    google_isbn_13: Mapped[str | None] = mapped_column(String, nullable=True)
    ol_edition_key: Mapped[str | None] = mapped_column(String, nullable=True)
    ol_first_publish_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ol_cover_url: Mapped[str | None] = mapped_column(String, nullable=True)
    ol_isbn_10: Mapped[str | None] = mapped_column(String, nullable=True)
    ol_isbn_13: Mapped[str | None] = mapped_column(String, nullable=True)
    isbn: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String, nullable=True)
    release_date: Mapped[str | None] = mapped_column(String, nullable=True)
    publish_date_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    cover_image_cached_path: Mapped[str | None] = mapped_column(String, nullable=True)
    manual_cover_source: Mapped[str | None] = mapped_column(String, nullable=True)
    manual_cover_url: Mapped[str | None] = mapped_column(String, nullable=True)
    manual_visibility: Mapped[str | None] = mapped_column(String, nullable=True)
    manual_title: Mapped[str | None] = mapped_column(String, nullable=True)
    manual_author_name: Mapped[str | None] = mapped_column(String, nullable=True)
    manual_isbn: Mapped[str | None] = mapped_column(String, nullable=True)
    manual_publisher: Mapped[str | None] = mapped_column(String, nullable=True)
    manual_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_release_date: Mapped[str | None] = mapped_column(String, nullable=True)
    manual_language: Mapped[str | None] = mapped_column(String, nullable=True)
    manual_series_name: Mapped[str | None] = mapped_column(String, nullable=True)
    manual_series_position: Mapped[float | None] = mapped_column(Float, nullable=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_owned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author: Mapped["Author"] = relationship("Author", back_populates="books", lazy="selectin")
    book_series: Mapped[list["BookSeries"]] = relationship("BookSeries", back_populates="book", lazy="selectin")
    files: Mapped[list["BookFile"]] = relationship("BookFile", back_populates="book", lazy="selectin")

    @validates("title", "manual_title")
    def _set_title_sort_key(self, key: str, value: str | None) -> str | None:
        title = value if key == "title" else self.title
        manual_title = value if key == "manual_title" else self.manual_title
        self.title_sort_key = effective_title_sort_key(title, manual_title)
        return value
