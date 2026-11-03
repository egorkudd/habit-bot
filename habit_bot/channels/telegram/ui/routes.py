"""Обработчики канала: главное меню, «Ещё», отмена, ответы на непонятное (раздел 3.1 и раздел 3, «Отмена»)."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from habit_bot.channels.telegram.ui.callbacks import CancelCb, MenuCb
from habit_bot.channels.telegram.ui.menu import MORE_KEY, MenuRegistry, soon_text
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.identity import Actor

CANCEL_WORDS = frozenset({"отмена", "✕ отмена", "отменить"})
CANCELLED = "Отменено, ничего не записано."
NOTHING_TO_CANCEL = "Отменять нечего. Вот главное меню 👇"
MORE_TITLE = "Ещё:"
NOT_UNDERSTOOD = "Не понял. Выберите раздел в меню 👇"


def is_cancel_word(text: str | None) -> bool:
    return bool(text) and text.strip().lower() in CANCEL_WORDS  # type: ignore[union-attr]


def build_core_router(menu: MenuRegistry, screens: Screens) -> Router:
    """Подключается первым: отмена и меню работают в любом состоянии ввода."""
    router = Router(name="core")

    def soon_label(text: str | None) -> bool:
        entry = menu.by_label(text)
        return entry is not None and (entry.key == MORE_KEY or not entry.ready)

    def soon_key(key: str) -> bool:
        entry = menu.get(key)
        return entry is not None and not entry.ready

    async def cancel(bot: Bot, chat_id: int, actor: Actor, state: FSMContext) -> None:
        had_input = await state.get_state() is not None or bool(await state.get_data())
        await state.clear()
        await screens.home(bot, chat_id, actor, CANCELLED if had_input else NOTHING_TO_CANCEL)

    @router.message(Command("cancel"))
    @router.message(F.text.func(is_cancel_word))
    async def cancel_by_text(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await cancel(bot, message.chat.id, actor, state)

    @router.callback_query(CancelCb.filter())
    async def cancel_by_button(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await screens.close_buttons(query)
        await cancel(bot, query.from_user.id, actor, state)

    @router.message(F.text.func(soon_label))
    async def home_button(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        entry = menu.by_label(message.text)
        assert entry is not None
        await state.clear()  # переход в другой раздел закрывает незаконченный ввод
        if entry.key == MORE_KEY:
            await message.answer(MORE_TITLE, reply_markup=menu.more_keyboard(actor))
            return
        await screens.home(bot, message.chat.id, actor, soon_text(entry))

    @router.callback_query(MenuCb.filter(F.k.func(soon_key)))
    async def more_button(query: CallbackQuery, callback_data: MenuCb) -> None:
        entry = menu.get(callback_data.k)
        assert entry is not None
        await screens.close_buttons(query, toast=soon_text(entry))

    return router


def build_fallback_router(screens: Screens) -> Router:
    """Подключается последним: непонятный текст — подсказка, неизвестная кнопка — «Это меню устарело»."""
    router = Router(name="fallback")

    @router.message()
    async def not_understood(message: Message, bot: Bot, actor: Actor) -> None:
        await screens.home(bot, message.chat.id, actor, NOT_UNDERSTOOD)

    @router.callback_query()
    async def unknown_button(query: CallbackQuery, bot: Bot, actor: Actor) -> None:
        await screens.refuse_button(bot, query, actor, "UI-STALE")

    return router

