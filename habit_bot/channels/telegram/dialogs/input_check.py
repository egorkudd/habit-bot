"""«/check» — проверка ввода чисел, времени и дат в три шага. Ничего не записывает.

Нужна, чтобы владелец проверил каркас диалогов части 2 до появления разделов: разбор «77,5» и «77.5»,
подсказки ``INPUT-*``, «✕ Отмена», сброс через 15 минут и «Это меню устарело».
"""

from __future__ import annotations

from datetime import date, tzinfo
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from habit_bot.channels.telegram.dialogs.fsm import dialog_token, start_dialog
from habit_bot.channels.telegram.ui.callbacks import CancelCb, StepCb
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.clock import Clock
from habit_bot.kernel.domain.formatting import format_date, format_duration, format_number
from habit_bot.kernel.domain.parsing import (
    ensure_not_future,
    logical_day,
    parse_date,
    parse_duration,
    parse_number_in_range,
)
from habit_bot.kernel.identity import Actor

DONE = "done"
STEP_HEIGHT = "Проверка ввода — ничего не записывается.\n1/3. Рост в см — например 178 или 177,5"
STEP_TIME = "2/3. Время планки — 5:45, 5.45 или в секундах: 345"
STEP_DATE = "3/3. Дата — 20.10, 20.10.2026 или «вчера». Будущую нельзя"
RESULT = (
    "Понял так:\n• рост {height} см\n• время {time} ({seconds} сек)\n• дата {day}\n"
    "Нажмите «Готово» или «✕ Отмена»."
)
FINISHED = "Готово. Это была проверка — ничего не записано."


class InputCheck(StatesGroup):
    height = State()
    time = State()
    day = State()
    confirm = State()


def cancel_row(actor: Actor, token: int) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="✕ Отмена", callback_data=CancelCb(o=actor.user_id, t=token).pack())]


def build_input_check_router(clock: Clock, tz: tzinfo, screens: Screens) -> Router:
    router = Router(name="input_check")

    async def ask(message: Message, actor: Actor, state: FSMContext, text: str) -> None:
        token = await dialog_token(state)
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_row(actor, token)]))

    @router.message(Command("check"))
    async def begin(message: Message, actor: Actor, state: FSMContext) -> None:
        await start_dialog(state, InputCheck.height)
        await ask(message, actor, state, STEP_HEIGHT)

    @router.message(StateFilter(InputCheck.height), F.text)
    async def height(message: Message, actor: Actor, state: FSMContext) -> None:
        value = parse_number_in_range(message.text or "", low=120, high=230, field="Рост", unit="см")
        await state.update_data(height=str(value))
        await state.set_state(InputCheck.time)
        await ask(message, actor, state, STEP_TIME)

    @router.message(StateFilter(InputCheck.time), F.text)
    async def duration(message: Message, actor: Actor, state: FSMContext) -> None:
        await state.update_data(seconds=parse_duration(message.text or ""))
        await state.set_state(InputCheck.day)
        await ask(message, actor, state, STEP_DATE)

    @router.message(StateFilter(InputCheck.day), F.text)
    async def day(message: Message, actor: Actor, state: FSMContext) -> None:
        today = logical_day(clock.now(), tz)
        chosen = ensure_not_future(parse_date(message.text or "", today), today)
        data = await state.update_data(day=chosen.isoformat())
        await state.set_state(InputCheck.confirm)
        token = await dialog_token(state)
        text = RESULT.format(
            height=format_number(Decimal(data["height"])), time=format_duration(data["seconds"]),
            seconds=data["seconds"], day=format_date(date.fromisoformat(data["day"])),
        )
        done = InlineKeyboardButton(text="✅ Готово", callback_data=StepCb(o=actor.user_id, t=token, a=DONE).pack())
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[done, *cancel_row(actor, token)]])
        await message.answer(text, reply_markup=keyboard)

    @router.callback_query(StateFilter(InputCheck.confirm), StepCb.filter(F.a == DONE))
    async def finish(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await state.clear()
        await screens.close_buttons(query)
        await screens.home(bot, query.from_user.id, actor, FINISHED)

    return router
