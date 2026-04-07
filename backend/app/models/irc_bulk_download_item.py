from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


class IrcBulkDownloadItem(Base):
    __tablename__ = "irc_bulk_download_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("irc_bulk_download_batches.id"), nullable=False, index=True)
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("books.id"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued", index=True)
    query_text: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("irc_search_jobs.id"), nullable=True, index=True)
    download_job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("irc_download_jobs.id"), nullable=True, index=True)
    selected_search_result_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("irc_search_results.id"), nullable=True, index=True)
    selected_result_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempted_result_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    batch: Mapped["IrcBulkDownloadBatch"] = relationship("IrcBulkDownloadBatch", back_populates="items", lazy="selectin")
    book: Mapped["Book"] = relationship("Book", lazy="selectin")
    search_job: Mapped["IrcSearchJob | None"] = relationship(
        "IrcSearchJob",
        lazy="selectin",
        foreign_keys=[search_job_id],
    )
    download_job: Mapped["IrcDownloadJob | None"] = relationship(
        "IrcDownloadJob",
        lazy="selectin",
        foreign_keys=[download_job_id],
    )
    selected_search_result: Mapped["IrcSearchResult | None"] = relationship(
        "IrcSearchResult",
        lazy="selectin",
        foreign_keys=[selected_search_result_id],
    )
