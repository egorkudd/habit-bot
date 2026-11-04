"""Таблицы модуля warmup (раздел 5): набор зарядки, зарядки и их упражнения, личные цели, цель «в день»."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from habit_bot.kernel.db import Base, PublicIdMixin, SoftDeleteMixin, TimestampMixin, UtcDateTime, VersionedMixin


class WarmupTemplate(PublicIdMixin, TimestampMixin, VersionedMixin, Base):
    """Упражнение набора зарядки: порядок и шаг. С частью 8 к нему добавится ссылка на базу упражнений."""

    __tablename__ = "warmup_template"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    short: Mapped[str] = mapped_column(String(24), nullable=False)
    measure: Mapped[str] = mapped_column(String(8), nullable=False)
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class WarmupSession(PublicIdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "warmup_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    logged_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class WarmupItem(Base):
    """Упражнение в зарядке: название и вид скопированы — правка набора не меняет прошлые зарядки."""

    __tablename__ = "warmup_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[int] = mapped_column(ForeignKey("warmup_session.id", ondelete="CASCADE"), nullable=False,
                                            index=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("warmup_template.id", ondelete="SET NULL"),
                                                    nullable=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    measure: Mapped[str] = mapped_column(String(8), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)


class WarmupGoal(PublicIdMixin, TimestampMixin, VersionedMixin, Base):
    """Личная цель по упражнению (``ExerciseGoal`` раздела 5): значение к дате."""

    __tablename__ = "warmup_goal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[int] = mapped_column(ForeignKey("warmup_template.id", ondelete="CASCADE"), nullable=False)
    target: Mapped[int] = mapped_column(Integer, nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_value: Mapped[int] = mapped_column(Integer, nullable=False)
    set_on: Mapped[date] = mapped_column(Date, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class WarmupSettings(Base):
    """Цель «зарядок в день» (раздел 3.11, по умолчанию 2). С частью 7 станет целью встроенной привычки."""

    __tablename__ = "warmup_settings"
    __table_args__ = (UniqueConstraint("user_id", name="uq_warmup_settings_user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    daily_goal: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
