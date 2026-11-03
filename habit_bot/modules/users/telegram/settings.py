"""«Настройки» (раздел 3.11): профиль с кнопкой на каждое поле и пересчётом КБЖУ, цели, удаление аккаунта."""

from __future__ import annotations

from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message, ReplyKeyboardRemove

from habit_bot.channels.telegram.dialogs.fsm import dialog_token, start_dialog
from habit_bot.channels.telegram.ui.callbacks import CancelCb, MenuCb
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.domain.formatting import format_date
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.identity import Actor
from habit_bot.modules.users.domain.city import BUTTON_CITIES, City
from habit_bot.modules.users.domain.kbju import (
    Activity,
    Experience,
    GoalMode,
    Sex,
    Targets,
    allowed_modes,
    check_manual_targets,
    check_target_weight,
)
from habit_bot.modules.users.domain.profile import parse_birth_date, parse_kbju_line, parse_name
from habit_bot.modules.users.telegram.fields import (
    ACTIVITY_LABELS,
    EXPERIENCE_LABELS,
    MODE_LABELS,
    OTHER_CITY,
    SEX_LABELS,
    UCb,
    button,
    choice_rows,
    city_options,
    goal_line,
    keyboard,
    parse_height,
    parse_weight,
    profile_card,
    targets_line,
)
from habit_bot.modules.users.telegram.onboarding import city_from_data, city_to_data, not_found_text
from habit_bot.modules.users.usecases import Profiles

SETTINGS_TITLE = "⚙️ Настройки"
SAVED = "Сохранено ✅"
DELETE_QUESTION = "Удалить аккаунт и все данные? Это нельзя отменить."
DELETED = "Аккаунт и все данные удалены. Чтобы начать заново, напишите /start."
SOON = {"home": "🏠 Главный экран — скоро: в части 4 плана.", "export": "📦 Экспорт — скоро: в части 10 плана."}
FIELDS: dict[str, str] = {
    "name": "Имя", "sex": "Пол", "birth": "Дата рождения", "height": "Рост", "weight": "Вес",
    "activity": "Активность", "mode": "Цель", "target": "Целевой вес", "experience": "Опыт", "city": "Город",
}
TEXT_PROMPTS = {
    "name": "Как к вам обращаться?",
    "birth": "Дата рождения — ДД.ММ.ГГГГ, например 15.03.2003.",
    "height": "Рост, см — например 178.",
    "weight": "Вес, кг — например 75 или 77,5.",
    "target": "Целевой вес, кг.",
}


class SettingsInput(StatesGroup):
    value = State()
    city_text = State()
    recalc = State()
    kbju = State()
    delete = State()


def settings_keyboard(actor: Actor) -> Any:
    return keyboard([
        [button(actor, 0, "👤 Профиль", "settings", "profile"), button(actor, 0, "🎯 Цели КБЖУ", "settings", "goals")],
        [button(actor, 0, "🏠 Главный экран", "soon", "home"), button(actor, 0, "📦 Экспорт", "soon", "export")],
        [button(actor, 0, "🗑 Удалить аккаунт", "settings", "delete")],
    ])


def profile_keyboard(actor: Actor) -> Any:
    buttons = [button(actor, 0, label, "edit", key) for key, label in FIELDS.items()]
    return keyboard([buttons[i: i + 2] for i in range(0, len(buttons), 2)])


def cancel_button(actor: Actor, token: int) -> InlineKeyboardButton:
    return InlineKeyboardButton(text="✕ Отмена", callback_data=CancelCb(o=actor.user_id, t=token).pack())


class SettingsFlow:
    def __init__(self, profiles: Profiles, screens: Screens) -> None:
        self.profiles = profiles
        self.screens = screens

    async def show_settings(self, bot: Bot, chat_id: int, actor: Actor) -> None:
        await bot.send_message(chat_id, SETTINGS_TITLE, reply_markup=settings_keyboard(actor))

    async def show_profile(self, bot: Bot, chat_id: int, actor: Actor, prefix: str = "") -> None:
        view = await self.profiles.profile(actor)
        if view is None:
            await self.screens.home(bot, chat_id, actor, "Профиль появится после анкеты. Напишите /start.")
            return
        text = f"{prefix}\n\n{profile_card(view)}" if prefix else profile_card(view)
        await bot.send_message(chat_id, text, reply_markup=profile_keyboard(actor))

    async def show_goals(self, bot: Bot, chat_id: int, actor: Actor, prefix: str = "") -> None:
        history = await self.profiles.goals(actor)
        today = self.profiles.today()
        lines = [goal_line(g, today) for g in history[:10]] or ["целей пока нет"]
        text = "🎯 Цели КБЖУ (новые сверху):\n" + "\n".join(f"• {line}" for line in lines)
        if prefix:
            text = f"{prefix}\n\n{text}"
        markup = keyboard([[button(actor, 0, "✏️ Ввести вручную", "goal", "manual"),
                            button(actor, 0, "🔄 Пересчитать по профилю", "goal", "calc")]])
        await bot.send_message(chat_id, text, reply_markup=markup)

    async def ask_field(self, bot: Bot, chat_id: int, actor: Actor, state: FSMContext, field: str) -> None:
        token = await start_dialog(state, SettingsInput.value)
        await state.update_data(field=field)
        view = await self.profiles.profile(actor)
        assert view is not None
        rows: list[list[InlineKeyboardButton]] = []
        if field in TEXT_PROMPTS:
            prompt = TEXT_PROMPTS[field]
        elif field == "sex":
            prompt = "Пол:"
            rows = choice_rows(actor, token, {s.value: lbl for s, lbl in SEX_LABELS.items()}, action="set")
        elif field == "activity":
            prompt = "Уровень активности:\n" + "\n".join(f"• {n} — {h}" for n, h in ACTIVITY_LABELS.values())
            rows = choice_rows(actor, token, {a.value: n for a, (n, _) in ACTIVITY_LABELS.items()}, action="set")
        elif field == "mode":
            modes = allowed_modes(view.weight_kg, view.height_cm)
            prompt, rows = "Цель:", choice_rows(actor, token, {m.value: MODE_LABELS[m] for m in modes}, per_row=1,
                                                action="set")
        elif field == "experience":
            prompt = "Опыт тренировок:"
            rows = choice_rows(actor, token, {e.value: lbl for e, lbl in EXPERIENCE_LABELS.items()}, per_row=3,
                               action="set")
        else:
            prompt, rows = "Город — для погоды по утрам:", choice_rows(actor, token, city_options(), action="set")
            rows.append([button(actor, token, "Убрать город", "set", "none")])
        rows.append([cancel_button(actor, token)])
        await bot.send_message(chat_id, prompt, reply_markup=keyboard(rows))

    async def save(self, bot: Bot, chat_id: int, actor: Actor, state: FSMContext, field: str, value: Any) -> None:
        names = {"birth": "birth_date", "height": "height_cm", "weight": "weight_kg", "target": "target_weight"}
        view, recalc = await self.profiles.update_profile(actor, **{names.get(field, field): value})
        if not recalc:
            await state.clear()
            await self.show_profile(bot, chat_id, actor, SAVED)
            return
        new = self.profiles.targets(view)
        current = await self.profiles.goal_on(actor, self.profiles.today())
        if current is not None and tuple(int(v) for v in current.values()) == new.as_tuple():
            await state.clear()
            await self.show_profile(bot, chat_id, actor, f"{SAVED} КБЖУ не изменились.")
            return
        await state.set_state(SettingsInput.recalc)
        await state.update_data(targets=list(new.as_tuple()))
        token = await dialog_token(state)
        now = f"\nСейчас: {targets_line(current)}" if current else ""
        warnings = "".join(f"\n⚠️ {w}" for w in new.warnings)
        await bot.send_message(
            chat_id, f"{SAVED}\nНовые КБЖУ: {targets_line(new)}{now}{warnings}",
            reply_markup=keyboard([[button(actor, token, "🔄 Пересчитать", "recalc", "yes"),
                                    button(actor, token, "Оставить как есть", "recalc", "no")]]),
        )


def build_settings_router(flow: SettingsFlow) -> Router:
    router = Router(name="users.settings")

    @router.callback_query(MenuCb.filter(F.k == "settings"))
    async def open_settings(query: CallbackQuery, bot: Bot, actor: Actor) -> None:
        await flow.screens.close_buttons(query)
        await flow.show_settings(bot, query.from_user.id, actor)

    @router.callback_query(UCb.filter(F.a == "soon"))
    async def soon(query: CallbackQuery, callback_data: UCb) -> None:
        await flow.screens.close_buttons(query, toast=SOON.get(callback_data.v, "Скоро"))

    @router.callback_query(UCb.filter(F.a == "settings"))
    async def section(query: CallbackQuery, callback_data: UCb, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await flow.screens.close_buttons(query)
        chat_id = query.from_user.id
        if callback_data.v == "profile":
            await flow.show_profile(bot, chat_id, actor)
        elif callback_data.v == "goals":
            await flow.show_goals(bot, chat_id, actor)
        else:
            token = await start_dialog(state, SettingsInput.delete)
            await bot.send_message(chat_id, DELETE_QUESTION, reply_markup=keyboard([[
                button(actor, token, "🗑 Да, удалить всё", "delete", "yes"), cancel_button(actor, token)]]))

    @router.callback_query(UCb.filter(F.a == "edit"))
    async def edit(query: CallbackQuery, callback_data: UCb, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await flow.screens.close_buttons(query)
        if callback_data.v in FIELDS:
            await flow.ask_field(bot, query.from_user.id, actor, state, callback_data.v)

    @router.message(StateFilter(SettingsInput.value), F.text)
    async def text_value(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        field = (await state.get_data()).get("field", "")
        text = message.text or ""
        today = flow.profiles.today()
        value: Any
        if field == "name":
            value = parse_name(text)
        elif field == "birth":
            value = parse_birth_date(text, today)
        elif field == "height":
            value = parse_height(text)
        elif field == "weight":
            value = parse_weight(text)
        elif field == "target":
            view = await flow.profiles.profile(actor)
            assert view is not None
            value = parse_weight(text)
            check_target_weight(view.mode, view.weight_kg, value)
        else:
            await message.answer("Выберите вариант кнопкой выше 👆")
            return
        await flow.save(bot, message.chat.id, actor, state, field, value)

    @router.callback_query(StateFilter(SettingsInput.value, SettingsInput.city_text), UCb.filter(F.a == "set"))
    async def set_value(query: CallbackQuery, callback_data: UCb, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await flow.screens.close_buttons(query)
        data = await state.get_data()
        field, raw, chat_id = data.get("field", ""), callback_data.v, query.from_user.id
        value: Any = None
        if field == "sex" and raw in {s.value for s in Sex}:
            value = Sex(raw)
        elif field == "activity" and raw in {a.value for a in Activity}:
            value = Activity(raw)
        elif field == "experience" and raw in {e.value for e in Experience}:
            value = Experience(raw)
        elif field == "mode" and raw in {m.value for m in GoalMode}:
            view = await flow.profiles.profile(actor)
            assert view is not None
            if raw not in allowed_modes(view.weight_kg, view.height_cm):
                return
            value = GoalMode(raw)
        elif field == "city" and raw == OTHER_CITY:
            await state.set_state(SettingsInput.city_text)
            token = await dialog_token(state)
            await bot.send_message(chat_id, "Напишите название города.",
                                   reply_markup=keyboard([[cancel_button(actor, token)]]))
            return
        elif field == "city" and raw == "none":
            value = None
        elif field == "city" and raw.isdigit() and int(raw) < len(BUTTON_CITIES):
            value = BUTTON_CITIES[int(raw)]
        elif field == "city" and raw.startswith("opt") and raw[3:].isdigit():
            options = data.get("options", [])
            index = int(raw[3:])
            if index >= len(options):
                return
            value = city_from_data(options[index])
        else:
            return
        await flow.save(bot, chat_id, actor, state, field, value)

    @router.message(StateFilter(SettingsInput.city_text), F.text)
    async def city_text(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        try:
            found = await flow.profiles.find_city(message.text or "")
        except AppError as err:  # CITY-SERVICE
            await message.answer(err.user_text())
            await flow.ask_field(bot, message.chat.id, actor, state, "city")
            return
        if found.city is not None:
            await flow.save(bot, message.chat.id, actor, state, "city", found.city)
            return
        choices: tuple[City, ...] = found.options or found.suggestions
        await state.update_data(options=[city_to_data(c) for c in choices])
        token = await dialog_token(state)
        rows = [[button(actor, token, c.label, "set", f"opt{i}")] for i, c in enumerate(choices)]
        rows.append([cancel_button(actor, token)])
        text = "Нашлось несколько — выберите:" if found.options else not_found_text(message.text or "", choices)
        await message.answer(text, reply_markup=keyboard(rows))

    @router.callback_query(StateFilter(SettingsInput.recalc), UCb.filter(F.a == "recalc"))
    async def recalc(query: CallbackQuery, callback_data: UCb, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await flow.screens.close_buttons(query)
        targets = Targets(*(int(v) for v in (await state.get_data())["targets"]))
        await state.clear()
        if callback_data.v == "yes":
            goal = await flow.profiles.set_goal(actor, targets, source="calc")
            await flow.show_goals(bot, query.from_user.id, actor,
                                  f"Новая цель с {format_date(goal.start_date)}: {targets_line(goal)}")
        else:
            await flow.show_profile(bot, query.from_user.id, actor, "КБЖУ оставлены как есть.")

    @router.callback_query(UCb.filter(F.a == "goal"))
    async def goal_action(query: CallbackQuery, callback_data: UCb, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await flow.screens.close_buttons(query)
        chat_id = query.from_user.id
        if callback_data.v == "calc":
            view = await flow.profiles.profile(actor)
            assert view is not None
            goal = await flow.profiles.set_goal(actor, flow.profiles.targets(view), source="calc")
            await flow.show_goals(bot, chat_id, actor, f"Новая цель с {format_date(goal.start_date)}: "
                                                       f"{targets_line(goal)}")
            return
        token = await start_dialog(state, SettingsInput.kbju)
        await bot.send_message(chat_id, "Напишите 4 числа: ккал, белки, жиры, углеводы — например 2800 160 80 360.",
                               reply_markup=keyboard([[cancel_button(actor, token)]]))

    @router.message(StateFilter(SettingsInput.kbju), F.text)
    async def manual_goal(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        kcal, protein, fat, carbs = parse_kbju_line(message.text or "")
        warnings = check_manual_targets(kcal, protein, fat, carbs)
        targets = Targets(*(int(v.to_integral_value()) for v in (kcal, protein, fat, carbs)))
        goal = await flow.profiles.set_goal(actor, targets, source="manual")
        await state.clear()
        notes = "".join(f"\n⚠️ {w}" for w in warnings)
        await flow.show_goals(bot, message.chat.id, actor,
                              f"Новая цель с {format_date(goal.start_date)}: {targets_line(goal)}{notes}")

    @router.callback_query(StateFilter(SettingsInput.delete), UCb.filter(F.a == "delete"))
    async def delete(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await flow.screens.close_buttons(query)
        await flow.profiles.delete_account(actor)
        await bot.send_message(query.from_user.id, DELETED, reply_markup=ReplyKeyboardRemove())

    return router

