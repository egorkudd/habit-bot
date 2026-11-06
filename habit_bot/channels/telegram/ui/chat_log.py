"""Журнал сообщений чата за 48 часов — для «🏠 Домой», которое очищает всю переписку (правки 1.0.2).

Бот не может прочитать историю чата, поэтому запоминает номера сообщений сам: входящие от пользователя и все
свои, в том числе от фоновых задач. Удалить Telegram даёт только сообщения не старше 48 часов, поэтому строки
старше удаляются при каждой записи. Файлы (экспорт, бэкап) помечаются «оставить»: «Домой» их не трогает.
Каждую ночь в 04:00 по времени бота переписка очищается так же, но остаётся последнее сообщение с клавиатурой.
Содержимое сообщений не хранится — только номер чата, номер сообщения и время.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta, tzinfo

from sqlalchemy import BigInteger, Boolean, Integer, UniqueConstraint, delete, select
from sqlalchemy.orm import Mapped, mapped_column

from habit_bot.kernel.db import Base, UowFactory, UtcDateTime

KEEP_FOR = timedelta(hours=47)  # чуть меньше 48 часов: удаление на границе Telegram может не принять
NIGHT = time(4, 0)              # ежедневная чистка: всё, что прислано до 04:00, удаляется (граница суток — тоже 04:00)


@dataclass(frozen=True, slots=True)
class Sent:
    message_id: int
    file: bool = False      # экспорт, бэкап — «Домой» и ночная чистка их не трогают
    keyboard: bool = False  # с клавиатурой внизу: последнее такое ночная чистка оставляет, иначе клавиатура пропадёт


class ChatMessage(Base):
    """Номер сообщения в личном чате с ботом. Без внешнего ключа: фоновые задачи знают только номер чата."""

    __tablename__ = "chat_messages"
    __table_args__ = (UniqueConstraint("chat_id", "message_id", name="uq_chat_messages_chat_id_message_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    kept: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    keyboard: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sent_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)


def last_night(now: datetime, tz: tzinfo) -> datetime:
    """Последние 04:00 по времени бота — до этого момента переписка уже должна быть очищена."""
    local = now.astimezone(tz)
    night = datetime.combine(local.date(), NIGHT, tzinfo=tz)
    return night if local >= night else night - timedelta(days=1)


class ChatLog:
    def __init__(self, uow: UowFactory) -> None:
        self._uow = uow

    async def record(self, chat_id: int, sent: Sequence[Sent], now: datetime) -> None:
        async with self._uow() as uow:
            await uow.session.execute(delete(ChatMessage).where(ChatMessage.sent_at < now - KEEP_FOR))
            ids = [s.message_id for s in sent]
            known = set((await uow.session.execute(select(ChatMessage.message_id).where(
                ChatMessage.chat_id == chat_id, ChatMessage.message_id.in_(ids)))).scalars())
            for item in {s.message_id: s for s in sent}.values():
                if item.message_id not in known:
                    uow.session.add(ChatMessage(chat_id=chat_id, message_id=item.message_id, kept=item.file,
                                                keyboard=item.keyboard, sent_at=now))

    async def deletable(self, chat_id: int, now: datetime) -> list[int]:
        """Сообщения чата за 47 часов, кроме файлов."""
        async with self._uow() as uow:
            rows = await uow.session.execute(select(ChatMessage.message_id).where(
                ChatMessage.chat_id == chat_id, ChatMessage.sent_at >= now - KEEP_FOR,
                ChatMessage.kept.is_(False)))
            return sorted(rows.scalars())

    async def before(self, moment: datetime, now: datetime) -> dict[int, list[int]]:
        """Ночная чистка: по чатам — сообщения, присланные до ``moment``, кроме файлов и последнего сообщения
        с клавиатурой (без него клиент Telegram может спрятать клавиатуру)."""
        async with self._uow() as uow:
            rows = (await uow.session.execute(select(ChatMessage).where(
                ChatMessage.sent_at >= now - KEEP_FOR).order_by(ChatMessage.message_id))).scalars().all()
        holder = {r.chat_id: r.message_id for r in rows if r.keyboard}
        found: dict[int, list[int]] = {}
        for r in rows:
            if r.sent_at < moment and not r.kept and r.message_id != holder.get(r.chat_id):
                found.setdefault(r.chat_id, []).append(r.message_id)
        return found

    async def forget(self, chat_id: int, message_ids: Sequence[int]) -> None:
        async with self._uow() as uow:
            await uow.session.execute(delete(ChatMessage).where(
                ChatMessage.chat_id == chat_id, ChatMessage.message_id.in_(list(message_ids))))
