"""Telegram-канал: всё, что знает про aiogram (архитектура, раздел 7.5)."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

from aiogram import BaseMiddleware, Bot, Dispatcher, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.session.base import BaseSession
from aiogram.client.telegram import PRODUCTION, TelegramAPIServer
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message, TelegramObject, Update

from habit_bot.kernel.config import Settings
from habit_bot.kernel.errors import AppError, new_incident_id
from habit_bot.kernel.errors.catalog import user_message
from habit_bot.kernel.logs import current_handler, current_user_id

log = logging.getLogger(__name__)
PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # каталог habit_bot/

FALLBACK_TEXT = "Этот раздел появится в следующих частях. Напишите /start."


class Alerter(Protocol):
    async def alert(self, code: str, *, where: str, **params: object) -> None: ...


def build_session(settings: Settings) -> AiohttpSession:
    """Адрес Bot API и прокси задаются в .env (раздел 7)."""
    api = TelegramAPIServer.from_base(settings.bot_api_base) if settings.bot_api_base else PRODUCTION
    return AiohttpSession(api=api, proxy=settings.telegram_proxy)


def chat_id_of(update: Update) -> int | None:
    if update.message is not None:
        return update.message.chat.id
    if update.callback_query is not None and update.callback_query.from_user is not None:
        return update.callback_query.from_user.id
    return None


def error_location(exc: BaseException) -> tuple[str, str]:
    """Где упало в коде бота: («modules.users.telegram.handlers.start», «modules/users/telegram/handlers.py:42»)."""
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename.startswith(str(PACKAGE_ROOT))]
    if not frames:
        return "обработчик", "вне кода бота"
    frame = frames[-1]
    relative = Path(frame.filename).relative_to(PACKAGE_ROOT)
    module = ".".join(relative.with_suffix("").parts)
    return f"{module}.{frame.name}", f"{relative.as_posix()}:{frame.lineno}"


class ErrorMiddleware(BaseMiddleware):
    """Любая ошибка: пользователь видит понятный текст с кодом, администратор — оповещение (раздел 7.4)."""

    def __init__(self, alerter: Alerter | None) -> None:
        self._alerter = alerter

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except AppError as err:
            await self._reply(data, event, err.user_text())
            return None
        except Exception as exc:
            incident = new_incident_id()
            where, location = error_location(exc)
            actor = data.get("actor")
            user = getattr(actor, "user_id", "?")
            log.exception("Внутренняя ошибка", extra={"code": "INTERNAL", "incident": incident, "handler": where})
            await self._reply(data, event, user_message("INTERNAL", {"incident": incident}))
            if self._alerter is not None:
                await self._alerter.alert(
                    "INTERNAL", where=where, incident=incident, user=user,
                    detail=f"{type(exc).__name__} {exc} в {location}", signature=f"{type(exc).__name__}@{location}",
                )
            return None
        finally:
            current_user_id.set(None)
            current_handler.set(None)

    @staticmethod
    async def _reply(data: dict[str, Any], event: TelegramObject, text: str) -> None:
        bot: Bot | None = data.get("bot")
        chat_id = chat_id_of(event) if isinstance(event, Update) else None
        if bot is None or chat_id is None or not text:
            return
        try:
            await bot.send_message(chat_id, text)
        except TelegramAPIError:
            log.warning("Не удалось отправить сообщение об ошибке", extra={"code": "INTERNAL"})


class TelegramNotifier:
    """Отправка оповещений администратору через того же бота."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send(self, chat_id: int, text: str) -> int | None:
        try:
            message = await self._bot.send_message(chat_id, text)
        except TelegramAPIError:
            log.warning("Администратор %s недоступен для оповещений", chat_id)
            return None
        return message.message_id

    async def edit(self, chat_id: int, message_id: int, text: str) -> bool:
        try:
            await self._bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id)
        except TelegramAPIError:
            return False
        return True


class TelegramChannel:
    name = "telegram"

    def __init__(self, settings: Settings, *, session: BaseSession | None = None) -> None:
        self.bot = Bot(settings.bot_token, session=session or build_session(settings))
        self.dispatcher = Dispatcher()
        self.notifier = TelegramNotifier(self.bot)
        self._error_middleware = ErrorMiddleware(None)
        self.dispatcher.update.outer_middleware(self._error_middleware)
        self._fallback_added = False

    def set_alerter(self, alerter: Alerter) -> None:
        self._error_middleware._alerter = alerter

    def add_outer_middleware(self, middleware: BaseMiddleware) -> None:
        self.dispatcher.update.outer_middleware(middleware)

    def add_router(self, router: Router) -> None:
        self.dispatcher.include_router(router)

    def finalize(self) -> None:
        """Последним подключается ответ на всё, что модули не обработали."""
        if self._fallback_added:
            return
        fallback = Router(name="fallback")

        @fallback.message()
        async def _fallback(message: Message) -> None:
            await message.answer(FALLBACK_TEXT)

        self.dispatcher.include_router(fallback)
        self._fallback_added = True

    async def start(self) -> None:  # pragma: no cover — долгий опрос Telegram проверяется пробным запуском в CI
        self.finalize()
        await self.dispatcher.start_polling(self.bot)

    async def stop(self) -> None:
        await self.bot.session.close()
