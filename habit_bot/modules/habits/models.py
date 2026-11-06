"""Таблицы модуля habits (раздел 5): свои привычки (Habit) и их записи (HabitEntry)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from habit_bot.kernel.db import Base, PublicIdMixin, SoftDeleteMixin, TimestampMixin, UtcDateTime, VersionedMixin


class Habit(PublicIdMixin, TimestampMixin, VersionedMixin, Base):
    """Своя привычка. Показ на главном экране хранится в профиле (кнопки главного экрана) — одна правда.

    ``step`` пустой — нажатие спрашивает число («Шаги», «Сон»); ``weekdays`` пустой — каждый день.
    """

    __tablename__ = "habits_habit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="custom")
    template_key: Mapped[str | None] = mapped_column(String(16), nullable=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    short: Mapped[str] = mapped_column(String(20), nullable=False)
    emoji: Mapped[str] = mapped_column(String(8), nullable=False)
    measure: Mapped[str] = mapped_column(String(8), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    goal: Mapped[float | None] = mapped_column(Float, nullable=True)
    step: Mapped[float | None] = mapped_column(Float, nullable=True)
    quick_values: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    weekdays: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")  # active / archived


class HabitEntry(PublicIdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "habits_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    habit_id: Mapped[int] = mapped_column(ForeignKey("habits_habit.id", ondelete="CASCADE"), nullable=False,
                                          index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    logged_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)  # button / list / many / text


class BuiltinArchive(Base):
    """Встроенная привычка списка («🍽 Еда», «🤸 Зарядка», «🏋️ Тренировки за неделю») убрана в архив: не видна в
    «✅ Привычки» и в светофоре «Итогов». Раздел и его записи остаются."""

    __tablename__ = "habits_builtin_archive"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_habits_builtin_archive_user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(16), nullable=False)
