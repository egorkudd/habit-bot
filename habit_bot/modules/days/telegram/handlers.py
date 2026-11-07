"""«📅 Другой день», «🛌 Выходной», «📅 На вчера» (раздел 3.7).

Выбор даты — ввод в области ``dialog``: «✕ Отмена» на экране выбора и в календаре — режим не включается.
Сам режим хранится в области ``other_day`` и сбрасывается через 15 минут бездействия вместе с незаконченным вводом.
"""

from __future__ import annotations

from datetime import date, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from habit_bot.channels.telegram.dialogs.fsm import dialog_token, start_dialog
from habit_bot.channels.telegram.dialogs.policy import OTHER_DAY
from habit_bot.channels.telegram.ui import trail
from habit_bot.channels.telegram.ui.callbacks import MOVE_TTL_MINUTES, CancelCb, MenuCb, MoveCb
from habit_bot.channels.telegram.ui.layout import inline
from habit_bot.channels.telegram.ui.menu import is_return_label
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.domain.days import (
    MONTHS,
    WEEKDAYS,
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


class DayCb(CallbackData, prefix="d"):
    o: int
    t: int
    a: str
    v: str | None = None


class RecCb(CallbackData, prefix="rc"):
    """«📋 Записи»: ``a`` — list / open / del, ``k`` — раздел, ``v`` — запись, ``d`` — день ГГММДД."""

    o: int
    t: int
    a: str
    d: str
    k: str = "-"
    v: str = "-"


RECORDS_KEY = "records"
RECORDS_EMPTY = "Записей нет."
RECORDS_HINT = "Нажмите запись, чтобы удалить её."


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
        return inline(rows)

    def calendar_keyboard(actor: Actor, token: int, year: int, month: int, today: date) -> InlineKeyboardMarkup:
        prev_y, prev_m = shift_month(year, month, -1)
        next_y, next_m = shift_month(year, month, 1)
        # Название месяца — в тексте сообщения: в ряду из трёх кнопок «Октябрь 2026» обрезается.
        rows = [[btn(actor, token, f"◀ {MONTHS[prev_m - 1]}", "cal", f"{prev_y:04d}{prev_m:02d}"),
                 btn(actor, token, f"{MONTHS[next_m - 1]} ▶", "cal", f"{next_y:04d}{next_m:02d}")]]
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
        return inline(rows)

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
                reply_markup=inline([[btn(actor, token, "Да", "yes"), cancel(actor, token)]]),
            )
            return
        await activate(bot, chat_id, actor, state, day)

    async def activate(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, day: date) -> None:
        await state.clear()
        await screens.dialogs.set_day(actor.user_id, OTHER_DAY, day, days.now())
        trail.result()  # выбор дня (календарь, подтверждение) убирается, карточка дня остаётся
        await show_card(bot, chat_id, actor, day, entered(day))

    # --- «Вернуться к сегодня»: подключается первым, работает даже в середине ввода ---
    @router.message(F.text.func(is_return_label))
    async def return_today(message: Message, bot: Bot, actor: Actor, state: FSMContext, today: date) -> None:
        if await screens.dialogs.day(actor.user_id, OTHER_DAY) is None:
            await screens.home(bot, message.chat.id, actor, NOT_IN_MODE)
            return
        if await state.get_state() is not None:
            markup = inline([[btn(actor, 0, "Да", "exit"), btn(actor, 0, "Продолжить ввод", "stay")]])
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
            await query.message.edit_text(f"🗓 {month_title(year, month)}\n{PICK_TITLE}",
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
        trail.result()
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
        if query.message is not None:
            trail.discard(query.message.message_id)  # карточка с прежней датой вводит в заблуждение
        trail.result()
        for day in (result.new_day, result.old_day):
            await show_card(bot, query.from_user.id, actor, day, f"Итоги {format_day(day)}:")

    # --- «📋 Записи»: все записи дня, удаление — в том числе за прошлые дни (правки 1.0.2) ---
    def rbtn(actor: Actor, text: str, action: str, day: date, kind: str = "-",
             value: str = "-") -> InlineKeyboardButton:
        data = RecCb(o=actor.user_id, t=0, a=action, d=f"{day:%y%m%d}", k=kind, v=value)
        return InlineKeyboardButton(text=text, callback_data=data.pack())

    async def records(actor: Actor, day: date) -> tuple[str, InlineKeyboardMarkup]:
        found = await days.entries(actor, day)
        today = days.today()
        title = f"{format_day(day)} ({WEEKDAYS[day.weekday()]})"
        text = f"📋 Записи · {title}\n" + (RECORDS_HINT if found else RECORDS_EMPTY)
        rows = [[rbtn(actor, e.label[:60], "open", day, e.kind, e.public_id)] for e in found]
        move = [rbtn(actor, f"◀ {format_day(day - timedelta(days=1))}", "list", day - timedelta(days=1))]
        if day < today:
            move.append(rbtn(actor, f"{format_day(day + timedelta(days=1))} ▶", "list", day + timedelta(days=1)))
        rows.append(move)
        return text, inline(rows)

    def day_of(callback_data: RecCb) -> date | None:
        try:
            return date(2000 + int(callback_data.d[:2]), int(callback_data.d[2:4]), int(callback_data.d[4:6]))
        except ValueError:
            return None

    @router.callback_query(MenuCb.filter(F.k == RECORDS_KEY))
    async def open_records(query: CallbackQuery, bot: Bot, actor: Actor, record_day: date) -> None:
        await screens.close_buttons(query)
        text, markup = await records(actor, record_day)
        await bot.send_message(query.from_user.id, text, reply_markup=markup)

    @router.callback_query(RecCb.filter())
    async def record_action(query: CallbackQuery, callback_data: RecCb, bot: Bot, actor: Actor) -> None:
        day = day_of(callback_data)  # чужую кнопку отклоняет CallbackGuardMiddleware (ACCESS-FOREIGN)
        if day is None or day > days.today():
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        if not isinstance(query.message, Message):
            await query.answer()
            return
        toast = None
        if callback_data.a == "open":
            entry = next((e for e in await days.entries(actor, day)
                          if e.kind == callback_data.k and e.public_id == callback_data.v), None)
            if entry is not None:
                await query.answer()
                await query.message.edit_text(
                    f"{entry.detail}\n\n{format_day(day)}", reply_markup=inline([[
                        rbtn(actor, "🗑 Удалить", "del", day, entry.kind, entry.public_id),
                        rbtn(actor, "◀ Назад", "list", day)]]))
                return
            toast = "Этой записи уже нет"
        elif callback_data.a == "del":
            removed = await days.remove_entry(actor, callback_data.k, callback_data.v)
            toast = "🗑 Удалено" if removed else "Этой записи уже нет"
        await query.answer(toast)
        text, markup = await records(actor, day)
        await query.message.edit_text(text, reply_markup=markup)

    return router

