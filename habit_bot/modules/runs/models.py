"""Таблица модуля runs (раздел 5): забеги (RunEntry)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from habit_bot.kernel.db import Base, PublicIdMixin, SoftDeleteMixin, TimestampMixin, UtcDateTime


class RunEntry(PublicIdMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Один забег: дистанция и время; темп хранится, чтобы сравнивать и искать рекорды без пересчёта."""

    __tablename__ = "runs_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    logged_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    pace_sec: Mapped[int] = mapped_column(Integer, nullable=False)
