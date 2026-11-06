"""Чистый чат: промежуточные сообщения ввода удаляются, итог остаётся (раздел 3.1 требований, «Чистый чат»).

Пока пользователь что-то вводит, его сообщения и вопросы бота копятся в «следе» (``DialogState``, область
``trail``). Обработчик, который показывает итог (запись еды, зарядку, сохранённую настройку), вызывает
``result()``: сообщения, отправленные после этого, остаются, а след удаляется. «🏠 Домой» вызывает ``clean()``:
след удаляется без итога, а с 1.0.2 — и вся переписка за 48 часов, кроме файлов (``wipe()``, журнал
``ChatLog``). Сообщение с клавиатурой внизу не удаляется, пока не пришло следующее с клавиатурой,
иначе клиент Telegram может спрятать клавиатуру.

Оповещения администратору и сообщения фоновых задач в след не попадают: след ведётся только для сообщений в чат
того, чьё действие сейчас обрабатывается.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.exceptions import TelegramAPIError
from aiogram.methods import Response, SendMessage, TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import Message, ReplyKeyboardMarkup, ReplyKeyboardRemove, TelegramObject, Update

from habit_bot.channels.telegram.dialogs.policy import TRAIL
from habit_bot.channels.telegram.dialogs.store import DialogStore
from habit_bot.channels.telegram.ui.chat_log import ChatLog, Sent
from habit_bot.kernel.clock import Clock

log = logging.getLogger(__name__)
DELETE_CHUNK = 100  # Bot API deleteMessages: до 100 сообщений за раз
TRAIL_LIMIT = 300   # больше не храним: старые сообщения Telegram всё равно удалить не даст (48 часов)


@dataclass
class _Update:
    chat_id: int
    transient: list[int] = field(default_factory=list)
    keyboard: list[tuple[int, bool]] = field(default_factory=list)  # (сообщение с клавиатурой, итог ли это)
    discard: list[int] = field(default_factory=list)
    keep: list[int] = field(default_factory=list)
    result: bool = False
    clean: bool = False
    wipe: bool = False
    forget: bool = False
    sent: list[Sent] = field(default_factory=list)  # для журнала чата


_current: ContextVar[_Update | None] = ContextVar("trail_update", default=None)


def result() -> None:
    """Дальше — итог: сообщения после этого вызова остаются в чате, промежуточные удаляются."""
    current = _current.get()
    if current is not None:
        current.result = True


def clean() -> None:
    """«🏠 Домой»: удалить промежуточные сообщения без итога."""
    current = _current.get()
    if current is not None:
        current.clean = True


def wipe() -> None:
    """«🏠 Домой»: удалить всю переписку за 48 часов, кроме файлов и сообщения с клавиатурой этого ответа."""
    current = _current.get()
    if current is not None:
        current.clean = current.wipe = True


def forget() -> None:
    """Аккаунт удалён: след не сохранять (строки пользователя больше нет)."""
    current = _current.get()
    if current is not None:
        current.forget = True


def discard(message_id: int | None) -> None:
    """Удалить сообщение после ответа: старая карточка, которую заменила новая (×2, «Отменить», перенос)."""
    current = _current.get()
    if current is not None and message_id is not None:
        current.discard.append(message_id)


def keep(message_id: int | None) -> None:
    """Сообщение из следа стало итогом (его текст заменили итогом) — его не удалять."""
    current = _current.get()
    if current is not None and message_id is not None:
        current.keep.append(message_id)
        current.result = True


class TrailRecorder(BaseRequestMiddleware):
    """Сессия бота: запоминает номера сообщений, отправленных в чат текущего пользователя, и ведёт журнал чата
    (все отправленные сообщения, в том числе фоновых задач)."""

    def __init__(self, chat_log: ChatLog | None = None, clock: Clock | None = None) -> None:
        self._log = chat_log
        self._clock = clock

    async def __call__(
        self, make_request: NextRequestMiddlewareType[TelegramType], bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        response = await make_request(bot, method)
        current = _current.get()
        sent: object = response  # на деле сессия возвращает сам результат метода, а не Response
        request: object = method
        await self._journal(current, sent, request)
        if current is None or not isinstance(request, SendMessage) or not isinstance(sent, Message):
            return response
        if sent.chat.id != current.chat_id:
            return response  # оповещение администратору и другим людям — не наш след
        if isinstance(request.reply_markup, (ReplyKeyboardMarkup, ReplyKeyboardRemove)):
            current.keyboard.append((sent.message_id, current.result))
        elif not current.result:
            current.transient.append(sent.message_id)
        return response

    async def _journal(self, current: _Update | None, sent: object, request: object) -> None:
        if self._log is None or self._clock is None:
            return
        messages = [m for m in (sent if isinstance(sent, list) else [sent])
                    if isinstance(m, Message) and m.chat.type == "private"]
        if not messages:
            return
        keyboard = isinstance(getattr(request, "reply_markup", None), ReplyKeyboardMarkup)
        items = [Sent(m.message_id, file=m.document is not None, keyboard=keyboard) for m in messages]
        if current is not None and messages[0].chat.id == current.chat_id:
            current.sent += items
            return  # запишется после ответа: обработчик мог ещё не закончить свою транзакцию
        try:  # фоновая задача или оповещение другому человеку
            await self._log.record(messages[0].chat.id, items, self._clock.now())
        except Exception:
            log.warning("Не удалось записать сообщение в журнал чата", exc_info=True)


def chat_of(update: Update) -> tuple[int | None, int | None]:
    """(чат, входящее сообщение пользователя) — только личный чат с ботом."""
    if update.message is not None and update.message.chat.type == "private":
        return update.message.chat.id, update.message.message_id
    if update.callback_query is not None:
        return update.callback_query.from_user.id, None
    return None, None


class TrailMiddleware(BaseMiddleware):
    """Самый внешний: ведёт след апдейта и после ответа удаляет лишнее."""

    def __init__(self, store: DialogStore, clock: Clock, chat_log: ChatLog | None = None) -> None:
        self._store = store
        self._clock = clock
        self._log = chat_log

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update):
            return await handler(event, data)
        chat_id, incoming = chat_of(event)
        if chat_id is None:
            return await handler(event, data)
        current = _Update(chat_id=chat_id, transient=[incoming] if incoming is not None else [],
                          sent=[Sent(incoming)] if incoming is not None else [])
        token = _current.set(current)
        try:
            return await handler(event, data)
        finally:
            _current.reset(token)
            actor = data.get("actor")
            bot: Bot | None = data.get("bot")
            if actor is not None and bot is not None and not current.forget:
                try:
                    await self._settle(bot, actor.user_id, current)
                except Exception:  # чистота чата не должна ломать ответ пользователю
                    log.warning("Не удалось обновить след сообщений", exc_info=True)

    async def _settle(self, bot: Bot, user_id: int, current: _Update) -> None:
        now: datetime = self._clock.now()
        saved = await self._store.get(user_id, TRAIL)
        ids: list[int] = list(saved.data.get("ids", [])) if saved else []
        holder: int | None = saved.data.get("kb") if saved else None
        ids += current.transient
        for message_id, is_result in current.keyboard:
            if holder is not None:
                ids.append(holder)  # прежняя клавиатура больше не нужна: новая пришла
            holder = None if is_result else message_id  # итог с клавиатурой остаётся навсегда
        doomed = list(current.discard)
        if current.result or current.clean:
            doomed += ids
            ids = []
        if self._log is not None:
            if current.sent:
                await self._log.record(current.chat_id, current.sent, now)
            if current.wipe:
                doomed += await self._log.deletable(current.chat_id, now)
        doomed = [i for i in doomed if i not in current.keep and i != holder]
        if doomed:
            await delete_all(bot, current.chat_id, doomed)
            if self._log is not None:
                await self._log.forget(current.chat_id, doomed)
        ids = ids[-TRAIL_LIMIT:]
        await self._store.set_data(user_id, TRAIL, {"ids": ids, "kb": holder} if ids or holder else {}, now)


async def delete_all(bot: Bot, chat_id: int, message_ids: list[int]) -> None:
    unique = sorted(set(message_ids))
    for start in range(0, len(unique), DELETE_CHUNK):
        with suppress(TelegramAPIError):  # старше 48 часов или уже удалено — Telegram пропустит или откажет
            await bot.delete_messages(chat_id, unique[start: start + DELETE_CHUNK])
