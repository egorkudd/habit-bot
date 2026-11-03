"""Общие ответы канала: главное меню, «скоро», устаревшая или чужая кнопка."""

from __future__ import annotations

import logging
from contextlib import suppress

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from habit_bot.channels.telegram.ui.menu import MenuRegistry
from habit_bot.kernel.errors.catalog import user_message
from habit_bot.kernel.identity import Actor

log = logging.getLogger(__name__)


class Screens:
    def __init__(self, menu: MenuRegistry) -> None:
        self.menu = menu

    async def home(self, bot: Bot, chat_id: int, actor: Actor, text: str) -> Message:
        return await bot.send_message(chat_id, text, reply_markup=self.menu.home_keyboard(actor))

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
