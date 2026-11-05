"""Журнал бэкапов: когда был последний удачный (раз в 2 дня — считается от него, а не от перезапуска бота)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from habit_bot.kernel.db import Base, UtcDateTime


class BackupLog(Base):
    __tablename__ = "backup_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(String(16), nullable=False)  # schedule / manual
    size_kb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str] = mapped_column(String(255), nullable=False, default="")
