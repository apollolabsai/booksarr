from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


class IrcBulkDownloadBatch(Base):
    __tablename__ = "irc_bulk_download_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    items: Mapped[list["IrcBulkDownloadItem"]] = relationship(
        "IrcBulkDownloadItem",
        back_populates="batch",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
