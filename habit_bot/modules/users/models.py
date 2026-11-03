"""Таблицы модуля users (раздел 5): профиль, цели КБЖУ, приглашения, вес тела."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from habit_bot.kernel.db import (
    Base,
    PublicIdMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UtcDateTime,
    VersionedMixin,
    utcnow,
)

DEFAULT_TIMEZONE = "Europe/Moscow"


class Profile(PublicIdMixin, TimestampMixin, VersionedMixin, Base):
    """Текущее состояние: пол, дата рождения, рост, вес, активность, цель, опыт, город, часовой пояс."""

    __tablename__ = "users_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    sex: Mapped[str] = mapped_column(String(8), nullable=False)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    height_cm: Mapped[float] = mapped_column(Float, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    activity: Mapped[str] = mapped_column(String(16), nullable=False)
    goal_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    target_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    experience: Mapped[str] = mapped_column(String(16), nullable=False)
    city_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    city_region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    city_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    city_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default=DEFAULT_TIMEZONE)
    starter_kit: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    bands: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    has_small_plates: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    show_all_exercises: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ask_feeling: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Goal(PublicIdMixin, Base):
    """История целей КБЖУ: новая цель — новая строка с датой начала, прошлые дни считаются по старой."""

    __tablename__ = "users_goal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    kcal: Mapped[float] = mapped_column(Float, nullable=False)
    protein: Mapped[float] = mapped_column(Float, nullable=False)
    fat: Mapped[float] = mapped_column(Float, nullable=False)
    carbs: Mapped[float] = mapped_column(Float, nullable=False)
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    target_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # calc / manual
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class Invite(PublicIdMixin, Base):
    __tablename__ = "users_invite"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False)
    uses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class BodyWeight(PublicIdMixin, TimestampMixin, SoftDeleteMixin, Base):
    """История веса тела: вес из профиля пишется и сюда (раздел 3.0)."""

    __tablename__ = "users_body_weight"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_users_body_weight_user_id_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
