"""``SourceCache`` (раздел 5): кэш погоды, календаря и поиска городов."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from habit_bot.kernel.db import Base, UtcDateTime


class SourceCache(Base):
    __tablename__ = "source_cache"
    __table_args__ = (UniqueConstraint("source", "key", name="uq_source_cache_source_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    data: Mapped[Any] = mapped_column(JSON, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
