"""«📊 Итоги» в Telegram (раздел 3.8): картинка дня по выбранной привычке с «◀ / ▶» и «Текстом», обзор-светофор
«Неделя» / «Месяц» / «3 месяца». Картинка меняется в том же сообщении — чат не засоряется."""

from __future__ import annotations

import html
from datetime import date, timedelta

from aiogram import Bot, F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from habit_bot.channels.telegram.render.stats import day_png, day_text, overview_png, overview_text
from habit_bot.channels.telegram.ui import trail
from habit_bot.channels.telegram.ui.callbacks import MenuCb
from habit_bot.channels.telegram.ui.layout import fit_rows, inline
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.domain.formatting import format_day
from habit_bot.kernel.identity import Actor
from habit_bot.modules.stats.domain.periods import LABELS, Kind
from habit_bot.modules.stats.usecases import Section, Stats

KEY = "stats"
NO_SECTIONS = "📊 Итоги: пока нечего показать — включите разделы в настройках."


class StCb(CallbackData, prefix="st"):
    o: int
    t: int
    a: str
    v: str


def _day_code(day: date) -> str:
    return f"{day:%y%m%d}"


def _parse_day(code: str, fallback: date) -> date:
    try:
        return date(2000 + int(code[:2]), int(code[2:4]), int(code[4:6]))
    except (ValueError, IndexError):
        return fallback


def build_stats_router(stats: Stats, screens: Screens) -> tuple[Router, Router]:
    router = Router(name="stats")
    nav = Router(name="stats.nav")

    def btn(actor: Actor, text: str, action: str, value: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=StCb(o=actor.user_id, t=0, a=action, v=value).pack())

    def day_markup(actor: Actor, key: str, day: date, sections: list[Section]) -> InlineKeyboardMarkup:
        code = _day_code(day)
        choice = [btn(actor, ("▸ " if s.key == key else "") + s.label + (" •" if s.has_data else ""), "sec",
                      f"{s.key}.{code}") for s in sections]
        rows = fit_rows(choice, 3)
        move = [btn(actor, f"◀ {format_day(day - timedelta(days=1))}", "sec",
                    f"{key}.{_day_code(day - timedelta(days=1))}"),
                btn(actor, "📝 Текстом", "text", f"{key}.{code}")]
        if day < stats.today():
            move.append(btn(actor, f"{format_day(day + timedelta(days=1))} ▶", "sec",
                            f"{key}.{_day_code(day + timedelta(days=1))}"))
        rows.append(move)
        rows.append([btn(actor, LABELS[k], "per", f"{k.value}0") for k in Kind])
        return inline(rows)

    def period_markup(actor: Actor, kind: Kind, shift: int) -> InlineKeyboardMarkup:
        move = [btn(actor, "◀", "per", f"{kind.value}{shift - 1}"),
                btn(actor, "📝 Текстом", "ptext", f"{kind.value}{shift}")]
        if shift < 0:
            move.append(btn(actor, "▶", "per", f"{kind.value}{shift + 1}"))
        kinds = [btn(actor, ("▸ " if k is kind else "") + LABELS[k], "per", f"{k.value}0") for k in Kind]
        return inline([move, kinds, [btn(actor, "📊 День", "sec", f"last.{_day_code(stats.today())}")]])

    async def send_photo(bot: Bot, chat_id: int, query: CallbackQuery | None, png: bytes, caption: str,
                         markup: InlineKeyboardMarkup) -> None:
        photo = BufferedInputFile(png, filename="stats.png")
        message = query.message if query is not None else None
        if isinstance(message, Message) and message.photo:
            await bot.edit_message_media(InputMediaPhoto(media=photo, caption=caption), chat_id=chat_id,
                                         message_id=message.message_id, reply_markup=markup)
            return
        trail.result()
        await bot.send_photo(chat_id, photo, caption=caption, reply_markup=markup)

    async def show_day(bot: Bot, chat_id: int, actor: Actor, query: CallbackQuery | None, key: str | None,
                       day: date) -> None:
        chosen, sections = await stats.choose(actor, day)
        if key is not None and key in {s.key for s in sections}:
            chosen = key
            await stats.remember(actor, key)
        data = await stats.day(actor, chosen, day)
        if data is None:
            await screens.home(bot, chat_id, actor, NO_SECTIONS)
            return
        await send_photo(bot, chat_id, query, day_png(data), f"📊 {data.title}",
                         day_markup(actor, chosen, day, sections))

    def is_label(text: str | None) -> bool:
        entry = screens.menu.get(KEY)
        return entry is not None and text is not None and text.strip() == entry.label

    @nav.message(F.text.func(is_label))
    async def open_from_home(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await state.clear()  # переход в раздел закрывает незаконченный ввод
        await show_day(bot, message.chat.id, actor, None, None, stats.today())

    @nav.callback_query(MenuCb.filter(F.k == KEY))
    async def open_from_more(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await screens.close_buttons(query)
        await state.clear()
        await show_day(bot, query.from_user.id, actor, None, None, stats.today())

    @router.callback_query(StCb.filter(F.a == "sec"))
    async def section(query: CallbackQuery, callback_data: StCb, bot: Bot, actor: Actor) -> None:
        key, _, code = callback_data.v.partition(".")
        day = min(_parse_day(code, stats.today()), stats.today())
        await query.answer()
        await show_day(bot, query.from_user.id, actor, query, None if key == "last" else key, day)

    @router.callback_query(StCb.filter(F.a == "text"))
    async def as_text(query: CallbackQuery, callback_data: StCb, bot: Bot, actor: Actor) -> None:
        key, _, code = callback_data.v.partition(".")
        data = await stats.day(actor, key, min(_parse_day(code, stats.today()), stats.today()))
        if data is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        await query.answer()
        await bot.send_message(query.from_user.id, f"<pre>{html.escape(day_text(data))}</pre>", parse_mode="HTML")

    def period_of(value: str) -> tuple[Kind, int]:
        try:
            kind, shift = Kind(value[:1]), int(value[1:] or 0)
        except ValueError:
            return Kind.WEEK, 0
        return kind, min(shift, 0)

    @router.callback_query(StCb.filter(F.a == "per"))
    async def overview(query: CallbackQuery, callback_data: StCb, bot: Bot, actor: Actor) -> None:
        kind, shift = period_of(callback_data.v)
        data = await stats.overview(actor, kind, shift)
        await query.answer()
        await send_photo(bot, query.from_user.id, query, overview_png(data), f"📊 {data.title}",
                         period_markup(actor, kind, shift))

    @router.callback_query(StCb.filter(F.a == "ptext"))
    async def overview_as_text(query: CallbackQuery, callback_data: StCb, bot: Bot, actor: Actor) -> None:
        kind, shift = period_of(callback_data.v)
        data = await stats.overview(actor, kind, shift)
        await query.answer()
        await bot.send_message(query.from_user.id, f"<pre>{html.escape(overview_text(data))}</pre>",
                               parse_mode="HTML")

    return nav, router


__all__ = ["StCb", "build_stats_router"]
