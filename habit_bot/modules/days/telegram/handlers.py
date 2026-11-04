"""«📅 Другой день», «🛌 Выходной», «📅 На вчера» (раздел 3.7).

Выбор даты — ввод в области ``dialog``: «✕ Отмена» на экране выбора и в календаре — режим не включается.
Сам режим хранится в области ``other_day`` и сбрасывается через 15 минут бездействия вместе с незаконченным вводом.
"""

from __future__ import annotations

import time
from datetime import date

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from habit_bot.channels.telegram.dialogs.fsm import dialog_token, start_dialog
from habit_bot.channels.telegram.dialogs.policy import OTHER_DAY
from habit_bot.channels.telegram.ui.callbacks import CancelCb, MenuCb
from habit_bot.channels.telegram.ui.menu import is_return_label
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.domain.days import (
    days_ago,
    days_word,
    month_title,
    month_weeks,
    needs_confirmation,
    quick_days,
    shift_month,
)
from habit_bot.kernel.domain.formatting import format_day
from habit_bot.kernel.domain.parsing import ensure_not_future, parse_date
from habit_bot.kernel.identity import Actor
from habit_bot.modules.days.telegram.card import render_card
from habit_bot.modules.days.usecases import Days

PICK_TITLE = "За какой день записать? Можно и написать дату: 20.10 или 20.10.2026."
ALREADY_TODAY = "Это сегодняшний день — записи и так попадают в него."
UNSAVED = "Ввод не сохранён. Выйти без сохранения?"
NOT_IN_MODE = "Вы и так в сегодняшнем дне."
MOVE_TTL_MINUTES = 24 * 60  # кнопки под сохранённой записью работают 24 часа


class DayCb(CallbackData, prefix="d"):
    o: int
    t: int
    a: str
    v: str | None = None


class MoveCb(CallbackData, prefix="mv"):
    """«📅 На вчера» под карточкой записи: вид записи, её public_id, минута создания кнопки."""

    o: int
    t: int
    k: str
    i: str
    m: int


class OtherDay(StatesGroup):
    pick = State()
    confirm = State()


def iso(day: date) -> str:
    return day.strftime("%Y%m%d")


def from_iso(text: str | None) -> date | None:
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8])) if text and len(text) == 8 else None
    except ValueError:
        return None


def entered(day: date) -> str:
    return f"Записываю за {format_day(day)}. Всё, что добавите, попадёт в этот день."


def back_to_today(today: date) -> str:
    return f"Вернулись к сегодняшнему дню ({format_day(today)})."


def move_button(actor: Actor, kind: str, public_id: str, now_minute: int | None = None) -> InlineKeyboardButton:
    """Кнопка для карточек записей частей 5–8."""
    minute = now_minute if now_minute is not None else int(time.time() // 60)
    data = MoveCb(o=actor.user_id, t=0, k=kind, i=public_id, m=minute).pack()
    return InlineKeyboardButton(text="📅 На вчера", callback_data=data)


def build_days_router(days: Days, screens: Screens) -> Router:
    router = Router(name="days")

    def btn(actor: Actor, token: int, text: str, action: str, value: str | None = None) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=DayCb(o=actor.user_id, t=token, a=action, v=value).pack())

    def cancel(actor: Actor, token: int) -> InlineKeyboardButton:
        return InlineKeyboardButton(text="✕ Отмена", callback_data=CancelCb(o=actor.user_id, t=token).pack())

    def pick_keyboard(actor: Actor, token: int, today: date) -> InlineKeyboardMarkup:
        buttons = [btn(actor, token, label, "day", iso(day)) for label, day in quick_days(today)]
        rows = [buttons[i: i + 2] for i in range(0, len(buttons), 2)]
        rows.append([btn(actor, token, "🗓 Выбрать дату", "cal", f"{today.year:04d}{today.month:02d}"),
                     cancel(actor, token)])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def calendar_keyboard(actor: Actor, token: int, year: int, month: int, today: date) -> InlineKeyboardMarkup:
        prev_y, prev_m = shift_month(year, month, -1)
        next_y, next_m = shift_month(year, month, 1)
        rows = [[btn(actor, token, "◀", "cal", f"{prev_y:04d}{prev_m:02d}"),
                 btn(actor, token, month_title(year, month), "noop"),
                 btn(actor, token, "▶", "cal", f"{next_y:04d}{next_m:02d}")]]
        rows.append([btn(actor, token, w, "noop") for w in ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")])
        for week in month_weeks(year, month):
            row = []
            for day in week:
                if day is None:
                    row.append(btn(actor, token, "⠀", "noop"))  # пустая клетка: у кнопки должен быть текст
                elif day > today:
                    row.append(btn(actor, token, "·", "noop"))  # будущие даты недоступны
                else:
                    row.append(btn(actor, token, str(day.day), "day", iso(day)))
            rows.append(row)
        rows.append([cancel(actor, token)])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def show_card(bot: Bot, chat_id: int, actor: Actor, day: date, text: str) -> None:
        card = render_card(await days.card(actor, day))
        await screens.home(bot, chat_id, actor, f"{text}\n{card}", parse_mode="HTML")

    async def choose(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, day: date, today: date) -> None:
        ensure_not_future(day, today)
        if day == today:
            await state.clear()
            await screens.dialogs.clear(actor.user_id, OTHER_DAY)
            await screens.home(bot, chat_id, actor, ALREADY_TODAY)
            return
        if needs_confirmation(day, today):
            await state.set_state(OtherDay.confirm)
            await state.update_data(day=day.isoformat())
            token = await dialog_token(state)
            await bot.send_message(
                chat_id, f"Это {days_word(days_ago(day, today))} назад ({format_day(day)}), всё верно?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn(actor, token, "Да", "yes"),
                                                                     cancel(actor, token)]]),
            )
            return
        await activate(bot, chat_id, actor, state, day)

    async def activate(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, day: date) -> None:
        await state.clear()
        await screens.dialogs.set_day(actor.user_id, OTHER_DAY, day, days.now())
        await show_card(bot, chat_id, actor, day, entered(day))

    # --- «Вернуться к сегодня»: подключается первым, работает даже в середине ввода ---
    @router.message(F.text.func(is_return_label))
    async def return_today(message: Message, bot: Bot, actor: Actor, state: FSMContext, today: date) -> None:
        if await screens.dialogs.day(actor.user_id, OTHER_DAY) is None:
            await screens.home(bot, message.chat.id, actor, NOT_IN_MODE)
            return
        if await state.get_state() is not None:
            markup = InlineKeyboardMarkup(inline_keyboard=[[btn(actor, 0, "Да", "exit"),
                                                             btn(actor, 0, "Продолжить ввод", "stay")]])
            await message.answer(UNSAVED, reply_markup=markup)
            return
        await screens.dialogs.clear(actor.user_id, OTHER_DAY)
        await screens.home(bot, message.chat.id, actor, back_to_today(today))

    @router.callback_query(DayCb.filter(F.a.in_({"exit", "stay"})))
    async def exit_answer(query: CallbackQuery, callback_data: DayCb, bot: Bot, actor: Actor, state: FSMContext,
                          today: date) -> None:
        await screens.close_buttons(query)
        if callback_data.a == "stay":
            return
        await state.clear()  # незавершённая запись не создана; сохранённые остаются
        await screens.dialogs.clear(actor.user_id, OTHER_DAY)
        await screens.home(bot, query.from_user.id, actor, back_to_today(today))

    # --- выбор дня ---
    @router.callback_query(MenuCb.filter(F.k == "other_day"))
    async def open_picker(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext, today: date) -> None:
        await screens.close_buttons(query)
        token = await start_dialog(state, OtherDay.pick)
        await bot.send_message(query.from_user.id, PICK_TITLE, reply_markup=pick_keyboard(actor, token, today))

    @router.callback_query(StateFilter(OtherDay.pick), DayCb.filter(F.a == "cal"))
    async def calendar(query: CallbackQuery, callback_data: DayCb, actor: Actor, state: FSMContext,
                       today: date) -> None:
        await query.answer()
        value = callback_data.v or ""
        year, month = (int(value[:4]), int(value[4:6])) if len(value) == 6 and value.isdigit() else (
            today.year, today.month)
        month = min(max(month, 1), 12)
        if isinstance(query.message, Message):
            token = await dialog_token(state)
            await query.message.edit_text(PICK_TITLE,
                                          reply_markup=calendar_keyboard(actor, token, year, month, today))

    @router.callback_query(StateFilter(OtherDay.pick), DayCb.filter(F.a == "noop"))
    async def noop(query: CallbackQuery) -> None:
        await query.answer()

    @router.callback_query(StateFilter(OtherDay.pick), DayCb.filter(F.a == "day"))
    async def picked(query: CallbackQuery, callback_data: DayCb, bot: Bot, actor: Actor, state: FSMContext,
                     today: date) -> None:
        day = from_iso(callback_data.v)
        await screens.close_buttons(query)
        if day is not None:
            await choose(bot, query.from_user.id, actor, state, day, today)

    @router.message(StateFilter(OtherDay.pick), F.text)
    async def typed(message: Message, bot: Bot, actor: Actor, state: FSMContext, today: date) -> None:
        await choose(bot, message.chat.id, actor, state, parse_date(message.text or "", today), today)

    @router.callback_query(StateFilter(OtherDay.confirm), DayCb.filter(F.a == "yes"))
    async def confirmed(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await screens.close_buttons(query)
        day = date.fromisoformat((await state.get_data())["day"])
        await activate(bot, query.from_user.id, actor, state, day)

    # --- выходной ---
    @router.callback_query(MenuCb.filter(F.k == "day_off"))
    async def day_off(query: CallbackQuery, bot: Bot, actor: Actor, record_day: date) -> None:
        await screens.close_buttons(query)
        is_off = await days.toggle_day_off(actor, record_day)
        text = (f"🛌 {format_day(record_day)} — выходной: цели не проверяются, серии не прерываются."
                if is_off else f"Отметка «Выходной» за {format_day(record_day)} снята.")
        await show_card(bot, query.from_user.id, actor, record_day, text)

    # --- перенос записи «📅 На вчера» ---
    @router.callback_query(MoveCb.filter())
    async def move(query: CallbackQuery, callback_data: MoveCb, bot: Bot, actor: Actor) -> None:
        if int(days.now().timestamp() // 60) - callback_data.m > MOVE_TTL_MINUTES:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        result = await days.move(actor, callback_data.k, callback_data.i)
        if result is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        await screens.close_buttons(query, toast=f"Перенесено на {format_day(result.new_day)}")
        for day in (result.new_day, result.old_day):
            await show_card(bot, query.from_user.id, actor, day, f"Итоги {format_day(day)}:")

    return router

