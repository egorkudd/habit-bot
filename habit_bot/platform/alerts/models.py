from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from habit_bot.kernel.db import Base, UtcDateTime


class AdminAlert(Base):
    """Оповещение администратору; одинаковые за час склеиваются в одно со счётчиком (раздел 7.4.2)."""

    __tablename__ = "admin_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    window_start: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Куда отправлено: [[chat_id, message_id], …] — чтобы обновлять счётчик в том же сообщении.
    messages: Mapped[list[list[int]]] = mapped_column(JSON, nullable=False, default=list)
