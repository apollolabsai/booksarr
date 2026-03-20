from sqlalchemy import Integer, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


class BookSeries(Base):
    __tablename__ = "book_series"
    __table_args__ = (UniqueConstraint("book_id", "series_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("books.id"), nullable=False, index=True)
    series_id: Mapped[int] = mapped_column(Integer, ForeignKey("series.id"), nullable=False, index=True)
    position: Mapped[float | None] = mapped_column(Float, nullable=True)

    book: Mapped["Book"] = relationship("Book", back_populates="book_series")
    series: Mapped["Series"] = relationship("Series", back_populates="book_series")
