"""«🤸 Зарядка» в Telegram (раздел 3.3): черновик со значениями прошлой зарядки, «Как в прошлый раз», «+шаг»,
«Изменить» с «−» / «+» и точным числом, «Записать»; настройки набора, шагов, целей."""

from __future__ import annotations

import html
import re
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from habit_bot.channels.telegram.dialogs.fsm import dialog_token, start_dialog
from habit_bot.channels.telegram.ui.callbacks import CancelCb, MenuCb, move_button
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.domain.formatting import format_day
from habit_bot.kernel.domain.parsing import parse_date
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.identity import Actor
from habit_bot.modules.days.public import Days
from habit_bot.modules.warmup.domain.warmup import (
    Measure,
    apply_step,
    format_step,
    format_value,
    ordinal,
    parse_step,
    parse_value,
)
from habit_bot.modules.warmup.usecases import ExerciseView, SessionView, Warmup

KIND = "warmup"
EMPTY_SET = "Набор зарядки пуст. Возьмите набор по умолчанию или добавьте свои упражнения."
FIRST_TIME = "Первая зарядка — введите результаты: «−» / «+» или нажмите упражнение, чтобы ввести число."
SETTINGS_TITLE = "🤸 Настройки зарядки"
GOAL_PROMPT = "Цель и дата одной строкой, например: {example} 03.12.2026"
DayCard = Callable[[Actor, date], Awaitable[str]]


class WCb(CallbackData, prefix="w"):
    o: int
    t: int
    a: str
    v: str | None = None


class WarmupEntryCb(CallbackData, prefix="we"):
    """«Отменить» под карточкой записанной зарядки: 24 часа."""

    o: int
    t: int
    i: str
    m: int


class WarmupInput(StatesGroup):
    draft = State()
    value = State()
    step = State()
    new_name = State()
    new_measure = State()
    goal_value = State()


def build_warmup_router(
    warmup: Warmup, days: Days, screens: Screens, day_card: Callable[[], DayCard | None],
) -> tuple[Router, Router]:
    router = Router(name="warmup")
    nav = Router(name="warmup.nav")

    def wbtn(actor: Actor, token: int, text: str, action: str, value: str | None = None) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=WCb(o=actor.user_id, t=token, a=action, v=value).pack())

    def cancel(actor: Actor, token: int) -> InlineKeyboardButton:
        return InlineKeyboardButton(text="✕ Отмена", callback_data=CancelCb(o=actor.user_id, t=token).pack())

    def minute() -> int:
        return int(days.now().timestamp() // 60)

    def pairs(buttons: list[InlineKeyboardButton]) -> list[list[InlineKeyboardButton]]:
        return [buttons[i: i + 2] for i in range(0, len(buttons), 2)]

    # --- черновик ---
    def draft_text(exercises: list[ExerciseView], values: dict[str, int], day: date, number: int) -> str:
        line = " · ".join(f"{e.short} {format_value(e.measure, values.get(e.public_id, 0))}" for e in exercises)
        return f"🤸 Зарядка · {format_day(day)} · {ordinal(number)} за день\n{line}"

    def main_keyboard(actor: Actor, token: int, exercises: list[ExerciseView], has_last: bool,
                      ) -> InlineKeyboardMarkup:
        rows: list[list[InlineKeyboardButton]] = []
        if has_last:
            rows.append([wbtn(actor, token, "✅ Как в прошлый раз", "same")])
        rows += pairs([wbtn(actor, token, f"{e.short} {format_step(e.measure, e.step)}", "inc", e.public_id)
                       for e in exercises])
        rows.append([wbtn(actor, token, "✏️ Изменить", "edit"), wbtn(actor, token, "💾 Записать", "save")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def edit_keyboard(actor: Actor, token: int, exercises: list[ExerciseView], values: dict[str, int],
                      ) -> InlineKeyboardMarkup:
        rows = [[wbtn(actor, token, "−", "dec", e.public_id),
                 wbtn(actor, token, f"{e.short} {format_value(e.measure, values.get(e.public_id, 0))}", "val",
                      e.public_id),
                 wbtn(actor, token, "+", "inc", e.public_id)] for e in exercises]
        rows.append([wbtn(actor, token, "← Готово", "main"), wbtn(actor, token, "💾 Записать", "save")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def render(actor: Actor, state: FSMContext, day: date) -> tuple[str, InlineKeyboardMarkup]:
        data = await state.get_data()
        exercises = await warmup.templates(actor)
        values = data.get("values", {})
        token = await dialog_token(state)
        text = draft_text(exercises, values, day, await warmup.next_number(actor, day))
        if data.get("mode") == "edit":
            if not data.get("has_last"):
                text = f"{text}\n{FIRST_TIME}"
            return text, edit_keyboard(actor, token, exercises, values)
        return text, main_keyboard(actor, token, exercises, bool(data.get("has_last")))

    async def open_screen(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, day: date) -> None:
        if not await warmup.ensure_set(actor):
            await state.clear()
            markup = InlineKeyboardMarkup(inline_keyboard=[[wbtn(actor, 0, "Взять набор по умолчанию", "defaults")],
                                                           [wbtn(actor, 0, "➕ Добавить упражнение", "add")]])
            await bot.send_message(chat_id, EMPTY_SET, reply_markup=markup)
            return
        last = await warmup.last_values(actor, day)
        await start_dialog(state, WarmupInput.draft, day)
        await state.update_data(values=last or {}, has_last=last is not None, mode="main" if last else "edit")
        text, markup = await render(actor, state, day)
        await bot.send_message(chat_id, text, reply_markup=markup)

    async def refresh(query: CallbackQuery, actor: Actor, state: FSMContext, day: date) -> None:
        await query.answer()
        if isinstance(query.message, Message):
            text, markup = await render(actor, state, day)
            await query.message.edit_text(text, reply_markup=markup)

    def is_label(text: str | None) -> bool:
        entry = screens.menu.get(KIND)
        return entry is not None and text is not None and text.strip() == entry.label

    @nav.message(F.text.func(is_label))
    async def open_warmup(message: Message, bot: Bot, actor: Actor, state: FSMContext, record_day: date) -> None:
        await open_screen(bot, message.chat.id, actor, state, record_day)

    @router.callback_query(WCb.filter(F.a == "defaults"))
    async def defaults(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext, record_day: date) -> None:
        await screens.close_buttons(query)
        await warmup.use_default_set(actor)
        await open_screen(bot, query.from_user.id, actor, state, record_day)

    @router.callback_query(StateFilter(WarmupInput.draft), WCb.filter(F.a.in_({"inc", "dec"})))
    async def step(query: CallbackQuery, callback_data: WCb, actor: Actor, state: FSMContext,
                   record_day: date) -> None:
        exercise = next((e for e in await warmup.templates(actor) if e.public_id == callback_data.v), None)
        if exercise is None:
            await query.answer()
            return
        values: dict[str, int] = dict((await state.get_data()).get("values", {}))
        direction = 1 if callback_data.a == "inc" else -1
        values[exercise.public_id] = apply_step(values.get(exercise.public_id, 0), exercise.step, direction)
        await state.update_data(values=values)
        await refresh(query, actor, state, record_day)

    @router.callback_query(StateFilter(WarmupInput.draft), WCb.filter(F.a.in_({"edit", "main"})))
    async def mode(query: CallbackQuery, callback_data: WCb, actor: Actor, state: FSMContext,
                   record_day: date) -> None:
        await state.update_data(mode="edit" if callback_data.a == "edit" else "main")
        await refresh(query, actor, state, record_day)

    @router.callback_query(StateFilter(WarmupInput.draft), WCb.filter(F.a == "val"))
    async def ask_value(query: CallbackQuery, callback_data: WCb, bot: Bot, actor: Actor, state: FSMContext) -> None:
        exercise = next((e for e in await warmup.templates(actor) if e.public_id == callback_data.v), None)
        await query.answer()
        if exercise is None:
            return
        await state.update_data(editing=exercise.public_id)
        await state.set_state(WarmupInput.value)
        hint = "5:45, 5.45 или в секундах: 345" if exercise.measure is Measure.SECONDS else "числом"
        await bot.send_message(query.from_user.id, f"{exercise.name}: сколько? {hint}.")

    @router.message(StateFilter(WarmupInput.value), F.text)
    async def exact_value(message: Message, bot: Bot, actor: Actor, state: FSMContext, record_day: date) -> None:
        data = await state.get_data()
        exercise = next((e for e in await warmup.templates(actor) if e.public_id == data.get("editing")), None)
        if exercise is None:
            raise AppError("UI-STALE")
        values = dict(data.get("values", {}))
        values[exercise.public_id] = parse_value(exercise.measure, message.text or "", exercise.name)
        await state.update_data(values=values, mode="edit")
        await state.set_state(WarmupInput.draft)
        text, markup = await render(actor, state, record_day)
        await bot.send_message(message.chat.id, text, reply_markup=markup)

    async def saved(bot: Bot, chat_id: int, actor: Actor, session: SessionView, today: date) -> None:
        lines = await warmup.progress_lines(actor, today, {i.template_id for i in session.items if i.template_id})
        render_card = day_card()
        card = await render_card(actor, session.day) if render_card else ""
        text = f"🤸 Зарядка {ordinal(session.number)} за {format_day(session.day)}: {session.summary()}"
        body = "\n".join([html.escape(text), *(html.escape(line) for line in lines), card])
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Отменить", callback_data=WarmupEntryCb(
                o=actor.user_id, t=0, i=session.public_id, m=minute()).pack()),
            move_button(actor.user_id, KIND, session.public_id, minute()),
        ]])
        await bot.send_message(chat_id, body, parse_mode="HTML", reply_markup=markup)

    @router.callback_query(StateFilter(WarmupInput.draft), WCb.filter(F.a.in_({"save", "same"})))
    async def save(query: CallbackQuery, callback_data: WCb, bot: Bot, actor: Actor, state: FSMContext,
                   record_day: date, today: date, request_id: str | None) -> None:
        data = await state.get_data()
        if callback_data.a == "same":
            values = await warmup.last_values(actor, record_day) or {}
        else:
            # Записываются все упражнения с экрана, включая нули — как пользователь их видел.
            values = {e.public_id: data.get("values", {}).get(e.public_id, 0) for e in await warmup.templates(actor)}
        session = await warmup.record(actor, values, day=record_day, request_id=request_id)
        await state.clear()
        await screens.close_buttons(query)
        await saved(bot, query.from_user.id, actor, session, today)

    @router.callback_query(WarmupEntryCb.filter())
    async def undo(query: CallbackQuery, callback_data: WarmupEntryCb, bot: Bot, actor: Actor) -> None:
        if minute() - callback_data.m > 24 * 60:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        removed = await warmup.delete_session(actor, callback_data.i)
        if removed is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        await screens.close_buttons(query)
        await bot.send_message(query.from_user.id, f"Зарядка {ordinal(removed.number)} за "
                                                   f"{format_day(removed.day)} удалена.")

    # --- настройки (раздел 3.11) ---
    async def settings_screen(bot: Bot, chat_id: int, actor: Actor) -> None:
        exercises = await warmup.templates(actor)
        goals = await warmup.goals(actor)
        lines = [SETTINGS_TITLE,
                 "Набор: " + (" · ".join(f"{e.short} ({format_step(e.measure, e.step)})" for e in exercises)
                              or "пусто"),
                 f"Зарядок в день: {await warmup.daily_goal(actor)}",
                 "Личные цели: " + (" · ".join(f"{g.exercise.short} {format_value(g.exercise.measure, g.target)} к "
                                               f"{format_day(g.target_date)}" for g in goals) or "нет")]
        rows = [[wbtn(actor, 0, "📋 Набор и шаги", "set"), wbtn(actor, 0, "🎯 Личные цели", "goals")],
                [wbtn(actor, 0, f"Зарядок в день: {n}", "daily", str(n)) for n in (1, 2, 3)]]
        await bot.send_message(chat_id, "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(MenuCb.filter(F.k == "warmup_settings"))
    @router.callback_query(WCb.filter(F.a == "settings"))
    async def open_settings(query: CallbackQuery, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        await settings_screen(bot, query.from_user.id, actor)

    @router.callback_query(WCb.filter(F.a == "daily"))
    async def daily(query: CallbackQuery, callback_data: WCb, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        await warmup.set_daily_goal(actor, int(callback_data.v or "2"))
        await settings_screen(bot, query.from_user.id, actor)

    async def set_screen(bot: Bot, chat_id: int, actor: Actor) -> None:
        rows = [[wbtn(actor, 0, f"{e.short} {format_step(e.measure, e.step)}", "step", e.public_id),
                 wbtn(actor, 0, "⬆", "up", e.public_id), wbtn(actor, 0, "✕", "rm", e.public_id)]
                for e in await warmup.templates(actor)]
        rows.append([wbtn(actor, 0, "➕ Добавить упражнение", "add"), wbtn(actor, 0, "← Настройки", "settings")])
        await bot.send_message(chat_id, "📋 Набор зарядки: нажмите упражнение, чтобы изменить шаг.",
                               reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(WCb.filter(F.a.in_({"set", "up", "rm"})))
    async def edit_set(query: CallbackQuery, callback_data: WCb, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        if callback_data.a == "up":
            await warmup.move_up(actor, callback_data.v or "")
        elif callback_data.a == "rm":
            await warmup.remove_exercise(actor, callback_data.v or "")
        await set_screen(bot, query.from_user.id, actor)

    @router.callback_query(WCb.filter(F.a == "step"))
    async def ask_step(query: CallbackQuery, callback_data: WCb, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await screens.close_buttons(query)
        exercise = next((e for e in await warmup.templates(actor) if e.public_id == callback_data.v), None)
        if exercise is None:
            return
        token = await start_dialog(state, WarmupInput.step)
        await state.update_data(exercise=exercise.public_id)
        hint = "в секундах или как 1:00" if exercise.measure is Measure.SECONDS else "числом повторов"
        await bot.send_message(query.from_user.id, f"Шаг для «{exercise.name}» — {hint}:",
                               reply_markup=InlineKeyboardMarkup(inline_keyboard=[[cancel(actor, token)]]))

    @router.message(StateFilter(WarmupInput.step), F.text)
    async def new_step(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        wanted = (await state.get_data()).get("exercise")
        exercise = next((e for e in await warmup.templates(actor) if e.public_id == wanted), None)
        if exercise is None:
            raise AppError("UI-STALE")
        updated = await warmup.set_step(actor, exercise.public_id, parse_step(exercise.measure, message.text or ""))
        await state.clear()
        await message.answer(f"Шаг сохранён: «{updated.short} {format_step(updated.measure, updated.step)}».")
        await set_screen(bot, message.chat.id, actor)

    @router.callback_query(WCb.filter(F.a == "add"))
    async def add(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await screens.close_buttons(query)
        token = await start_dialog(state, WarmupInput.new_name)
        await bot.send_message(query.from_user.id, "Название упражнения?",
                               reply_markup=InlineKeyboardMarkup(inline_keyboard=[[cancel(actor, token)]]))

    @router.message(StateFilter(WarmupInput.new_name), F.text)
    async def add_name(message: Message, actor: Actor, state: FSMContext) -> None:
        name = " ".join((message.text or "").split())
        if not 1 <= len(name) <= 64:
            raise AppError("INPUT-TEXT", field="Название", low=1, high=64, length=len(name))
        await state.update_data(name=name)
        await state.set_state(WarmupInput.new_measure)
        token = await dialog_token(state)
        await message.answer("Что записывать?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            wbtn(actor, token, "Повторы", "measure", Measure.REPS.value),
            wbtn(actor, token, "Время", "measure", Measure.SECONDS.value)], [cancel(actor, token)]]))

    @router.callback_query(StateFilter(WarmupInput.new_measure), WCb.filter(F.a == "measure"))
    async def add_measure(query: CallbackQuery, callback_data: WCb, bot: Bot, actor: Actor,
                          state: FSMContext) -> None:
        await screens.close_buttons(query)
        name = (await state.get_data()).get("name", "")
        await state.clear()
        exercise = await warmup.add_exercise(actor, name=name, measure=Measure(callback_data.v or "reps"))
        await bot.send_message(query.from_user.id, f"«{exercise.name}» добавлено в набор, шаг "
                                                   f"{format_step(exercise.measure, exercise.step)}.")
        await set_screen(bot, query.from_user.id, actor)

    # --- личные цели ---
    @router.callback_query(WCb.filter(F.a == "goals"))
    async def goals(query: CallbackQuery, bot: Bot, actor: Actor, today: date) -> None:
        await screens.close_buttons(query)
        lines = await warmup.progress_lines(actor, today)
        rows = [[wbtn(actor, 0, f"✕ {g.exercise.short} {format_value(g.exercise.measure, g.target)}", "goalrm",
                      g.public_id)] for g in await warmup.goals(actor)]
        rows.append([wbtn(actor, 0, "➕ Новая цель", "goalnew"), wbtn(actor, 0, "← Настройки", "settings")])
        text = "🎯 Личные цели\n" + ("\n".join(lines) if lines else "Целей пока нет.")
        await bot.send_message(query.from_user.id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(WCb.filter(F.a == "goalrm"))
    async def goal_remove(query: CallbackQuery, callback_data: WCb, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query, toast="Цель убрана")
        await warmup.remove_goal(actor, callback_data.v or "")
        await settings_screen(bot, query.from_user.id, actor)

    @router.callback_query(WCb.filter(F.a == "goalnew"))
    async def goal_pick(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await screens.close_buttons(query)
        token = await start_dialog(state, WarmupInput.goal_value)
        buttons = [wbtn(actor, token, e.short, "goalex", e.public_id) for e in await warmup.templates(actor)]
        await bot.send_message(query.from_user.id, "Для какого упражнения цель?",
                               reply_markup=InlineKeyboardMarkup(inline_keyboard=[*pairs(buttons),
                                                                                  [cancel(actor, token)]]))

    @router.callback_query(StateFilter(WarmupInput.goal_value), WCb.filter(F.a == "goalex"))
    async def goal_exercise(query: CallbackQuery, callback_data: WCb, bot: Bot, actor: Actor,
                            state: FSMContext) -> None:
        await screens.close_buttons(query)
        exercise = next((e for e in await warmup.templates(actor) if e.public_id == callback_data.v), None)
        if exercise is None:
            return
        await state.update_data(exercise=exercise.public_id)
        example = "11:00" if exercise.measure is Measure.SECONDS else "80"
        await bot.send_message(query.from_user.id, f"{exercise.name}: " + GOAL_PROMPT.format(example=example))

    @router.message(StateFilter(WarmupInput.goal_value), F.text)
    async def goal_value(message: Message, actor: Actor, state: FSMContext, today: date) -> None:
        data: dict[str, Any] = await state.get_data()
        exercise = next((e for e in await warmup.templates(actor) if e.public_id == data.get("exercise")), None)
        if exercise is None:
            await message.answer("Сначала выберите упражнение кнопкой выше 👆")
            return
        parts = re.split(r"\s+", (message.text or "").strip())
        if len(parts) != 2:
            raise AppError("INPUT-DATE", value=message.text or "")
        target = parse_value(exercise.measure, parts[0], exercise.name)
        target_date = parse_date(parts[1], today)
        await warmup.set_goal(actor, exercise.public_id, target=target, target_date=target_date)
        await state.clear()
        lines = await warmup.progress_lines(actor, today, {exercise.public_id})
        await message.answer("Цель сохранена.\n" + "\n".join(lines))

    return nav, router
