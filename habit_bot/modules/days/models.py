"""``DayStatus`` (раздел 5): отметка «🛌 Выходной» — цели не проверяются, серии не прерываются."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from habit_bot.kernel.db import Base, PublicIdMixin, SoftDeleteMixin, TimestampMixin

DAY_OFF = "off"


class DayStatus(PublicIdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "days_status"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_days_status_user_id_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=DAY_OFF)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
