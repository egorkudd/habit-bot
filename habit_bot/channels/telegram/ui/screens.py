"""Общие ответы канала: главное меню, «скоро», устаревшая или чужая кнопка."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, ReplyKeyboardMarkup

from habit_bot.channels.telegram.dialogs.policy import OTHER_DAY
from habit_bot.channels.telegram.dialogs.store import DialogStore
from habit_bot.channels.telegram.ui.menu import MenuRegistry
from habit_bot.kernel.errors.catalog import user_message
from habit_bot.kernel.identity import Actor

log = logging.getLogger(__name__)


LayoutProvider = Callable[[Actor], Awaitable[Sequence[str] | None]]


async def _default_layout(actor: Actor) -> Sequence[str] | None:
    return None


class Screens:
    """Главная клавиатура учитывает выбор пользователя («Настройки» → «Главный экран») и режим «Другой день»."""

    def __init__(self, menu: MenuRegistry, dialogs: DialogStore) -> None:
        self.menu = menu
        self.dialogs = dialogs
        self.layout: LayoutProvider = _default_layout

    async def home_keyboard(self, actor: Actor) -> ReplyKeyboardMarkup:
        other_day = await self.dialogs.day(actor.user_id, OTHER_DAY)
        return self.menu.home_keyboard(actor, await self.layout(actor), other_day)

    async def home(self, bot: Bot, chat_id: int, actor: Actor, text: str, *, parse_mode: str | None = None) -> Message:
        return await bot.send_message(chat_id, text, reply_markup=await self.home_keyboard(actor),
                                      parse_mode=parse_mode)

    async def refuse_button(self, bot: Bot, query: CallbackQuery, actor: Actor, code: str) -> None:
        """«Это меню устарело» или чужая кнопка: убрать кнопки, ответить и показать главное меню."""
        await self.close_buttons(query)
        await self.home(bot, query.from_user.id, actor, user_message(code))

    @staticmethod
    async def close_buttons(query: CallbackQuery, toast: str | None = None) -> None:
        """Ответить на нажатие и убрать кнопки под сообщением, чтобы их не нажали второй раз."""
        with suppress(TelegramAPIError):
            await query.answer(toast)
        if query.message is not None and isinstance(query.message, Message):
            with suppress(TelegramAPIError):
                await query.message.edit_reply_markup(reply_markup=None)
