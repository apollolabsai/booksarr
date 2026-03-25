from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


class IrcSearchResult(Base):
    __tablename__ = "irc_search_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    search_job_id: Mapped[int] = mapped_column(Integer, ForeignKey("irc_search_jobs.id"), nullable=False, index=True)
    result_index: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_line: Mapped[str] = mapped_column(Text, nullable=False)
    bot_name: Mapped[str | None] = mapped_column(String, nullable=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_title: Mapped[str | None] = mapped_column(String, nullable=True)
    normalized_author: Mapped[str | None] = mapped_column(String, nullable=True)
    file_format: Mapped[str | None] = mapped_column(String, nullable=True)
    file_size_text: Mapped[str | None] = mapped_column(String, nullable=True)
    download_command: Mapped[str] = mapped_column(Text, nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    search_job: Mapped["IrcSearchJob"] = relationship("IrcSearchJob", back_populates="results", lazy="selectin")
    download_jobs: Mapped[list["IrcDownloadJob"]] = relationship(
        "IrcDownloadJob",
        back_populates="search_result",
        lazy="selectin",
    )
