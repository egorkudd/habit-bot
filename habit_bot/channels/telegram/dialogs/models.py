"""``DialogState`` (раздел 5): незаконченный ввод в Telegram. Сами записи сюда не попадают."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from habit_bot.kernel.db import Base, PublicIdMixin, TimestampMixin, UtcDateTime


class DialogState(PublicIdMixin, TimestampMixin, Base):
    """Одна строка на пользователя и область: «dialog» (текущий ввод), «other_day», «workout», «onboarding».

    ``token`` — номер этого ввода: его несут кнопки, и после сброса или отмены они устаревают.
    ``version`` растёт при каждом изменении (раздел 5, служебные поля).
    """

    __tablename__ = "dialog_states"
    __table_args__ = (UniqueConstraint("user_id", "scope", name="uq_dialog_states_user_id_scope"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    other_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    token: Mapped[int] = mapped_column(Integer, nullable=False)
    last_action_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
