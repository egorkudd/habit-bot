"""«✅ Привычки» в Telegram (раздел 3.6): кнопка привычки на главном экране — 1 нажатие, список «Привычки»
с обновлением того же сообщения, «Отметить несколько», ответ «👁 Зарядка для глаз — 2/3» с «Отменить», «+ ещё»,
«Другое значение», «📅 На вчера»; настройки: шаблоны и свои, цель, шаг, быстрые значения, дни, главный экран,
порядок, архив, удаление. Логика — в ``Habits``; здесь только кнопки и тексты."""

from __future__ import annotations

import html
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Filter, StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from habit_bot.channels.telegram.dialogs.fsm import dialog_token, start_dialog
from habit_bot.channels.telegram.ui import trail
from habit_bot.channels.telegram.ui.callbacks import CancelCb, MenuCb, move_button
from habit_bot.channels.telegram.ui.layout import fit_rows, inline
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.domain.formatting import format_day
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.identity import Actor
from habit_bot.modules.days.public import Days
from habit_bot.modules.habits.domain.habits import (
    MEASURE_LABELS,
    PERIOD_GOAL,
    TEMPLATES,
    WEEKDAYS,
    Measure,
    Period,
    format_value,
    is_done,
    parse_quick,
    parse_value,
    progress_label,
    schedule_label,
    streak_word,
    unit_of,
)
from habit_bot.modules.habits.usecases import DayHabit, Habits, HabitView, MarkResult

KIND = "habits"
SETTINGS_KEY = "habit_settings"
HOME_PREFIX = "h"
LIST_HINT = "Нажмите привычку — отмечу. Еда и зарядка открывают свой раздел."
MANY_HINT = "Отметьте сделанное и нажмите «Записать». Ничего не запишется, пока не нажмёте."
HOME_FULL = "Главный экран полон (до 7 кнопок и «Ещё») — уберите что-нибудь в «Настройки» → «🏠 Главный экран»."
DEFAULT_EMOJI = "⭐"
DayCard = Callable[[Actor, date], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class Builtin:
    """Встроенная привычка в списке: «🍽 Еда 2 340/2 800», «🤸 Зарядка 1/2»; нажатие открывает раздел ``key``."""

    key: str
    label: str
    progress: Callable[[Actor, date], Awaitable[tuple[Decimal, Decimal | None]]]


class HCb(CallbackData, prefix="hb"):
    o: int
    t: int
    a: str
    v: str | None = None


class HabitEntryCb(CallbackData, prefix="he"):
    """Кнопки под ответом об отметке: 24 часа (``m`` — минута создания)."""

    o: int
    t: int
    a: str
    i: str
    m: int


class HabitInput(StatesGroup):
    value = State()     # своё число для отметки
    correct = State()   # «Другое значение» под ответом
    many = State()      # «Отметить несколько»
    name = State()      # новая своя: название
    measure = State()   # новая своя: тип
    unit = State()      # новая своя: единица
    goal = State()      # новая своя: цель
    home = State()      # новая: на главный экран?
    edit = State()      # правка поля привычки
    days = State()      # дни недели
    period = State()    # цель за неделю / месяц: сколько


def home_key(habit: HabitView) -> str:
    return f"{HOME_PREFIX}{habit.public_id}"


def amount_text(habit: HabitView, fact: Decimal) -> str:
    """«2/3», «6/8 стак.», «20/20 мин»; цель за неделю или месяц — «1/2 нед.»."""
    unit = unit_of(habit.measure, habit.unit)
    return f"{progress_label(fact, habit.goal)} {unit}".rstrip() + habit.per


def split_emoji(text: str) -> tuple[str, str]:
    """«🧘 Медитация» → («🧘», «Медитация»); без эмодзи — («⭐», текст)."""
    from habit_bot.channels.telegram.ui.layout import label_width

    clean = " ".join(text.split())
    head, _, rest = clean.partition(" ")
    if rest and not head.isalnum() and label_width(head) >= 2:
        return head[:8], rest
    return DEFAULT_EMOJI, clean


def habit_line(h: HabitView) -> str:
    goal = (f"цель {format_value(h.goal, h.measure, h.unit)} {PERIOD_GOAL[h.period]}" if h.goal is not None
            else "без цели")
    step = "число при нажатии" if h.step is None else f"шаг {format_value(h.step, h.measure, h.unit)}"
    schedule = schedule_label(h.weekdays, h.period)
    return f"{h.emoji} {h.name} — {MEASURE_LABELS[h.measure].lower()}, {goal}, {step}, {schedule}"


class OwnHabitLabel(Filter):
    """Текст — подпись кнопки своей привычки этого пользователя («👁 Глаза»)."""

    def __init__(self, habits: Habits) -> None:
        self._habits = habits

    async def __call__(self, message: Message, actor: Actor | None = None,
                       raw_state: str | None = None) -> bool | dict[str, Any]:
        if actor is None or not message.text or len(message.text) > 40:
            return False
        if raw_state and raw_state.startswith("HabitInput:"):
            return False  # посреди ввода привычки текст — это ответ («🧘 Медитация» как название), а не нажатие
        habit = await self._habits.by_label(actor, message.text)
        return {"habit": habit} if habit is not None else False


def build_habits_router(
    habits: Habits, days: Days, screens: Screens, day_card: Callable[[], DayCard | None],
    builtins: Callable[[], Sequence[Builtin]],
) -> tuple[Router, Router]:
    router = Router(name="habits")
    nav = Router(name="habits.nav")

    def hbtn(actor: Actor, token: int, text: str, action: str, value: str | None = None) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=HCb(o=actor.user_id, t=token, a=action, v=value).pack())

    def ebtn(actor: Actor, text: str, action: str, entry_id: str) -> InlineKeyboardButton:
        data = HabitEntryCb(o=actor.user_id, t=0, a=action, i=entry_id, m=minute()).pack()
        return InlineKeyboardButton(text=text, callback_data=data)

    def cancel(actor: Actor, token: int) -> InlineKeyboardButton:
        return InlineKeyboardButton(text="✕ Отмена", callback_data=CancelCb(o=actor.user_id, t=token).pack())

    def minute() -> int:
        return int(days.now().timestamp() // 60)

    async def card(actor: Actor, day: date) -> str:
        render = day_card()
        return await render(actor, day) if render else ""

    async def send_card(bot: Bot, chat_id: int, actor: Actor, text: str, day: date,
                        markup: InlineKeyboardMarkup | None = None) -> None:
        await bot.send_message(chat_id, f"{html.escape(text)}\n{await card(actor, day)}", parse_mode="HTML",
                               reply_markup=markup)

    def result_text(result: MarkResult) -> str:
        h = result.habit
        if result.just_done:
            return f"✅ {h.short} {amount_text(h, result.fact)} · серия {streak_word(result.streak, h.period)}"
        return f"{h.emoji} {h.name} — {amount_text(h, result.fact)}"

    async def show_result(bot: Bot, chat_id: int, actor: Actor, result: MarkResult) -> None:
        """Ответ на отметку — итог: промежуточные сообщения уходят, этот остаётся."""
        buttons = [ebtn(actor, "Отменить", "undo", result.entry_id), ebtn(actor, "+ ещё", "more", result.entry_id),
                   ebtn(actor, "Другое значение", "other", result.entry_id),
                   move_button(actor.user_id, KIND, result.entry_id, minute())]
        trail.result()
        await send_card(bot, chat_id, actor, result_text(result), result.day, inline(fit_rows(buttons)))

    async def ask_value(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, habit: HabitView, day: date,
                        target: State = HabitInput.value, entry_id: str | None = None) -> None:
        token = await start_dialog(state, target, day)
        await state.update_data(habit=habit.public_id, entry=entry_id)
        unit = unit_of(habit.measure, habit.unit)
        quick = [hbtn(actor, token, format_value(v, habit.measure, habit.unit), "q", str(v))
                 for v in habit.quick_values]
        hint = f" ({unit})" if unit else ""
        rows = [*fit_rows(quick, 4), [cancel(actor, token)]]
        await bot.send_message(chat_id, f"{habit.emoji} {habit.name}: сколько? Числом{hint}, можно дробное: 1,5.",
                               reply_markup=inline(rows))

    async def mark(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, habit: HabitView, day: date,
                   source: str, request_id: str | None) -> None:
        if habit.step is None:
            await ask_value(bot, chat_id, actor, state, habit, day)
            return
        result = await habits.mark(actor, habit.public_id, day=day, source=source, request_id=request_id)
        await show_result(bot, chat_id, actor, result)

    # --- кнопка привычки на главном экране: 1 нажатие ---
    @nav.message(F.text, OwnHabitLabel(habits))
    async def home_tap(message: Message, bot: Bot, actor: Actor, state: FSMContext, record_day: date,
                       habit: HabitView, request_id: str | None) -> None:
        await state.clear()  # переход к привычке закрывает незаконченный ввод
        await mark(bot, message.chat.id, actor, state, habit, record_day, "button", request_id)

    # --- своё число ---
    async def save_value(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, record_day: date, value: Decimal,
                         request_id: str | None) -> None:
        data = await state.get_data()
        habit = await habits.habit(actor, data.get("habit", ""))
        if habit is None or habit.archived:
            raise AppError("UI-STALE")
        await state.clear()
        if data.get("entry"):
            undone = await habits.undo(actor, data["entry"])  # «Другое значение» заменяет только что записанное
            if undone is None:
                raise AppError("UI-STALE")
        result = await habits.mark(actor, habit.public_id, day=record_day, value=value, source="button",
                                   request_id=request_id)
        await show_result(bot, chat_id, actor, result)

    async def value_of(state: FSMContext, actor: Actor, text: str) -> Decimal:
        habit = await habits.habit(actor, (await state.get_data()).get("habit", ""))
        measure = habit.measure if habit else Measure.AMOUNT
        return parse_value(measure, text, habit.name if habit else "Значение")

    @router.message(StateFilter(HabitInput.value, HabitInput.correct), F.text)
    async def typed_value(message: Message, bot: Bot, actor: Actor, state: FSMContext, record_day: date,
                          request_id: str | None) -> None:
        value = await value_of(state, actor, message.text or "")
        await save_value(bot, message.chat.id, actor, state, record_day, value, request_id)

    @router.callback_query(StateFilter(HabitInput.value, HabitInput.correct), HCb.filter(F.a == "q"))
    async def quick_value(query: CallbackQuery, callback_data: HCb, bot: Bot, actor: Actor, state: FSMContext,
                          record_day: date, request_id: str | None) -> None:
        await screens.close_buttons(query)
        await save_value(bot, query.from_user.id, actor, state, record_day, Decimal(callback_data.v or "1"),
                         request_id)

    # --- кнопки под ответом ---
    @router.callback_query(HabitEntryCb.filter())
    async def entry_action(query: CallbackQuery, callback_data: HabitEntryCb, bot: Bot, actor: Actor,
                           state: FSMContext, request_id: str | None) -> None:
        if minute() - callback_data.m > 24 * 60:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        current = await habits.entry_result(actor, callback_data.i)
        if current is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        chat_id = query.from_user.id
        await screens.close_buttons(query)
        if callback_data.a == "undo":
            if query.message is not None:
                trail.discard(query.message.message_id)
            left = await habits.undo(actor, callback_data.i)
            assert left is not None
            trail.result()
            await send_card(bot, chat_id, actor, f"Отметка отменена: {current.habit.emoji} {current.habit.name} — "
                                                 f"{amount_text(current.habit, left.fact)}", current.day)
        elif callback_data.a == "more":
            await mark(bot, chat_id, actor, state, current.habit, current.day, "button", request_id)
        else:  # «Другое значение»
            await ask_value(bot, chat_id, actor, state, current.habit, current.day, HabitInput.correct,
                            callback_data.i)

    # --- список «Привычки» ---
    async def list_markup(actor: Actor, day: date, *, expanded: bool = False) -> tuple[str, InlineKeyboardMarkup]:
        items = await habits.day(actor, day)
        rows: list[tuple[bool, InlineKeyboardButton]] = []
        hidden = await habits.archived_builtins(actor)
        for builtin in [b for b in builtins() if b.key not in hidden]:
            fact, goal = await builtin.progress(actor, day)
            done = is_done(fact, goal)
            label = f"{'✅ ' if done else ''}{builtin.label} {progress_label(fact, goal)}"
            rows.append((done, InlineKeyboardButton(
                text=label, callback_data=MenuCb(o=actor.user_id, t=0, k=builtin.key).pack())))
        resting: list[DayHabit] = []
        for item in items:
            if not item.scheduled and not expanded:
                resting.append(item)
                continue
            label = f"{'✅ ' if item.done else ''}{item.habit.label} {amount_text(item.habit, item.fact)}"
            rows.append((item.done, hbtn(actor, 0, label, "tap", f"{item.habit.public_id}_{int(expanded)}")))
        ordered = [b for done, b in rows if not done] + [b for done, b in rows if done]
        keyboard = fit_rows(ordered)
        if resting:
            names = ", ".join(i.habit.short for i in resting)
            keyboard.append([hbtn(actor, 0, f"💤 Не сегодня: {names}"[:60], "all")])
        keyboard.append([hbtn(actor, 0, "☑️ Отметить несколько", "many"), hbtn(actor, 0, "⚙️ Настроить", "settings")])
        title = f"✅ Привычки за {format_day(day)}"
        if not items:
            title += "\nСвоих привычек пока нет — «⚙️ Настроить» → «➕ Новая»."
        return f"{title}\n{LIST_HINT}", inline(keyboard)

    async def open_list(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, day: date) -> None:
        await state.clear()
        await habits.apply_starter(actor)
        text, markup = await list_markup(actor, day)
        await bot.send_message(chat_id, text, reply_markup=markup)

    def is_list_label(text: str | None) -> bool:
        entry = screens.menu.get(KIND)
        return entry is not None and text is not None and text.strip() == entry.label

    @nav.message(F.text.func(is_list_label))
    async def open_from_home(message: Message, bot: Bot, actor: Actor, state: FSMContext, record_day: date) -> None:
        await open_list(bot, message.chat.id, actor, state, record_day)

    @nav.callback_query(MenuCb.filter(F.k == KIND))
    async def open_from_more(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext,
                             record_day: date) -> None:
        await screens.close_buttons(query)
        await open_list(bot, query.from_user.id, actor, state, record_day)

    @router.callback_query(HCb.filter(F.a == "all"))
    async def expand(query: CallbackQuery, actor: Actor, record_day: date) -> None:
        await query.answer()
        if isinstance(query.message, Message):
            text, markup = await list_markup(actor, record_day, expanded=True)
            await query.message.edit_text(text, reply_markup=markup)

    @router.callback_query(HCb.filter(F.a == "tap"))
    async def list_tap(query: CallbackQuery, callback_data: HCb, bot: Bot, actor: Actor, state: FSMContext,
                       record_day: date, request_id: str | None) -> None:
        public_id, _, expanded = (callback_data.v or "").partition("_")
        habit = await habits.habit(actor, public_id)
        if habit is None or habit.archived:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        if habit.step is None:
            await query.answer()
            await ask_value(bot, query.from_user.id, actor, state, habit, record_day)
            return
        fact = next((i.fact for i in await habits.day(actor, record_day) if i.habit.public_id == public_id),
                    Decimal(0))
        if habit.once and fact >= 1:
            await query.answer()
            await bot.send_message(query.from_user.id, f"{habit.label} уже отмечено за {format_day(record_day)}.",
                                   reply_markup=inline([[hbtn(actor, 0, "Снять отметку", "unmark", public_id),
                                                         hbtn(actor, 0, "Оставить", "keep")]]))
            return
        result = await habits.mark(actor, public_id, day=record_day, source="list", request_id=request_id)
        await query.answer(result_text(result)[:200])
        if isinstance(query.message, Message):  # список обновляется в том же сообщении
            text, markup = await list_markup(actor, record_day, expanded=expanded == "1")
            await query.message.edit_text(text, reply_markup=markup)

    @router.callback_query(HCb.filter(F.a.in_({"unmark", "keep"})))
    async def unmark(query: CallbackQuery, callback_data: HCb, bot: Bot, actor: Actor, record_day: date) -> None:
        if callback_data.a == "keep":
            await screens.close_buttons(query)
            if query.message is not None:
                trail.discard(query.message.message_id)
            return
        habit = await habits.habit(actor, callback_data.v or "")
        await screens.close_buttons(query)
        if habit is None:
            return
        await habits.clear_day(actor, habit.public_id, record_day)
        trail.result()
        await send_card(bot, query.from_user.id, actor, f"Отметка снята: {habit.label} — "
                                                        f"{amount_text(habit, Decimal(0))}", record_day)

    # --- «Отметить несколько» ---
    async def many_markup(actor: Actor, state: FSMContext, record_day: date) -> InlineKeyboardMarkup:
        token = await dialog_token(state)
        chosen = set((await state.get_data()).get("chosen", []))
        buttons = []
        for item in await habits.day(actor, record_day):
            if item.habit.step is None:
                continue  # «Шаги», «Сон» — только числом
            mark_ = "☑️" if item.habit.public_id in chosen else "☐"
            buttons.append(hbtn(actor, token, f"{mark_} {item.habit.label}", "mt", item.habit.public_id))
        rows = fit_rows(buttons)
        rows.append([hbtn(actor, token, f"💾 Записать ({len(chosen)})", "msave"), cancel(actor, token)])
        return inline(rows)

    @router.callback_query(HCb.filter(F.a == "many"))
    async def many(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext, record_day: date) -> None:
        await query.answer()
        await start_dialog(state, HabitInput.many, record_day)
        await state.update_data(chosen=[])
        await bot.send_message(query.from_user.id, f"☑️ За {format_day(record_day)}. {MANY_HINT}",
                               reply_markup=await many_markup(actor, state, record_day))

    @router.callback_query(StateFilter(HabitInput.many), HCb.filter(F.a == "mt"))
    async def many_toggle(query: CallbackQuery, callback_data: HCb, actor: Actor, state: FSMContext,
                          record_day: date) -> None:
        chosen: list[str] = list((await state.get_data()).get("chosen", []))
        key = callback_data.v or ""
        chosen = [c for c in chosen if c != key] if key in chosen else [*chosen, key]
        await state.update_data(chosen=chosen)
        await query.answer()
        if isinstance(query.message, Message):
            await query.message.edit_reply_markup(reply_markup=await many_markup(actor, state, record_day))

    @router.callback_query(StateFilter(HabitInput.many), HCb.filter(F.a == "msave"))
    async def many_save(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext, record_day: date,
                        request_id: str | None) -> None:
        chosen: list[str] = list((await state.get_data()).get("chosen", []))
        if not chosen:
            await query.answer("Ничего не отмечено")
            return
        await screens.close_buttons(query)
        results = await habits.mark_many(actor, chosen, day=record_day, request_id=request_id)
        await state.clear()
        lines = [f"{'✅' if r.done else r.habit.emoji} {r.habit.short} {amount_text(r.habit, r.fact)}" for r in results]
        trail.result()
        await send_card(bot, query.from_user.id, actor, f"Записано за {format_day(record_day)}: " + " · ".join(lines),
                        record_day)

    # --- настройки (раздел 3.6, 3.11) ---
    async def settings_screen(bot: Bot, chat_id: int, actor: Actor) -> None:
        await habits.apply_starter(actor)
        items = await habits.habits(actor)
        hidden = await habits.archived_builtins(actor)
        archived = [*await habits.habits(actor, archived=True), *[b for b in builtins() if b.key in hidden]]
        shown = [b for b in builtins() if b.key not in hidden]
        layout = await screens.layout(actor) or []
        lines = ["⚙️ Свои привычки — нажмите, чтобы изменить:", ""]
        lines += [f"{n}. {habit_line(h)}{' · 🏠' if home_key(h) in layout else ''}" for n, h in enumerate(items, 1)]
        if not items:
            lines.append("Пока нет ни одной.")
        if shown:
            lines += ["", "Встроенные: " + ", ".join(b.label for b in shown) + " — их тоже можно убрать в архив."]
        rows = fit_rows([hbtn(actor, 0, h.label, "open", h.public_id) for h in items])
        rows += fit_rows([hbtn(actor, 0, b.label, "b_open", b.key) for b in shown])
        rows.append([hbtn(actor, 0, "➕ Новая", "new"), *([hbtn(actor, 0, f"🗄 Архив ({len(archived)})", "arch")]
                                                         if archived else [])])
        await bot.send_message(chat_id, "\n".join(lines), reply_markup=inline(rows))

    @router.callback_query(MenuCb.filter(F.k == SETTINGS_KEY))
    @router.callback_query(HCb.filter(F.a == "settings"))
    async def open_settings(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await screens.close_buttons(query)
        await state.clear()
        await settings_screen(bot, query.from_user.id, actor)

    async def habit_screen(bot: Bot, chat_id: int, actor: Actor, habit: HabitView) -> None:
        on_home = home_key(habit) in (await screens.layout(actor) or [])
        quick = ", ".join(format_value(v, habit.measure, habit.unit) for v in habit.quick_values) or "нет"
        text = (f"{habit_line(habit)}\nБыстрые значения: {quick}\n"
                f"На главном экране: {'да' if on_home else 'нет'}")
        pid = habit.public_id
        rows = [[hbtn(actor, 0, "🎯 Цель", "e_goal", pid), hbtn(actor, 0, "📅 Расписание", "e_days", pid)],
                [hbtn(actor, 0, "🏠 Убрать с главного" if on_home else "🏠 На главный", "e_home", pid)]]
        if habit.measure is not Measure.CHECK:
            rows.append([hbtn(actor, 0, "➕ Шаг", "e_step", pid), hbtn(actor, 0, "⚡ Быстрые", "e_quick", pid)])
        rows += [[hbtn(actor, 0, "✏️ Название", "e_name", pid), hbtn(actor, 0, "⬆ Выше", "up", pid)],
                 [hbtn(actor, 0, "🗄 В архив", "archive", pid), hbtn(actor, 0, "🗑 Удалить", "delask", pid)],
                 [hbtn(actor, 0, "← Привычки", "settings")]]
        await bot.send_message(chat_id, text, reply_markup=inline(rows))

    async def own(query: CallbackQuery, bot: Bot, actor: Actor, public_id: str | None) -> HabitView | None:
        habit = await habits.habit(actor, public_id or "")
        if habit is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return None
        return habit

    @router.callback_query(HCb.filter(F.a == "open"))
    async def open_habit(query: CallbackQuery, callback_data: HCb, bot: Bot, actor: Actor) -> None:
        habit = await own(query, bot, actor, callback_data.v)
        if habit is not None:
            await screens.close_buttons(query)
            await habit_screen(bot, query.from_user.id, actor, habit)

    @router.callback_query(HCb.filter(F.a.in_({"up", "e_home"})))
    async def quick_edit(query: CallbackQuery, callback_data: HCb, bot: Bot, actor: Actor) -> None:
        habit = await own(query, bot, actor, callback_data.v)
        if habit is None:
            return
        if callback_data.a == "up":
            await screens.close_buttons(query)
            await habits.move_up(actor, habit.public_id)
            await settings_screen(bot, query.from_user.id, actor)
            return
        on_home = home_key(habit) in (await screens.layout(actor) or [])
        if not await screens.set_on_home(actor, home_key(habit), not on_home):
            await query.answer(HOME_FULL[:200], show_alert=True)
            return
        await screens.close_buttons(query)
        trail.result()
        await screens.home(bot, query.from_user.id, actor,
                           f"{habit.label} {'убрана с главного экрана' if on_home else 'теперь на главном экране'} 👇")

    @router.callback_query(HCb.filter(F.a.in_({"archive", "restore"})))
    async def archive(query: CallbackQuery, callback_data: HCb, bot: Bot, actor: Actor) -> None:
        habit = await own(query, bot, actor, callback_data.v)
        if habit is None:
            return
        await screens.close_buttons(query)
        archived = callback_data.a == "archive"
        await habits.set_archived(actor, habit.public_id, archived)
        if archived:
            await screens.set_on_home(actor, home_key(habit), False)
        trail.result()
        await screens.home(bot, query.from_user.id, actor,
                           f"{habit.label} — в архиве, история сохранена." if archived
                           else f"{habit.label} снова в списке привычек.")

    def builtin_of(key: str | None) -> Builtin | None:
        return next((b for b in builtins() if b.key == key), None)

    @router.callback_query(HCb.filter(F.a == "b_open"))
    async def open_builtin(query: CallbackQuery, callback_data: HCb, bot: Bot, actor: Actor) -> None:
        builtin = builtin_of(callback_data.v)
        if builtin is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        await screens.close_buttons(query)
        text = (f"{builtin.label} — встроенная привычка: цель задаётся в своём разделе.\n"
                "В архиве она не показывается в «✅ Привычки» и в светофоре «📊 Итоги»; раздел и записи остаются.")
        await bot.send_message(query.from_user.id, text, reply_markup=inline([
            [hbtn(actor, 0, "🗄 В архив", "b_archive", builtin.key), hbtn(actor, 0, "← Привычки", "settings")]]))

    @router.callback_query(HCb.filter(F.a.in_({"b_archive", "b_restore"})))
    async def archive_builtin(query: CallbackQuery, callback_data: HCb, bot: Bot, actor: Actor) -> None:
        builtin = builtin_of(callback_data.v)
        if builtin is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        await screens.close_buttons(query)
        archived = callback_data.a == "b_archive"
        await habits.set_builtin_archived(actor, builtin.key, archived)
        trail.result()
        await screens.home(bot, query.from_user.id, actor,
                           f"{builtin.label} — в архиве: в «✅ Привычки» и светофоре её нет, записи остаются."
                           if archived else f"{builtin.label} снова в списке привычек.")

    @router.callback_query(HCb.filter(F.a == "arch"))
    async def archive_list(query: CallbackQuery, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        items = await habits.habits(actor, archived=True)
        hidden = await habits.archived_builtins(actor)
        rows = [[hbtn(actor, 0, f"↩ {b.label}", "b_restore", b.key)] for b in builtins() if b.key in hidden]
        rows += [[hbtn(actor, 0, f"↩ {h.label}", "restore", h.public_id), hbtn(actor, 0, "🗑", "delask", h.public_id)]
                 for h in items]
        rows.append([hbtn(actor, 0, "← Привычки", "settings")])
        await bot.send_message(query.from_user.id, "🗄 Архив привычек: «↩» вернуть, «🗑» удалить с историей.",
                               reply_markup=inline(rows))

    @router.callback_query(HCb.filter(F.a == "delask"))
    async def delete_ask(query: CallbackQuery, callback_data: HCb, bot: Bot, actor: Actor) -> None:
        habit = await own(query, bot, actor, callback_data.v)
        if habit is None:
            return
        await screens.close_buttons(query)
        await bot.send_message(query.from_user.id, f"Удалить «{habit.name}» вместе со всей историей? "
                                                   "Это нельзя отменить. История сохранится, если выбрать «В архив».",
                               reply_markup=inline([[hbtn(actor, 0, "🗑 Да, удалить", "del", habit.public_id),
                                                     hbtn(actor, 0, "Оставить", "settings")]]))

    @router.callback_query(HCb.filter(F.a == "del"))
    async def delete_habit(query: CallbackQuery, callback_data: HCb, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        removed = await habits.delete(actor, callback_data.v or "")
        if removed is None:
            await screens.home(bot, query.from_user.id, actor, "Привычка уже удалена.")
            return
        await screens.set_on_home(actor, home_key(removed), False)
        trail.result()
        await screens.home(bot, query.from_user.id, actor, f"«{removed.name}» удалена вместе с историей.")

    # --- правка полей ---
    PROMPTS = {
        "e_goal": "Цель на день числом, например 3 или 1,5. Без цели — кнопкой.",
        "e_step": "Шаг одного нажатия числом, например 1 или 0,5. «Без шага» — бот будет спрашивать число.",
        "e_quick": "До 4 быстрых значений через пробел, например: 0,5 1 1,5 2.",
        "e_name": "Новое название (можно с эмодзи в начале: «🧘 Медитация»).",
    }

    @router.callback_query(HCb.filter(F.a.in_(set(PROMPTS))))
    async def edit_ask(query: CallbackQuery, callback_data: HCb, bot: Bot, actor: Actor, state: FSMContext) -> None:
        habit = await own(query, bot, actor, callback_data.v)
        if habit is None:
            return
        await screens.close_buttons(query)
        token = await start_dialog(state, HabitInput.edit)
        await state.update_data(habit=habit.public_id, field=callback_data.a)
        clear = {"e_goal": "Без цели", "e_step": "Без шага", "e_quick": "Очистить"}.get(callback_data.a)
        row = [*([hbtn(actor, token, clear, "eclear")] if clear else []), cancel(actor, token)]
        await bot.send_message(query.from_user.id, f"{habit.label}: {PROMPTS[callback_data.a]}",
                               reply_markup=inline([row]))

    async def apply_edit(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, text: str | None) -> None:
        data = await state.get_data()
        habit = await habits.habit(actor, data.get("habit", ""))
        if habit is None:
            raise AppError("UI-STALE")
        field = data.get("field")
        if field == "e_name":
            emoji, name = split_emoji(text or "")
            changes: dict[str, Any] = {"name": name}
            if emoji != DEFAULT_EMOJI:
                changes["emoji"] = emoji
            updated = await habits.update(actor, habit.public_id, **changes)
        elif field == "e_goal":
            goal = None if text is None else parse_value(habit.measure, text, "Цель")
            updated = await habits.update(actor, habit.public_id, goal=goal)
        elif field == "e_step":
            step = None if text is None else parse_value(habit.measure, text, "Шаг")
            updated = await habits.update(actor, habit.public_id, step=step)
        else:
            updated = await habits.update(actor, habit.public_id,
                                          quick=[] if text is None else parse_quick(habit.measure, text))
        await state.clear()
        trail.result()
        await bot.send_message(chat_id, f"Сохранено ✅\n{habit_line(updated)}")

    @router.message(StateFilter(HabitInput.edit), F.text)
    async def edit_text(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await apply_edit(bot, message.chat.id, actor, state, message.text or "")

    @router.callback_query(StateFilter(HabitInput.edit), HCb.filter(F.a == "eclear"))
    async def edit_clear(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await screens.close_buttons(query)
        await apply_edit(bot, query.from_user.id, actor, state, None)

    # --- дни недели ---
    async def days_markup(actor: Actor, state: FSMContext) -> InlineKeyboardMarkup:
        token = await dialog_token(state)
        chosen = set((await state.get_data()).get("days", []))
        buttons = [hbtn(actor, token, f"✅ {name}" if i in chosen else name, "dt", str(i))
                   for i, name in enumerate(WEEKDAYS)]
        return inline([buttons[:4], buttons[4:],
                       [hbtn(actor, token, "Каждый день", "dall"), hbtn(actor, token, "💾 Сохранить", "dsave")],
                       [hbtn(actor, token, "🔁 N раз в неделю", "pweek"),
                        hbtn(actor, token, "🗓 N раз в месяц", "pmonth")],
                       [cancel(actor, token)]])

    @router.callback_query(HCb.filter(F.a == "e_days"))
    async def days_ask(query: CallbackQuery, callback_data: HCb, bot: Bot, actor: Actor, state: FSMContext) -> None:
        habit = await own(query, bot, actor, callback_data.v)
        if habit is None:
            return
        await screens.close_buttons(query)
        await start_dialog(state, HabitInput.days)
        await state.update_data(habit=habit.public_id, days=list(habit.weekdays or range(7)))
        now = (f"{progress_label(habit.goal or Decimal(1), None)} {PERIOD_GOAL[habit.period]}"
               if habit.period is not Period.DAY else schedule_label(habit.weekdays))
        await bot.send_message(query.from_user.id, f"{habit.label}: в какие дни? Сейчас — {now}.\n"
                                                   "Или цель на неделю / месяц — в любые дни.",
                               reply_markup=await days_markup(actor, state))

    @router.callback_query(StateFilter(HabitInput.days), HCb.filter(F.a.in_({"dt", "dall"})))
    async def days_toggle(query: CallbackQuery, callback_data: HCb, actor: Actor, state: FSMContext) -> None:
        chosen: list[int] = list((await state.get_data()).get("days", []))
        if callback_data.a == "dall":
            chosen = list(range(7))
        else:
            day = int(callback_data.v or "0")
            chosen = [d for d in chosen if d != day] if day in chosen else sorted([*chosen, day])
        await state.update_data(days=chosen)
        await query.answer()
        if isinstance(query.message, Message):
            await query.message.edit_reply_markup(reply_markup=await days_markup(actor, state))

    @router.callback_query(StateFilter(HabitInput.days), HCb.filter(F.a == "dsave"))
    async def days_save(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        data = await state.get_data()
        if not data.get("days"):
            await query.answer("Выберите хотя бы один день")
            return
        await screens.close_buttons(query)
        updated = await habits.update(actor, data.get("habit", ""), weekdays=data["days"])
        await state.clear()
        trail.result()
        await bot.send_message(query.from_user.id, f"Сохранено ✅\n{habit_line(updated)}")

    # --- цель за неделю или месяц (правки 1.0.2) ---
    @router.callback_query(StateFilter(HabitInput.days), HCb.filter(F.a.in_({"pweek", "pmonth"})))
    async def period_ask(query: CallbackQuery, callback_data: HCb, bot: Bot, actor: Actor, state: FSMContext) -> None:
        period = Period.WEEK if callback_data.a == "pweek" else Period.MONTH
        habit = await habits.habit(actor, (await state.get_data()).get("habit", ""))
        if habit is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        await screens.close_buttons(query)
        token = await start_dialog(state, HabitInput.period)
        await state.update_data(habit=habit.public_id, period=period.value)
        word = "неделю" if period is Period.WEEK else "месяц"
        if habit.measure is Measure.CHECK:
            counts = (1, 2, 3, 4, 5) if period is Period.WEEK else (1, 2, 4, 8, 12)
            rows = [[hbtn(actor, token, str(n), "pnum", str(n)) for n in counts], [cancel(actor, token)]]
            question = f"{habit.label}: сколько раз за {word}? Нажмите или напишите число."
        else:
            rows = [[cancel(actor, token)]]
            unit = unit_of(habit.measure, habit.unit)
            question = f"{habit.label}: сколько за {word}{f' ({unit})' if unit else ''}? Напишите число."
        await bot.send_message(query.from_user.id, question, reply_markup=inline(rows))

    async def period_save(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, text: str) -> None:
        data = await state.get_data()
        habit = await habits.habit(actor, data.get("habit", ""))
        if habit is None:
            await state.clear()
            await screens.home(bot, chat_id, actor, "Это меню устарело. Вот главное меню 👇")
            return
        goal = parse_value(habit.measure, text, "Цель")
        updated = await habits.update(actor, habit.public_id, period=data.get("period", "week"), goal=goal)
        await state.clear()
        trail.result()
        await bot.send_message(chat_id, f"Сохранено ✅\n{habit_line(updated)}")

    @router.callback_query(StateFilter(HabitInput.period), HCb.filter(F.a == "pnum"))
    async def period_number(query: CallbackQuery, callback_data: HCb, bot: Bot, actor: Actor,
                            state: FSMContext) -> None:
        await screens.close_buttons(query)
        await period_save(bot, query.from_user.id, actor, state, callback_data.v or "1")

    @router.message(StateFilter(HabitInput.period), F.text)
    async def period_text(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await period_save(bot, message.chat.id, actor, state, message.text or "")

    # --- новая привычка: шаблон или своя ---
    @router.callback_query(HCb.filter(F.a == "new"))
    async def new(query: CallbackQuery, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        taken = {h.template_key for h in [*await habits.habits(actor), *await habits.habits(actor, archived=True)]}
        buttons = [hbtn(actor, 0, f"{t.emoji} {t.name}", "tpl", t.key) for t in TEMPLATES if t.key not in taken]
        rows = [*fit_rows(buttons), [hbtn(actor, 0, "✍️ Своя", "own"), hbtn(actor, 0, "← Привычки", "settings")]]
        await bot.send_message(query.from_user.id, "Новая привычка: шаблон или своя?", reply_markup=inline(rows))

    async def ask_home(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, habit: HabitView) -> None:
        await start_dialog(state, HabitInput.home)
        await state.update_data(habit=habit.public_id)
        token = await dialog_token(state)
        await bot.send_message(chat_id, f"Добавлено: {habit_line(habit)}\nПоказывать «{habit.label}» на главном "
                                        "экране? Тогда отметка — одно нажатие.",
                               reply_markup=inline([[hbtn(actor, token, "🏠 Да", "hyes"),
                                                     hbtn(actor, token, "Нет", "hno")]]))

    @router.callback_query(HCb.filter(F.a == "tpl"))
    async def from_template(query: CallbackQuery, callback_data: HCb, bot: Bot, actor: Actor,
                            state: FSMContext) -> None:
        await screens.close_buttons(query)
        habit = await habits.from_template(actor, callback_data.v or "")
        await ask_home(bot, query.from_user.id, actor, state, habit)

    @router.callback_query(StateFilter(HabitInput.home), HCb.filter(F.a.in_({"hyes", "hno"})))
    async def home_answer(query: CallbackQuery, callback_data: HCb, bot: Bot, actor: Actor,
                          state: FSMContext) -> None:
        await screens.close_buttons(query)
        habit = await habits.habit(actor, (await state.get_data()).get("habit", ""))
        await state.clear()
        if habit is None:
            return
        text = f"Готово: {habit.label} в списке «✅ Привычки»."
        if callback_data.a == "hyes":
            text = (f"Готово: «{habit.label}» на главном экране 👇" if await screens.set_on_home(
                actor, home_key(habit), True) else f"{text}\n{HOME_FULL}")
        trail.result()
        await screens.home(bot, query.from_user.id, actor, text)

    @router.callback_query(HCb.filter(F.a == "own"))
    async def own_habit(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await screens.close_buttons(query)
        token = await start_dialog(state, HabitInput.name)
        await bot.send_message(query.from_user.id, "Название привычки — можно с эмодзи в начале: «🧘 Медитация».",
                               reply_markup=inline([[cancel(actor, token)]]))

    @router.message(StateFilter(HabitInput.name), F.text)
    async def own_name(message: Message, actor: Actor, state: FSMContext) -> None:
        emoji, name = split_emoji(message.text or "")
        if not 1 <= len(name) <= 64:
            raise AppError("INPUT-TEXT", field="Название", low=1, high=64, length=len(name))
        label = f"{emoji} {name[:20]}"
        if screens.menu.by_label(label) is not None or await habits.by_label(actor, label) is not None:
            raise AppError("INPUT-HABIT-DUPLICATE", name=name)
        await state.update_data(name=name, emoji=emoji)
        await state.set_state(HabitInput.measure)
        token = await dialog_token(state)
        buttons = [hbtn(actor, token, label_, "m", m.value) for m, label_ in MEASURE_LABELS.items()]
        await message.answer("Что записывать? Отметка — «сделал», количество — число в своей единице "
                             "(стаканы, часы), длительность — минуты.",
                             reply_markup=inline([*fit_rows(buttons, 3), [cancel(actor, token)]]))

    async def ask_goal(bot: Bot, chat_id: int, actor: Actor, state: FSMContext) -> None:
        await state.set_state(HabitInput.goal)
        token = await dialog_token(state)
        data = await state.get_data()
        measure = Measure(data["measure"])
        example = {Measure.CHECK: "3 (раза в день)", Measure.AMOUNT: f"8 ({data.get('unit') or 'единиц'})",
                   Measure.DURATION: "20 (минут)"}[measure]
        await bot.send_message(chat_id, f"Цель на день числом, например {example}. Или без цели.",
                               reply_markup=inline([[hbtn(actor, token, "Без цели", "nogoal"), cancel(actor, token)]]))

    @router.callback_query(StateFilter(HabitInput.measure), HCb.filter(F.a == "m"))
    async def own_measure(query: CallbackQuery, callback_data: HCb, bot: Bot, actor: Actor,
                          state: FSMContext) -> None:
        await screens.close_buttons(query)
        measure = Measure(callback_data.v or Measure.CHECK.value)
        await state.update_data(measure=measure.value)
        if measure is Measure.AMOUNT:
            await state.set_state(HabitInput.unit)
            token = await dialog_token(state)
            await bot.send_message(query.from_user.id, "В чём считать? Например: стаканы, страницы, км.",
                                   reply_markup=inline([[cancel(actor, token)]]))
            return
        await ask_goal(bot, query.from_user.id, actor, state)

    @router.message(StateFilter(HabitInput.unit), F.text)
    async def own_unit(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        unit = " ".join((message.text or "").split())
        if not 1 <= len(unit) <= 16:
            raise AppError("INPUT-TEXT", field="Единица", low=1, high=16, length=len(unit))
        await state.update_data(unit=unit)
        await ask_goal(bot, message.chat.id, actor, state)

    async def own_create(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, goal: Decimal | None) -> None:
        data = await state.get_data()
        measure = Measure(data["measure"])
        habit = await habits.create(actor, name=data["name"], emoji=data["emoji"], measure=measure,
                                    unit=data.get("unit", ""), goal=goal, step=Decimal(1) if measure is not
                                    Measure.DURATION else Decimal(10))
        await ask_home(bot, chat_id, actor, state, habit)

    @router.message(StateFilter(HabitInput.goal), F.text)
    async def own_goal(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        measure = Measure((await state.get_data())["measure"])
        await own_create(bot, message.chat.id, actor, state, parse_value(measure, message.text or "", "Цель"))

    @router.callback_query(StateFilter(HabitInput.goal), HCb.filter(F.a == "nogoal"))
    async def own_no_goal(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await screens.close_buttons(query)
        await own_create(bot, query.from_user.id, actor, state, None)

    return nav, router


__all__ = ["Builtin", "build_habits_router", "home_key"]
