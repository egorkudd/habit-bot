"""Таблицы модуля food (раздел 5): продукты и рецепты (FoodItem), записи еды (FoodEntry)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from habit_bot.kernel.db import Base, PublicIdMixin, SoftDeleteMixin, TimestampMixin, UtcDateTime, VersionedMixin


class FoodItem(PublicIdMixin, TimestampMixin, VersionedMixin, Base):
    """Рецепт или продукт. ``user_id`` пустой — общий каталог (только читается и копируется)."""

    __tablename__ = "food_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
                                                index=True)
    catalog_key: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # recipe / product
    composition: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(16), nullable=False)  # portion / 100g / piece
    portion_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kcal: Mapped[float] = mapped_column(Float, nullable=False)
    protein: Mapped[float] = mapped_column(Float, nullable=False)
    fat: Mapped[float] = mapped_column(Float, nullable=False)
    carbs: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_catalog_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FoodEntry(PublicIdMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Запись еды: значения скопированы на момент записи (раздел 4.2)."""

    __tablename__ = "food_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    logged_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    food_item_id: Mapped[int | None] = mapped_column(ForeignKey("food_item.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    portion_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kcal: Mapped[float] = mapped_column(Float, nullable=False)
    protein: Mapped[float] = mapped_column(Float, nullable=False)
    fat: Mapped[float] = mapped_column(Float, nullable=False)
    carbs: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # button / other / text
