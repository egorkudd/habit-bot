"""Общие ответы канала: главное меню, «скоро», устаревшая или чужая кнопка."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup

from habit_bot.channels.telegram.dialogs.policy import OTHER_DAY
from habit_bot.channels.telegram.dialogs.store import DialogStore
from habit_bot.channels.telegram.ui.menu import MenuEntry, MenuRegistry
from habit_bot.kernel.errors.catalog import user_message
from habit_bot.kernel.identity import Actor

log = logging.getLogger(__name__)


LayoutProvider = Callable[[Actor], Awaitable[Sequence[str] | None]]
ExtraProvider = Callable[[Actor], Awaitable[Sequence[MenuEntry]]]
LayoutSaver = Callable[[Actor, list[str] | None], Awaitable[None]]


async def _default_layout(actor: Actor) -> Sequence[str] | None:
    return None


async def _no_extra(actor: Actor) -> Sequence[MenuEntry]:
    return ()


async def _no_save(actor: Actor, layout: list[str] | None) -> None:
    return None


class Screens:
    """Главная клавиатура учитывает выбор пользователя («Настройки» → «Главный экран») и режим «Другой день»."""

    def __init__(self, menu: MenuRegistry, dialogs: DialogStore) -> None:
        self.menu = menu
        self.dialogs = dialogs
        self.layout: LayoutProvider = _default_layout
        self.save_layout: LayoutSaver = _no_save
        self.extras: ExtraProvider = _no_extra  # кнопки пользователя на главный экран (свои привычки, часть 7)

    async def home_keyboard(self, actor: Actor) -> ReplyKeyboardMarkup:
        other_day = await self.dialogs.day(actor.user_id, OTHER_DAY)
        extra = await self.extras(actor)  # до раскладки: модуль может сам поставить кнопку (стартовый набор)
        return self.menu.home_keyboard(actor, await self.layout(actor), other_day, extra)

    async def choosable(self, actor: Actor) -> list[MenuEntry]:
        """Что можно поставить на главный экран, со своими привычками пользователя."""
        return self.menu.choosable(actor, await self.extras(actor))

    async def set_on_home(self, actor: Actor, key: str, on: bool) -> bool:
        """Поставить кнопку на главный экран или убрать. ``False`` — экран полон (до 7 кнопок и «Ещё»)."""
        layout = list(await self.layout(actor) or self.menu.defaults(actor))
        if on and key not in layout:
            if len(layout) >= self.menu.HOME_LIMIT - 1:
                return False
            layout.append(key)
        elif not on and key in layout:
            layout.remove(key)
        else:
            return True
        await self.save_layout(actor, layout)
        return True

    async def more_keyboard(self, actor: Actor) -> InlineKeyboardMarkup:
        """«Ещё»: разделы, убранные с главного экрана, и пункты «Ещё»."""
        return self.menu.more_keyboard(actor, await self.layout(actor))

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
