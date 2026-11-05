"""«🏋️ Тренировка» в Telegram (раздел 3.4.0): зал / площадка / свободная, «➕ Упражнение» (10 последних, «Все по
группам», «Новое упражнение»), подходы («Как в прошлый раз», вес «−шаг» / «+шаг», «4×8» или по подходам),
«Завершить» → длительность → итог с тоннажем. Идущая тренировка живёт в области ``workout`` (3 часа), поэтому пауза
в 20 минут её не сбрасывает. Логика — в ``Workouts``; здесь только кнопки и тексты."""

from __future__ import annotations

import html
import re
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Filter, StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from habit_bot.channels.telegram.dialogs.fsm import context_for, dialog_token, start_dialog
from habit_bot.channels.telegram.dialogs.policy import WORKOUT
from habit_bot.channels.telegram.ui import trail
from habit_bot.channels.telegram.ui.callbacks import CancelCb, MenuCb, move_button
from habit_bot.channels.telegram.ui.layout import fit_rows, inline
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.domain.formatting import format_day, format_number
from habit_bot.kernel.domain.parsing import parse_number_in_range
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.identity import Actor
from habit_bot.modules.days.public import Days
from habit_bot.modules.workouts.domain.training import (
    BAND_LABELS,
    GROUP_LABELS,
    KIND_LABELS,
    MEASURE_LABELS,
    OUTDOOR_EQUIPMENT,
    Band,
    Equipment,
    Group,
    Kind,
    Measure,
    SetValue,
    format_sets,
    kg,
    parse_counts,
    parse_weight,
    step_weight,
    tonnage,
)
from habit_bot.modules.workouts.usecases import ExerciseView, SessionView, Workouts

KIND = "workout"
RUN_KEY = "run"
SETTINGS_KEY = "workout_settings"
DURATIONS = (60, 70, 80, 90)
DayCard = Callable[[Actor, date], Awaitable[str]]
WeekProgress = Callable[[Actor, date], Awaitable[tuple[int, int]]]
_COUNTS = re.compile(r"[×xх*]|\s", re.IGNORECASE)


class WkCb(CallbackData, prefix="wk"):
    o: int
    t: int
    a: str
    v: str | None = None


class SessionCb(CallbackData, prefix="ws"):
    """«Отменить» под итогом тренировки: 24 часа."""

    o: int
    t: int
    i: str
    m: int


class WorkoutInput(StatesGroup):
    """Шаги внутри идущей тренировки — в области ``workout`` (3 часа)."""

    screen = State()    # экран тренировки
    sets = State()      # ждём подходы (и вес) упражнения
    new_name = State()  # название нового упражнения
    duration = State()  # длительность при завершении


class OutdoorInput(StatesGroup):
    """Перед площадкой: «Резинка с собой?» и «Чего-то нет?» — обычный ввод (15 минут)."""

    prepare = State()


class WorkoutText(Filter):
    """Текст для шага идущей тренировки — если сейчас не идёт другой ввод."""

    def __init__(self, step: State) -> None:
        self._step = step.state

    async def __call__(self, message: Message, state: FSMContext | None = None,
                       raw_state: str | None = None) -> bool:
        if state is None or raw_state is not None or not message.text:
            return False
        return await context_for(state, WORKOUT).get_state() == self._step


def build_workouts_router(
    workouts: Workouts, days: Days, screens: Screens, day_card: Callable[[], DayCard | None],
    week_progress: WeekProgress,
) -> tuple[Router, Router]:
    router = Router(name="workouts")
    nav = Router(name="workouts.nav")

    def btn(actor: Actor, token: int, text: str, action: str, value: str | None = None) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=WkCb(o=actor.user_id, t=token, a=action, v=value).pack())

    def cancel(actor: Actor, token: int) -> InlineKeyboardButton:
        return InlineKeyboardButton(text="✕ Отмена", callback_data=CancelCb(o=actor.user_id, t=token).pack())

    def minute() -> int:
        return int(days.now().timestamp() // 60)

    def wctx(state: FSMContext) -> FSMContext:
        return context_for(state, WORKOUT)

    async def wtoken(state: FSMContext) -> int:
        return await dialog_token(wctx(state))

    async def card(actor: Actor, day: date) -> str:
        render = day_card()
        return await render(actor, day) if render else ""

    def block_lines(session: SessionView) -> list[str]:
        return [f"{n}. {b.name} — {format_sets(b.measure, b.sets, b.per_dumbbell)}"
                + (f" · {kg(b.tonnage)}" if b.tonnage else "") for n, b in enumerate(session.blocks, 1)]

    def session_text(session: SessionView, head: str = "") -> str:
        started = session.started_at.astimezone(days.tz).strftime("%H:%M")
        lines = [*([head, ""] if head else []),
                 f"{KIND_LABELS[session.kind]} · {format_day(session.day)} · идёт с {started}"]
        lines += block_lines(session) or ["Упражнений пока нет — «➕ Упражнение»."]
        if session.tonnage:
            lines.append(f"Тоннаж: {kg(session.tonnage)}")
        return "\n".join(lines)

    async def remember_screen(state: FSMContext, message_id: int) -> None:
        """Прежний экран тренировки заменяет новый — в чате один экран (чистый чат)."""
        ctx = wctx(state)
        trail.discard((await ctx.get_data()).get("screen"))
        await ctx.update_data(screen=message_id)

    async def show_session(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, session: SessionView,
                           head: str = "") -> None:
        ctx = wctx(state)
        await ctx.set_state(WorkoutInput.screen)
        await ctx.update_data(session=session.public_id, exercise=None)
        token = await wtoken(state)
        rows = [[btn(actor, token, "➕ Упражнение" if not session.blocks else "➕ Следующее упражнение", "add"),
                 btn(actor, token, "🏁 Завершить", "finish")]]
        if session.blocks:
            rows.append([btn(actor, token, "↩ Убрать последнее", "undo")])
        sent = await bot.send_message(chat_id, session_text(session, head), reply_markup=inline(rows))
        await remember_screen(state, sent.message_id)

    async def current(state: FSMContext, actor: Actor) -> SessionView | None:
        public_id = (await wctx(state).get_data()).get("session")
        found = await workouts.session(actor, public_id or "") if public_id else None
        return found if found is not None and found.open else None

    # --- вход: «🏋️ Тренировка» ---
    async def open_section(bot: Bot, chat_id: int, actor: Actor, state: FSMContext) -> None:
        await state.clear()
        running = await workouts.open_session(actor)
        if running is not None:
            ctx = wctx(state)
            if await ctx.get_state() is None:
                await start_dialog(ctx, WorkoutInput.screen)
            await show_session(bot, chat_id, actor, state, running, "Тренировка идёт:")
            return
        rows = [[btn(actor, 0, KIND_LABELS[Kind.GYM], "kind", Kind.GYM.value),
                 btn(actor, 0, KIND_LABELS[Kind.OUTDOOR], "kind", Kind.OUTDOOR.value)],
                [btn(actor, 0, KIND_LABELS[Kind.FREE], "kind", Kind.FREE.value),
                 InlineKeyboardButton(text="🏃 Бег", callback_data=MenuCb(o=actor.user_id, t=0, k=RUN_KEY).pack())]]
        done, goal = await week_progress(actor, days.today())
        await bot.send_message(chat_id, f"🏋️ Какая тренировка? За неделю: {done}/{goal}.", reply_markup=inline(rows))

    def is_label(text: str | None) -> bool:
        entry = screens.menu.get(KIND)
        return entry is not None and text is not None and text.strip() == entry.label

    @nav.message(F.text.func(is_label))
    async def from_home(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await open_section(bot, message.chat.id, actor, state)

    @nav.callback_query(MenuCb.filter(F.k == KIND))
    async def from_more(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await screens.close_buttons(query)
        await open_section(bot, query.from_user.id, actor, state)

    async def begin(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, kind: Kind, day: date,
                    band: bool | None = None, missing: tuple[Equipment, ...] = ()) -> None:
        await state.clear()
        session = await workouts.start(actor, kind, day=day, band=band, missing=missing)
        await start_dialog(wctx(state), WorkoutInput.screen, day)
        await show_session(bot, chat_id, actor, state, session)

    @router.callback_query(WkCb.filter(F.a == "kind"))
    async def choose_kind(query: CallbackQuery, callback_data: WkCb, bot: Bot, actor: Actor, state: FSMContext,
                          record_day: date) -> None:
        await screens.close_buttons(query)
        kind = Kind(callback_data.v or Kind.GYM.value)
        if kind is not Kind.OUTDOOR:
            await begin(bot, query.from_user.id, actor, state, kind, record_day)
            return
        settings = await workouts.settings(actor)
        token = await start_dialog(state, OutdoorInput.prepare, record_day)
        await state.update_data(band=settings.band_last, missing=[])
        await send_prepare(bot, query.from_user.id, actor, state, token)

    async def prepare_markup(actor: Actor, state: FSMContext, token: int) -> tuple[str, InlineKeyboardMarkup]:
        data = await state.get_data()
        band, missing = bool(data.get("band")), set(data.get("missing", []))
        rows = [[btn(actor, token, f"{'✅ ' if band else ''}Резинка: да", "band", "1"),
                 btn(actor, token, f"{'✅ ' if not band else ''}Резинка: нет", "band", "0")]]
        rows += fit_rows([btn(actor, token, f"{'❌' if e.value in missing else '✅'} {label}", "miss", e.value)
                          for e, label in OUTDOOR_EQUIPMENT.items()])
        rows.append([btn(actor, token, "▶ Начать", "go"), cancel(actor, token)])
        absent = ", ".join(OUTDOOR_EQUIPMENT[Equipment(m)] for m in sorted(missing)) or "—"
        text = (f"🌳 Площадка. Резинка с собой? (по умолчанию — прошлый ответ)\nЧего-то нет? Нажмите, чтобы "
                f"исключить на этот раз. Нет: {absent}")
        return text, inline(rows)

    async def send_prepare(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, token: int) -> None:
        text, markup = await prepare_markup(actor, state, token)
        await bot.send_message(chat_id, text, reply_markup=markup)

    @router.callback_query(StateFilter(OutdoorInput.prepare), WkCb.filter(F.a.in_({"band", "miss"})))
    async def prepare_toggle(query: CallbackQuery, callback_data: WkCb, actor: Actor, state: FSMContext) -> None:
        data = await state.get_data()
        if callback_data.a == "band":
            await state.update_data(band=callback_data.v == "1")
        else:
            missing = set(data.get("missing", []))
            missing ^= {callback_data.v or ""}
            await state.update_data(missing=sorted(missing & {e.value for e in OUTDOOR_EQUIPMENT}))
        await query.answer()
        if isinstance(query.message, Message):
            text, markup = await prepare_markup(actor, state, await dialog_token(state))
            await query.message.edit_text(text, reply_markup=markup)

    @router.callback_query(StateFilter(OutdoorInput.prepare), WkCb.filter(F.a == "go"))
    async def prepare_go(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext, record_day: date) -> None:
        await screens.close_buttons(query)
        data = await state.get_data()
        await begin(bot, query.from_user.id, actor, state, Kind.OUTDOOR, record_day, band=bool(data.get("band")),
                    missing=tuple(Equipment(m) for m in data.get("missing", [])))

    # --- «➕ Упражнение» ---
    async def guard(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> SessionView | None:
        session = await current(state, actor)
        if session is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return None
        await workouts.touch(actor, session.public_id)
        return session

    @router.callback_query(WkCb.filter(F.a == "add"))
    async def add(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        session = await guard(query, bot, actor, state)
        if session is None:
            return
        await screens.close_buttons(query)
        token = await wtoken(state)
        filters = await workouts.session_filters(actor, session)
        recent = await workouts.recent(actor, filters)
        rows = fit_rows([btn(actor, token, e.name, "ex", e.public_id) for e in recent])
        rows.append([btn(actor, token, "📚 Все по группам", "groups"), btn(actor, token, "✍️ Новое", "new")])
        rows.append([btn(actor, token, "← К тренировке", "back")])
        title = "Недавние упражнения:" if recent else "Выберите группу мышц или создайте своё упражнение."
        sent = await bot.send_message(query.from_user.id, f"➕ {title}", reply_markup=inline(rows))
        await remember_screen(state, sent.message_id)

    @router.callback_query(WkCb.filter(F.a == "groups"))
    async def groups(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        session = await guard(query, bot, actor, state)
        if session is None:
            return
        await query.answer()
        token = await wtoken(state)
        found = await workouts.groups(actor, await workouts.session_filters(actor, session))
        rows = fit_rows([btn(actor, token, f"{GROUP_LABELS[g]} ({n})", "group", g.value) for g, n in found])
        rows.append([btn(actor, token, "← К тренировке", "back")])
        if isinstance(query.message, Message):
            await query.message.edit_text("📚 Группа мышц:", reply_markup=inline(rows))

    @router.callback_query(WkCb.filter(F.a == "group"))
    async def group(query: CallbackQuery, callback_data: WkCb, bot: Bot, actor: Actor, state: FSMContext) -> None:
        session = await guard(query, bot, actor, state)
        if session is None:
            return
        await query.answer()
        token = await wtoken(state)
        chosen = Group(callback_data.v or Group.LEGS.value)
        found = await workouts.exercises(actor, await workouts.session_filters(actor, session), chosen)
        rows = fit_rows([btn(actor, token, e.name, "ex", e.public_id) for e in found])
        rows.append([btn(actor, token, "← Группы", "groups"), btn(actor, token, "← К тренировке", "back")])
        if isinstance(query.message, Message):
            await query.message.edit_text(f"📚 {GROUP_LABELS[chosen]}:", reply_markup=inline(rows))

    @router.callback_query(WkCb.filter(F.a == "back"))
    async def back(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        session = await guard(query, bot, actor, state)
        if session is not None:
            await screens.close_buttons(query)
            await show_session(bot, query.from_user.id, actor, state, session)

    # --- новое упражнение ---
    @router.callback_query(WkCb.filter(F.a == "new"))
    async def new(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        session = await guard(query, bot, actor, state)
        if session is None:
            return
        await screens.close_buttons(query)
        await wctx(state).set_state(WorkoutInput.new_name)
        token = await wtoken(state)
        await bot.send_message(query.from_user.id, "Название нового упражнения?",
                               reply_markup=inline([[btn(actor, token, "← К тренировке", "back")]]))

    @router.message(WorkoutText(WorkoutInput.new_name))
    async def new_name(message: Message, actor: Actor, state: FSMContext) -> None:
        name = " ".join((message.text or "").split())
        if not 1 <= len(name) <= 64:
            raise AppError("INPUT-TEXT", field="Название", low=1, high=64, length=len(name))
        await wctx(state).update_data(new_name=name)
        token = await wtoken(state)
        buttons = [btn(actor, token, label, "nm", m.value) for m, label in MEASURE_LABELS.items()]
        await message.answer("Что записывать?", reply_markup=inline([*fit_rows(buttons),
                                                                     [btn(actor, token, "← К тренировке", "back")]]))

    @router.callback_query(WkCb.filter(F.a == "nm"))
    async def new_measure(query: CallbackQuery, callback_data: WkCb, bot: Bot, actor: Actor,
                          state: FSMContext) -> None:
        session = await guard(query, bot, actor, state)
        if session is None:
            return
        await screens.close_buttons(query)
        name = (await wctx(state).get_data()).get("new_name", "")
        exercise = await workouts.create_exercise(actor, name=name, measure=Measure(callback_data.v or "reps"),
                                                  kind=session.kind)
        await show_exercise(bot, query.from_user.id, actor, state, session, exercise)

    # --- упражнение: подходы ---
    async def show_exercise(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, session: SessionView,
                            exercise: ExerciseView, weight: Decimal | None = None, band: Band | None = None) -> None:
        spec = exercise.spec
        last = await workouts.last_sets(actor, exercise.public_id, before_session=session.public_id)
        last_sets = last[1] if last else ()
        if weight is None and spec.measure is Measure.WEIGHT_REPS:
            today = [b for b in session.blocks if b.exercise_id == exercise.public_id]
            source = today[-1].sets if today else last_sets  # сегодня уже делал — с того же веса
            weight = source[-1].weight if source else None
        settings = await workouts.settings(actor)
        if band is None and spec.measure is Measure.BAND_REPS:
            band = (last_sets[-1].band if last_sets else None) or (settings.bands[0] if settings.bands else Band.MEDIUM)
        ctx = wctx(state)
        await ctx.set_state(WorkoutInput.sets)
        await ctx.update_data(exercise=exercise.public_id, weight=str(weight) if weight is not None else None,
                              band=band.value if band else None)
        token = await wtoken(state)
        rows: list[list[InlineKeyboardButton]] = []
        lines = [f"🏋️ {exercise.name}"]
        if last is not None:
            shown = format_sets(spec.measure, last_sets, spec.per_dumbbell)
            lines.append(f"Прошлый раз {format_day(last[0])}: {shown}")
            rows.append([btn(actor, token, f"✅ Как в прошлый раз ({shown})"[:60], "same")])
        if spec.measure is Measure.WEIGHT_REPS:
            step = spec.weight_step or Decimal("2.5")
            each = " (вес каждой гантели)" if spec.per_dumbbell else ""
            lines.append(f"Вес: {kg(weight) if weight is not None else 'не задан — напишите, например 60'}{each}")
            if weight is not None:
                rows.append([btn(actor, token, f"−{format_number(step)}", "w", "-1"),
                             btn(actor, token, kg(weight), "noop"),
                             btn(actor, token, f"+{format_number(step)}", "w", "1")])
        if spec.measure is Measure.BAND_REPS:
            bands = settings.bands or tuple(Band)
            lines.append(f"Резинка: {BAND_LABELS[band] if band else '—'}")
            rows.append([btn(actor, token, f"{'✅ ' if b is band else ''}{BAND_LABELS[b]}", "band", b.value)
                         for b in bands])
        unit = "секунды: 3×45 или 1:00 0:50" if spec.measure is Measure.TIME else "4×8 или по подходам: 8 8 7 6"
        lines.append(f"Подходы — {unit}.")
        if spec.measure is not Measure.TIME:
            low, high = spec.reps_low, spec.reps_high
            presets = dict.fromkeys([f"3×{low}", f"4×{low}", f"3×{high}"])
            rows.append([btn(actor, token, p, "reps", p) for p in presets])
        rows.append([btn(actor, token, "← К тренировке", "back")])
        sent = await bot.send_message(chat_id, "\n".join(lines), reply_markup=inline(rows))
        await remember_screen(state, sent.message_id)

    @router.callback_query(WkCb.filter(F.a == "ex"))
    async def pick_exercise(query: CallbackQuery, callback_data: WkCb, bot: Bot, actor: Actor,
                            state: FSMContext) -> None:
        session = await guard(query, bot, actor, state)
        if session is None:
            return
        exercise = await workouts.exercise(actor, callback_data.v or "")
        if exercise is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        await screens.close_buttons(query)
        await show_exercise(bot, query.from_user.id, actor, state, session, exercise)

    async def chosen(state: FSMContext, actor: Actor) -> tuple[ExerciseView | None, dict[str, Any]]:
        data = await wctx(state).get_data()
        return await workouts.exercise(actor, data.get("exercise") or ""), data

    @router.callback_query(WkCb.filter(F.a.in_({"w", "band"})))
    async def adjust(query: CallbackQuery, callback_data: WkCb, bot: Bot, actor: Actor, state: FSMContext) -> None:
        session = await guard(query, bot, actor, state)
        exercise, data = await chosen(state, actor)
        if session is None:
            return
        if exercise is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        await screens.close_buttons(query)
        weight = Decimal(data["weight"]) if data.get("weight") else None
        band = Band(data["band"]) if data.get("band") else None
        if callback_data.a == "w" and weight is not None:
            weight = step_weight(weight, exercise.spec.weight_step or Decimal("2.5"), int(callback_data.v or "1"))
        if callback_data.a == "band":
            band = Band(callback_data.v or Band.MEDIUM.value)
        await show_exercise(bot, query.from_user.id, actor, state, session, exercise, weight, band)

    @router.callback_query(WkCb.filter(F.a == "noop"))
    async def noop(query: CallbackQuery) -> None:
        await query.answer("Вес меняется кнопками «−» / «+» или числом")

    async def save_sets(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, session: SessionView,
                        exercise: ExerciseView, sets: list[SetValue], request_id: str | None) -> None:
        updated = await workouts.add_sets(actor, session.public_id, exercise.public_id, sets, request_id=request_id)
        spec = exercise.spec
        head = f"✅ {exercise.name}: {format_sets(spec.measure, sets, spec.per_dumbbell)}"  # только что записанное
        added = tonnage(sets, spec.per_dumbbell)
        if added:
            head += f" · {kg(added)}"
        await show_session(bot, chat_id, actor, state, updated, head)

    def build_sets(exercise: ExerciseView, data: dict[str, Any], counts: list[int]) -> list[SetValue]:
        measure = exercise.spec.measure
        weight = Decimal(data["weight"]) if data.get("weight") else None
        band = Band(data["band"]) if data.get("band") else None
        if measure is Measure.TIME:
            return [SetValue(seconds=c) for c in counts]
        if measure is Measure.WEIGHT_REPS:
            if weight is None:
                raise AppError("INPUT-WEIGHT-FIRST")
            return [SetValue(reps=c, weight=weight) for c in counts]
        return [SetValue(reps=c, band=band if measure is Measure.BAND_REPS else None) for c in counts]

    @router.callback_query(WkCb.filter(F.a.in_({"same", "reps"})))
    async def quick_sets(query: CallbackQuery, callback_data: WkCb, bot: Bot, actor: Actor, state: FSMContext,
                         request_id: str | None) -> None:
        session = await guard(query, bot, actor, state)
        exercise, data = await chosen(state, actor)
        if session is None:
            return
        if exercise is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        if callback_data.a == "same":
            last = await workouts.last_sets(actor, exercise.public_id, before_session=session.public_id)
            sets = list(last[1]) if last else []
        else:
            try:
                sets = build_sets(exercise, data, parse_counts(callback_data.v or ""))
            except AppError as err:
                await query.answer(err.user_text()[:200], show_alert=True)
                return
        await screens.close_buttons(query)
        await save_sets(bot, query.from_user.id, actor, state, session, exercise, sets, request_id)

    @router.message(WorkoutText(WorkoutInput.sets))
    async def typed_sets(message: Message, bot: Bot, actor: Actor, state: FSMContext,
                         request_id: str | None) -> None:
        session = await current(state, actor)
        exercise, data = await chosen(state, actor)
        if session is None or exercise is None:
            raise AppError("UI-STALE")
        await workouts.touch(actor, session.public_id)
        text = (message.text or "").strip()
        measure = exercise.spec.measure
        if measure is Measure.WEIGHT_REPS and not _COUNTS.search(text):
            weight = parse_weight(text)  # одно число — это вес
            await show_exercise(bot, message.chat.id, actor, state, session, exercise, weight)
            return
        sets = build_sets(exercise, data, parse_counts(text, seconds=measure is Measure.TIME))
        await save_sets(bot, message.chat.id, actor, state, session, exercise, sets, request_id)

    @router.callback_query(WkCb.filter(F.a == "undo"))
    async def undo(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        session = await guard(query, bot, actor, state)
        if session is None:
            return
        await screens.close_buttons(query)
        updated = await workouts.undo_last(actor, session.public_id)
        assert updated is not None
        await show_session(bot, query.from_user.id, actor, state, updated, "Последнее упражнение убрано.")

    # --- «🏁 Завершить» ---
    @router.callback_query(WkCb.filter(F.a == "finish"))
    async def finish_ask(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        session = await guard(query, bot, actor, state)
        if session is None:
            return
        await screens.close_buttons(query)
        if not session.blocks:
            await workouts.finish(actor, session.public_id, None)
            await wctx(state).clear()
            await screens.home(bot, query.from_user.id, actor, "Тренировка без подходов не сохранена.")
            return
        await wctx(state).set_state(WorkoutInput.duration)
        token = await wtoken(state)
        elapsed = max(1, round((days.now() - session.started_at).total_seconds() / 60))
        rows = [[btn(actor, token, f"{m} мин", "dur", str(m)) for m in DURATIONS],
                [btn(actor, token, f"⏱ {elapsed} мин (по часам)", "dur", str(elapsed))],
                [btn(actor, token, "← К тренировке", "back")]]
        sent = await bot.send_message(query.from_user.id, "Сколько длилась тренировка? Кнопкой или числом минут.",
                                      reply_markup=inline(rows))
        await remember_screen(state, sent.message_id)

    async def finish(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, minutes: int) -> None:
        session = await current(state, actor)
        if session is None:
            raise AppError("UI-STALE")
        done = await workouts.finish(actor, session.public_id, minutes)
        assert done is not None
        await wctx(state).clear()
        week, goal = await week_progress(actor, done.day)
        lines = [f"{KIND_LABELS[done.kind]} {format_day(done.day)} — {done.duration_min} мин", *block_lines(done)]
        if done.tonnage:
            lines.append(f"Тоннаж: {kg(done.tonnage)}")
        lines.append(f"Тренировок за неделю: {week}/{goal}")
        markup = inline([[InlineKeyboardButton(text="Отменить", callback_data=SessionCb(
            o=actor.user_id, t=0, i=done.public_id, m=minute()).pack()),
            move_button(actor.user_id, KIND, done.public_id, minute())]])
        trail.result()  # экраны тренировки и вопросы уходят, итог остаётся
        body = html.escape("\n".join(lines)) + "\n" + await card(actor, done.day)
        await bot.send_message(chat_id, body, parse_mode="HTML", reply_markup=markup)

    @router.callback_query(WkCb.filter(F.a == "dur"))
    async def duration_button(query: CallbackQuery, callback_data: WkCb, bot: Bot, actor: Actor,
                              state: FSMContext) -> None:
        if await guard(query, bot, actor, state) is None:
            return
        await screens.close_buttons(query)
        await finish(bot, query.from_user.id, actor, state, int(callback_data.v or "60"))

    @router.message(WorkoutText(WorkoutInput.duration))
    async def duration_text(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        minutes = parse_number_in_range((message.text or "").removesuffix("мин").strip(), low=1, high=600,
                                        field="Длительность", unit="мин")
        await finish(bot, message.chat.id, actor, state, int(minutes))

    @router.callback_query(SessionCb.filter())
    async def undo_session(query: CallbackQuery, callback_data: SessionCb, bot: Bot, actor: Actor) -> None:
        if minute() - callback_data.m > 24 * 60:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        removed = await workouts.delete_session(actor, callback_data.i)
        if removed is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        await screens.close_buttons(query)
        if query.message is not None:
            trail.discard(query.message.message_id)
        trail.result()
        await bot.send_message(query.from_user.id, f"Тренировка {format_day(removed.day)} удалена.")

    # --- настройки (раздел 3.11) ---
    async def settings_screen(bot: Bot, chat_id: int, actor: Actor, message: Message | None = None) -> None:
        s = await workouts.settings(actor)
        bands = ", ".join(BAND_LABELS[b] for b in s.bands) or "не указаны"
        text = (f"🏋️ Тренировки\nТренировок в неделю: {s.weekly_goal}\nРезинки: {bands}\n"
                f"Показывать все упражнения: {'да' if s.show_all else 'нет — подбор по полу из профиля'}")
        rows = [[btn(actor, 0, f"{'✅ ' if n == s.weekly_goal else ''}{n}", "goal", str(n)) for n in (2, 3, 4, 5)],
                [btn(actor, 0, f"{'✅ ' if b in s.bands else ''}{BAND_LABELS[b]}", "sband", b.value) for b in Band],
                [btn(actor, 0, f"Все упражнения: {'да' if s.show_all else 'нет'}", "all")]]
        if message is not None:
            await message.edit_text(text, reply_markup=inline(rows))
            return
        await bot.send_message(chat_id, text, reply_markup=inline(rows))

    @router.callback_query(MenuCb.filter(F.k == SETTINGS_KEY))
    async def open_settings(query: CallbackQuery, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        await settings_screen(bot, query.from_user.id, actor)

    @router.callback_query(WkCb.filter(F.a.in_({"goal", "sband", "all"})))
    async def change_settings(query: CallbackQuery, callback_data: WkCb, bot: Bot, actor: Actor) -> None:
        s = await workouts.settings(actor)
        if callback_data.a == "goal":
            await workouts.update_settings(actor, weekly_goal=int(callback_data.v or "3"))
        elif callback_data.a == "sband":
            band = Band(callback_data.v or Band.MEDIUM.value)
            await workouts.update_settings(actor, bands=[b for b in s.bands if b is not band]
                                           if band in s.bands else [*s.bands, band])
        else:
            await workouts.update_settings(actor, show_all=not s.show_all)
        await query.answer("Сохранено")
        if isinstance(query.message, Message):
            await settings_screen(bot, query.from_user.id, actor, query.message)

    return nav, router
