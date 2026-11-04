"""Telegram-часть модуля users: вход в каждом апдейте (с кодом приглашения из ссылки) и команда /start."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot, Router
from aiogram.filters import CommandStart
from aiogram.types import Message, TelegramObject, Update
from aiogram.types import User as TgUser

from habit_bot import __version__
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.identity import Actor
from habit_bot.kernel.logs import current_user_id
from habit_bot.modules.users.usecases import SignInTelegram

ADMIN_GREETING = (
    "Привет, администратор 👋\n"
    "Бот работает, версия {version}. Меню внизу; пригласить близких — «☰ Ещё» → «🛠 Админ».\n"
    "/check — проверка ввода чисел, времени и дат, /cancel — отмена ввода."
)
USER_GREETING = "Привет, {name}! Меню внизу 👇"


def invite_code(event: TelegramObject) -> str | None:
    """Код из ссылки-приглашения: t.me/бот?start=КОД приходит как «/start КОД»."""
    message = event.message if isinstance(event, Update) else None
    text = message.text if message is not None else None
    if not text or not text.startswith("/start "):
        return None
    return text.split(maxsplit=1)[1].strip() or None


class AuthMiddleware(BaseMiddleware):
    """Пускает зарегистрированных, администраторов из списка и гостей с действующим приглашением."""

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
        try:
            actor = await self._sign_in.execute(tg_user.id, tg_user.full_name, invite_code=invite_code(event))
        except AppError as err:
            bot: Bot = data["bot"]
            await bot.send_message(tg_user.id, err.user_text())
            return None
        data["actor"] = actor
        current_user_id.set(actor.user_id)
        return await handler(event, data)


def build_router(screens: Screens, names: Callable[[Actor], Awaitable[str]]) -> Router:
    router = Router(name="users")

    @router.message(CommandStart())
    async def start(message: Message, bot: Bot, actor: Actor) -> None:
        if actor.is_admin:
            text = ADMIN_GREETING.format(version=__version__)
        else:
            text = USER_GREETING.format(name=await names(actor))
        await screens.home(bot, message.chat.id, actor, text)

    return router
