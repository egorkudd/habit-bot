"""Telegram-часть модуля users: вход в каждом апдейте и команда /start."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot, Router
from aiogram.filters import CommandStart
from aiogram.types import Message, TelegramObject
from aiogram.types import User as TgUser

from habit_bot import __version__
from habit_bot.channels.telegram.ui.menu import MenuRegistry
from habit_bot.kernel.errors.catalog import user_message
from habit_bot.kernel.identity import Actor
from habit_bot.kernel.logs import current_user_id
from habit_bot.modules.users.usecases import SignInTelegram

ADMIN_GREETING = (
    "Привет, администратор 👋\n"
    "Бот работает, версия {version}. Меню внизу; разделы появятся в следующих частях.\n"
    "/check — проверка ввода чисел, времени и дат, /cancel — отмена ввода."
)
USER_GREETING = "Привет! Меню внизу; разделы появятся в следующих частях."


class AuthMiddleware(BaseMiddleware):
    """Пускает только зарегистрированных; остальным — «Бот доступен по приглашению»."""

    def __init__(self, sign_in: SignInTelegram) -> None:
        self._sign_in = sign_in

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return None
        actor = await self._sign_in.execute(tg_user.id, tg_user.full_name)
        if actor is None:
            bot: Bot = data["bot"]
            await bot.send_message(tg_user.id, user_message("ACCESS-NO-INVITE"))
            return None
        data["actor"] = actor
        current_user_id.set(actor.user_id)
        return await handler(event, data)


def build_router(menu: MenuRegistry) -> Router:
    router = Router(name="users")

    @router.message(CommandStart())
    async def start(message: Message, actor: Actor) -> None:
        text = ADMIN_GREETING.format(version=__version__) if actor.is_admin else USER_GREETING
        await message.answer(text, reply_markup=menu.home_keyboard(actor))

    return router
