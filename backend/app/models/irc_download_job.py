from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


class IrcDownloadJob(Base):
    __tablename__ = "irc_download_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    book_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("books.id"), nullable=True, index=True)
    search_job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("irc_search_jobs.id"), nullable=True, index=True)
    search_result_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("irc_search_results.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued", index=True)
    bulk_request_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    bulk_item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("irc_bulk_download_items.id"), nullable=True, index=True)
    request_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    dcc_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes_downloaded: Mapped[int | None] = mapped_column(Integer, nullable=True)
    saved_path: Mapped[str | None] = mapped_column(String, nullable=True)
    moved_to_library_path: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    search_job: Mapped["IrcSearchJob | None"] = relationship("IrcSearchJob", back_populates="download_jobs", lazy="selectin")
    search_result: Mapped["IrcSearchResult | None"] = relationship("IrcSearchResult", back_populates="download_jobs", lazy="selectin")
