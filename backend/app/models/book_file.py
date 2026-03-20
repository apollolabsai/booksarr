from datetime import datetime

from sqlalchemy import Integer, String, Text, DateTime, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


class BookFile(Base):
    __tablename__ = "book_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    book_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("books.id"), nullable=True)
    file_path: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    file_name: Mapped[str] = mapped_column(String, nullable=False)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_format: Mapped[str | None] = mapped_column(String, nullable=True)
    opf_title: Mapped[str | None] = mapped_column(String, nullable=True)
    opf_author: Mapped[str | None] = mapped_column(String, nullable=True)
    opf_isbn: Mapped[str | None] = mapped_column(String, nullable=True)
    opf_series: Mapped[str | None] = mapped_column(String, nullable=True)
    opf_series_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    opf_publisher: Mapped[str | None] = mapped_column(String, nullable=True)
    opf_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_cover_path: Mapped[str | None] = mapped_column(String, nullable=True)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    book: Mapped["Book | None"] = relationship("Book", back_populates="files")
