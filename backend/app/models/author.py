from datetime import datetime

from sqlalchemy import Integer, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


class Author(Base):
    __tablename__ = "authors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    hardcover_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    hardcover_slug: Mapped[str | None] = mapped_column(String, nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    image_cached_path: Mapped[str | None] = mapped_column(String, nullable=True)
    manual_image_source: Mapped[str | None] = mapped_column(String, nullable=True)
    manual_image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    manual_image_page_url: Mapped[str | None] = mapped_column(String, nullable=True)
    book_count_local: Mapped[int] = mapped_column(Integer, default=0)
    book_count_total: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    books: Mapped[list["Book"]] = relationship("Book", back_populates="author", lazy="selectin")
