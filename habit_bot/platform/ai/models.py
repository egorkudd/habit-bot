"""``AiCommand`` (раздел 5): разборы текста — текст, действия, статус, токены и стоимость. Хранятся 30 дней."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from habit_bot.kernel.db import Base, PublicIdMixin, TimestampMixin, UtcDateTime


class AiCommand(PublicIdMixin, TimestampMixin, Base):
    __tablename__ = "ai_command"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)  # логический день разбора — для лимита «50 в сутки»
    mode: Mapped[str] = mapped_column(String(8), nullable=False, default="text")  # text / fill
    text: Mapped[str] = mapped_column(Text, nullable=False)
    actions: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)  # ops, skipped, question
    undo: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # pending / done / cancelled / undone / error
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    done_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
