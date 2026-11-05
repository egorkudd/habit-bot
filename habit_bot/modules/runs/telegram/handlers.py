"""«🏃 Бег» в Telegram (раздел 3.5): дистанция кнопками или числом, время, проверка нереального темпа, карточка
«🏃 5,2 км · 28:40 · темп 5:31 · 10,88 км/ч · ▲ на 0:09 быстрее прошлого», рекорды, «Отменить», «📅 На вчера»."""

from __future__ import annotations

import html
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message

from habit_bot.channels.telegram.dialogs.fsm import dialog_token, start_dialog
from habit_bot.channels.telegram.ui import trail
from habit_bot.channels.telegram.ui.callbacks import CancelCb, MenuCb, move_button
from habit_bot.channels.telegram.ui.layout import fit_rows, inline
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.domain.formatting import format_day, format_duration
from habit_bot.kernel.identity import Actor
from habit_bot.modules.days.public import Days
from habit_bot.modules.runs.domain.runs import (
    QUICK_DISTANCES,
    km,
    pace,
    parse_distance,
    parse_run_time,
    run_line,
    suspicious,
)
from habit_bot.modules.runs.usecases import Runs

KIND = "run"
TIME_PROMPT = "Время: 28:40, 28.40, 1:05:10 или целыми минутами: 28."
DayCard = Callable[[Actor, date], Awaitable[str]]
WeekProgress = Callable[[Actor, date], Awaitable[tuple[int, int] | None]]


class RCb(CallbackData, prefix="rn"):
    o: int
    t: int
    a: str
    v: str | None = None


class RunEntryCb(CallbackData, prefix="re"):
    """«Отменить» под карточкой забега: 24 часа."""

    o: int
    t: int
    i: str
    m: int


class RunInput(StatesGroup):
    distance = State()
    time = State()
    confirm = State()


def build_runs_router(runs: Runs, days: Days, screens: Screens, day_card: Callable[[], DayCard | None],
                      week_progress: Callable[[], WeekProgress | None]) -> Router:
    router = Router(name="runs")

    def btn(actor: Actor, token: int, text: str, action: str, value: str | None = None) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=RCb(o=actor.user_id, t=token, a=action, v=value).pack())

    def cancel(actor: Actor, token: int) -> InlineKeyboardButton:
        return InlineKeyboardButton(text="✕ Отмена", callback_data=CancelCb(o=actor.user_id, t=token).pack())

    def minute() -> int:
        return int(days.now().timestamp() // 60)

    @router.callback_query(MenuCb.filter(F.k == KIND))
    async def start(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext, record_day: date) -> None:
        await screens.close_buttons(query)
        token = await start_dialog(state, RunInput.distance, record_day)
        last = await runs.last(actor)
        rows = []
        if last is not None:
            rows.append([btn(actor, token, f"Как в прошлый раз ({km(last.distance_km)})", "d",
                             str(last.distance_km))])
        rows += fit_rows([btn(actor, token, km(d).replace(",0", ""), "d", str(d)) for d in QUICK_DISTANCES], 3)
        rows.append([cancel(actor, token)])
        await bot.send_message(query.from_user.id, "🏃 Дистанция? Кнопкой или числом: 5.2 или 5,2.",
                               reply_markup=inline(rows))

    async def ask_time(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, distance: Decimal) -> None:
        await state.update_data(distance=str(distance))
        await state.set_state(RunInput.time)
        token = await dialog_token(state)
        await bot.send_message(chat_id, f"🏃 {km(distance)}. {TIME_PROMPT}", reply_markup=inline([[cancel(actor,
                                                                                                         token)]]))

    @router.callback_query(StateFilter(RunInput.distance), RCb.filter(F.a == "d"))
    async def distance_button(query: CallbackQuery, callback_data: RCb, bot: Bot, actor: Actor,
                              state: FSMContext) -> None:
        await screens.close_buttons(query)
        await ask_time(bot, query.from_user.id, actor, state, Decimal(callback_data.v or "5"))

    @router.message(StateFilter(RunInput.distance), F.text)
    async def distance_text(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await ask_time(bot, message.chat.id, actor, state, parse_distance(message.text or ""))

    async def save(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, record_day: date,
                   request_id: str | None) -> None:
        data = await state.get_data()
        run = await runs.record(actor, distance_km=Decimal(data["distance"]), seconds=int(data["seconds"]),
                                day=record_day, request_id=request_id)
        await state.clear()
        lines = [f"{run_line(run.value)} · {run.comparison}", *run.records]
        progress = week_progress()
        if progress is not None:
            result = await progress(actor, run.day)
            if result is not None:
                lines.append(f"Тренировок за неделю: {result[0]}/{result[1]}")
        render = day_card()
        card = await render(actor, run.day) if render else ""
        markup = inline([[InlineKeyboardButton(text="Отменить", callback_data=RunEntryCb(
            o=actor.user_id, t=0, i=run.public_id, m=minute()).pack()),
            move_button(actor.user_id, KIND, run.public_id, minute())]])
        trail.result()
        await bot.send_message(chat_id, html.escape("\n".join(lines)) + "\n" + card, parse_mode="HTML",
                               reply_markup=markup)

    @router.message(StateFilter(RunInput.time), F.text)
    async def time_text(message: Message, bot: Bot, actor: Actor, state: FSMContext, record_day: date,
                        request_id: str | None) -> None:
        seconds = parse_run_time(message.text or "")
        distance = Decimal((await state.get_data())["distance"])
        await state.update_data(seconds=seconds)
        per_km = pace(distance, seconds)
        if suspicious(per_km):
            await state.set_state(RunInput.confirm)
            token = await dialog_token(state)
            await message.answer(f"Темп {format_duration(per_km)} мин/км ({km(distance)} за "
                                 f"{format_duration(seconds)}) — всё верно?",
                                 reply_markup=inline([[btn(actor, token, "Да, записать", "yes"),
                                                       btn(actor, token, "Нет, ввести заново", "no")]]))
            return
        await save(bot, message.chat.id, actor, state, record_day, request_id)

    @router.callback_query(StateFilter(RunInput.confirm), RCb.filter(F.a.in_({"yes", "no"})))
    async def confirm(query: CallbackQuery, callback_data: RCb, bot: Bot, actor: Actor, state: FSMContext,
                      record_day: date, request_id: str | None) -> None:
        await screens.close_buttons(query)
        if callback_data.a == "yes":
            await save(bot, query.from_user.id, actor, state, record_day, request_id)
            return
        await state.set_state(RunInput.distance)
        token = await dialog_token(state)
        await bot.send_message(query.from_user.id, "🏃 Дистанция ещё раз? Числом: 5.2.",
                               reply_markup=inline([[cancel(actor, token)]]))

    @router.callback_query(RunEntryCb.filter())
    async def undo(query: CallbackQuery, callback_data: RunEntryCb, bot: Bot, actor: Actor) -> None:
        if minute() - callback_data.m > 24 * 60:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        removed = await runs.delete(actor, callback_data.i)
        if removed is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        await screens.close_buttons(query)
        if query.message is not None:
            trail.discard(query.message.message_id)
        trail.result()
        await bot.send_message(query.from_user.id, f"Забег {km(removed.value.distance_km)} за "
                                                   f"{format_day(removed.day)} удалён.")

    return router
