"""Журнал сообщений чата за 48 часов — для «🏠 Домой», которое очищает всю переписку (правки 1.0.2).

Бот не может прочитать историю чата, поэтому запоминает номера сообщений сам: входящие от пользователя и все
свои, в том числе от фоновых задач. Удалить Telegram даёт только сообщения не старше 48 часов, поэтому строки
старше удаляются при каждой записи. Файлы (экспорт, бэкап) помечаются «оставить»: «Домой» их не трогает.
Содержимое сообщений не хранится — только номер чата, номер сообщения и время.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import BigInteger, Boolean, Integer, UniqueConstraint, delete, select
from sqlalchemy.orm import Mapped, mapped_column

from habit_bot.kernel.db import Base, UowFactory, UtcDateTime

KEEP_FOR = timedelta(hours=47)  # чуть меньше 48 часов: удаление на границе Telegram может не принять


class ChatMessage(Base):
    """Номер сообщения в личном чате с ботом. Без внешнего ключа: фоновые задачи знают только номер чата."""

    __tablename__ = "chat_messages"
    __table_args__ = (UniqueConstraint("chat_id", "message_id", name="uq_chat_messages_chat_id_message_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    kept: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sent_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)


class ChatLog:
    def __init__(self, uow: UowFactory) -> None:
        self._uow = uow

    async def record(self, chat_id: int, message_ids: Sequence[int], now: datetime, *, kept: bool = False) -> None:
        async with self._uow() as uow:
            await uow.session.execute(delete(ChatMessage).where(ChatMessage.sent_at < now - KEEP_FOR))
            known = set((await uow.session.execute(select(ChatMessage.message_id).where(
                ChatMessage.chat_id == chat_id, ChatMessage.message_id.in_(message_ids)))).scalars())
            for message_id in dict.fromkeys(message_ids):
                if message_id not in known:
                    uow.session.add(ChatMessage(chat_id=chat_id, message_id=message_id, kept=kept, sent_at=now))

    async def deletable(self, chat_id: int, now: datetime) -> list[int]:
        """Сообщения чата за 47 часов, кроме файлов."""
        async with self._uow() as uow:
            rows = await uow.session.execute(select(ChatMessage.message_id).where(
                ChatMessage.chat_id == chat_id, ChatMessage.sent_at >= now - KEEP_FOR,
                ChatMessage.kept.is_(False)))
            return sorted(rows.scalars())

    async def forget(self, chat_id: int, message_ids: Sequence[int]) -> None:
        async with self._uow() as uow:
            await uow.session.execute(delete(ChatMessage).where(
                ChatMessage.chat_id == chat_id, ChatMessage.message_id.in_(list(message_ids))))
