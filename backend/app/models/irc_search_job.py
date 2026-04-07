from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


class IrcSearchJob(Base):
    __tablename__ = "irc_search_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    book_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("books.id"), nullable=True, index=True)
    query_text: Mapped[str] = mapped_column(String, nullable=False)
    normalized_query: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued", index=True)
    auto_download: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bulk_request_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    bulk_item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("irc_bulk_download_items.id"), nullable=True, index=True)
    request_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_result_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    result_archive_path: Mapped[str | None] = mapped_column(String, nullable=True)
    result_text_path: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    results: Mapped[list["IrcSearchResult"]] = relationship(
        "IrcSearchResult",
        back_populates="search_job",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    download_jobs: Mapped[list["IrcDownloadJob"]] = relationship(
        "IrcDownloadJob",
        back_populates="search_job",
        lazy="selectin",
    )
