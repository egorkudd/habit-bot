"""Таблицы модуля workouts (раздел 5): база упражнений (Exercise), тренировки (WorkoutSession), подходы
(WorkoutSet), настройки тренировок."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from habit_bot.kernel.db import Base, PublicIdMixin, SoftDeleteMixin, TimestampMixin, UtcDateTime, VersionedMixin


class Exercise(PublicIdMixin, TimestampMixin, VersionedMixin, Base):
    """Упражнение. ``user_id`` пустой — общая база (раздел 3.4.1); своё — «Новое упражнение»."""

    __tablename__ = "workouts_exercise"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
                                                index=True)
    catalog_key: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    place: Mapped[str] = mapped_column(String(8), nullable=False)
    equipment: Mapped[str] = mapped_column(String(16), nullable=False)
    group: Mapped[str] = mapped_column(String(16), nullable=False)
    primary: Mapped[str] = mapped_column(String(16), nullable=False)
    secondary: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    movement: Mapped[str] = mapped_column(String(16), nullable=False)
    compound: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False)
    measure: Mapped[str] = mapped_column(String(16), nullable=False)
    floor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    suggest: Mapped[str] = mapped_column(String(4), nullable=False, default="all")
    loaded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    easier_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    harder_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    weight_step: Mapped[float | None] = mapped_column(Float, nullable=True)
    reps_low: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    reps_high: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    per_dumbbell: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class WorkoutSession(PublicIdMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Тренировка: открыта, пока не нажали «Завершить» или не прошло 3 часа без действий (раздел 3)."""

    __tablename__ = "workouts_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="open")  # open / done
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_action_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tonnage: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    band: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    missing: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    auto_finished: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class WorkoutSet(PublicIdMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Подход. Название и измерение скопированы — правка упражнения не меняет прошлое."""

    __tablename__ = "workouts_set"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[int] = mapped_column(ForeignKey("workouts_session.id", ondelete="CASCADE"), nullable=False,
                                            index=True)
    exercise_id: Mapped[int | None] = mapped_column(ForeignKey("workouts_exercise.id", ondelete="SET NULL"),
                                                    nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    measure: Mapped[str] = mapped_column(String(16), nullable=False)
    per_dumbbell: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    reps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    band: Mapped[str | None] = mapped_column(String(8), nullable=True)


class WorkoutSettings(Base):
    """Цель «тренировок в неделю» (по умолчанию 3), резинки, «Показывать все упражнения», прошлый ответ
    «Резинка с собой?»."""

    __tablename__ = "workouts_settings"
    __table_args__ = (UniqueConstraint("user_id", name="uq_workouts_settings_user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    weekly_goal: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    bands: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    show_all: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    band_last: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
