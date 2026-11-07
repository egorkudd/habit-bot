"""Таблица модуля stats: последняя выбранная привычка в «Итогах» (раздел 3.8.1 — «бот запоминает выбор») и какие
строки КБЖУ показывать в обзоре."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from habit_bot.kernel.db import Base


class StatsSettings(Base):
    __tablename__ = "stats_settings"
    __table_args__ = (UniqueConstraint("user_id", name="uq_stats_settings_user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    section: Mapped[str] = mapped_column(String(40), nullable=False, default="food")
    # Строки еды в обзоре (правки 1.0.2): k — калории, p — белки, f — жиры, c — углеводы; по умолчанию К и Б.
    nutrients: Mapped[str] = mapped_column(String(8), nullable=False, default="kp", server_default="kp")
