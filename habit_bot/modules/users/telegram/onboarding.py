"""Анкета из 12 шагов (раздел 3.0): вопросы по одному, кнопками где можно, на каждом шаге «← Назад».

Анкета хранится в области ``onboarding`` и не сбрасывается по бездействию: прерванная продолжается с того же шага.
Пока анкета не пройдена, весь ввод относится к ней — роутер подключается раньше меню и отмены.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
    TelegramObject,
)

from habit_bot.channels.telegram.dialogs.fsm import context_for, dialog_token
from habit_bot.channels.telegram.dialogs.policy import ONBOARDING
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.domain.formatting import format_number
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.errors.catalog import user_message
from habit_bot.kernel.identity import Actor
from habit_bot.modules.users.domain.city import BUTTON_CITIES, City
from habit_bot.modules.users.domain.kbju import (
    Activity,
    Experience,
    GoalMode,
    Sex,
    Targets,
    allowed_modes,
    bmi,
    check_manual_targets,
    check_target_weight,
)
from habit_bot.modules.users.domain.profile import parse_birth_date, parse_kbju_line, parse_name
from habit_bot.modules.users.dto import ProfileData
from habit_bot.modules.users.telegram.fields import (
    ACTIVITY_LABELS,
    EXPERIENCE_LABELS,
    MODE_LABELS,
    OTHER_CITY,
    SEX_LABELS,
    STARTER_KIT,
    UCb,
    button,
    choice_rows,
    city_options,
    keyboard,
    parse_height,
    parse_weight,
    targets_line,
)
from habit_bot.modules.users.usecases import Profiles

TOTAL = 12
INTRO = (
    "Привет! Пара минут — и бот посчитает вашу норму КБЖУ.\n"
    "12 коротких вопросов, на каждом можно вернуться «← Назад». Прервётесь — продолжим с того же места."
)
RESUME = "Продолжим анкету с того же места."
ANSWER_ABOVE = "Анкету нельзя отменить, но можно прерваться — продолжим с того же шага. Ответьте на вопрос 👇"
OLD_BUTTON = "Эта кнопка от прошлого шага"
AFTER_TEXT = "Можно сразу внести свои рецепты, цели и последние результаты одним текстом:"
AI_SOON = "✍️ Заполнение с помощью ИИ появится в части 9 плана."
LATER_TEXT = "Хорошо. Главное меню внизу 👇"


class Onboarding(StatesGroup):
    name = State()
    sex = State()
    birth = State()
    height = State()
    weight = State()
    activity = State()
    mode = State()
    target = State()
    experience = State()
    city = State()
    city_text = State()
    city_pick = State()
    kbju = State()
    kbju_manual = State()
    kit = State()


ORDER: list[State] = [
    Onboarding.name, Onboarding.sex, Onboarding.birth, Onboarding.height, Onboarding.weight, Onboarding.activity,
    Onboarding.mode, Onboarding.target, Onboarding.experience, Onboarding.city, Onboarding.kbju, Onboarding.kit,
]
PARENT: dict[str, State] = {
    str(Onboarding.city_text.state): Onboarding.city,
    str(Onboarding.city_pick.state): Onboarding.city,
    str(Onboarding.kbju_manual.state): Onboarding.kbju,
}
LATER_FROM = 10  # шаги 10–12 можно пропустить кнопкой «Заполнить позже»


def step_number(state: str) -> int:
    parent = PARENT.get(state)
    target = parent.state if parent else state
    return next(i for i, s in enumerate(ORDER, start=1) if s.state == target)


def previous_state(state: str) -> State | None:
    if state in PARENT:
        return PARENT[state]
    index = step_number(state) - 1
    return ORDER[index - 1] if index > 0 else None


def city_to_data(city: City | None) -> dict[str, Any] | None:
    if city is None:
        return None
    return {"name": city.name, "region": city.region, "lat": city.latitude, "lon": city.longitude,
            "cc": city.country_code}


def city_from_data(data: dict[str, Any] | None) -> City | None:
    if not data:
        return None
    return City(data["name"], data["region"], data["lat"], data["lon"], data.get("cc", "RU"))


def not_found_text(text: str, suggestions: tuple[City, ...]) -> str:
    maybe = f"Может, {', '.join(c.name for c in suggestions)}? " if suggestions else ""
    return user_message("CITY-NOT-FOUND", {"value": text.strip(), "maybe": maybe})


def suggestion_keyboard(actor: Actor, token: int, suggestions: tuple[City, ...]) -> InlineKeyboardMarkup:
    rows = [[button(actor, token, c.name, "pick", str(i))] for i, c in enumerate(suggestions)]
    rows.append([button(actor, token, "Пропустить", "skip"), button(actor, token, "← Назад", "back")])
    return keyboard(rows)


def needs_onboarding(event: TelegramObject, actor: Actor | None = None, raw_state: str | None = None) -> bool:
    """Анкета не пройдена и ещё не начата (или её состояние потерялось)."""
    return bool(actor and actor.onboarding and not (raw_state or "").startswith("Onboarding:"))


class OnboardingFlow:
    def __init__(self, profiles: Profiles, screens: Screens) -> None:
        self.profiles = profiles
        self.screens = screens

    # --- данные анкеты ---
    @staticmethod
    def profile_data(data: dict[str, Any]) -> ProfileData:
        target = data.get("target")
        return ProfileData(
            name=data["name"], sex=Sex(data["sex"]), birth_date=date.fromisoformat(data["birth"]),
            height_cm=Decimal(data["height"]), weight_kg=Decimal(data["weight"]),
            activity=Activity(data["activity"]), mode=GoalMode(data["mode"]),
            target_weight=Decimal(target) if target else None, experience=Experience(data["experience"]),
            city=city_from_data(data.get("city")),
        )

    def calculated(self, data: dict[str, Any]) -> Targets:
        return self.profiles.targets(self.profile_data(data))

    # --- вопросы ---
    async def ask(self, bot: Bot, chat_id: int, actor: Actor, state: FSMContext) -> None:
        current = await state.get_state() or Onboarding.name.state
        data = await state.get_data()
        token = await dialog_token(state)
        step = step_number(current)
        text, rows = self.question(current, data, actor, token)
        nav: list[InlineKeyboardButton] = []
        if step > 1:
            nav.append(button(actor, token, "← Назад", "back"))
        if step >= LATER_FROM and current != Onboarding.kbju_manual.state:
            nav.append(button(actor, token, "Заполнить позже", "later"))
        await bot.send_message(chat_id, f"Шаг {step}/{TOTAL}. {text}", reply_markup=keyboard([*rows, nav]))

    def question(
        self, current: str, data: dict[str, Any], actor: Actor, token: int,
    ) -> tuple[str, list[list[InlineKeyboardButton]]]:
        def pick(options: dict[str, str], per_row: int = 2) -> list[list[InlineKeyboardButton]]:
            return choice_rows(actor, token, options, per_row=per_row)

        if current == Onboarding.name.state:
            tg_name = data.get("tg_name") or ""
            rows = [[button(actor, token, tg_name, "pick", "tg")]] if tg_name else []
            return "Как к вам обращаться? Напишите имя или нажмите кнопку.", rows
        if current == Onboarding.sex.state:
            return "Пол:", pick({s.value: label for s, label in SEX_LABELS.items()})
        if current == Onboarding.birth.state:
            return "Дата рождения — ДД.ММ.ГГГГ, например 15.03.2003.", []
        if current == Onboarding.height.state:
            return "Рост, см — например 178.", []
        if current == Onboarding.weight.state:
            return "Текущий вес, кг — например 75 или 77,5.", []
        if current == Onboarding.activity.state:
            lines = "\n".join(f"• {name} — {hint}" for name, hint in ACTIVITY_LABELS.values())
            options = {a.value: name for a, (name, _) in ACTIVITY_LABELS.items()}
            return f"Уровень активности:\n{lines}", pick(options)
        if current == Onboarding.mode.state:
            weight, height = Decimal(data["weight"]), Decimal(data["height"])
            modes = allowed_modes(weight, height)
            note = "" if GoalMode.LOSS in modes else (
                f"\nСнижение веса недоступно: ИМТ {format_number(bmi(weight, height))} ниже 18,5.")
            return f"Цель:{note}", pick({m.value: MODE_LABELS[m] for m in modes}, per_row=1)
        if current == Onboarding.target.state:
            return "Целевой вес, кг — или «Пропустить».", [[button(actor, token, "Пропустить", "skip")]]
        if current == Onboarding.experience.state:
            return "Опыт тренировок:", pick({e.value: label for e, label in EXPERIENCE_LABELS.items()}, per_row=3)
        if current == Onboarding.city.state:
            rows = pick(city_options())
            rows.append([button(actor, token, "Пропустить", "skip")])
            return "Город — для погоды по утрам:", rows
        if current == Onboarding.city_text.state:
            return "Напишите название города.", []
        if current == Onboarding.city_pick.state:
            options = {str(i): City(**_city_kwargs(c)).label for i, c in enumerate(data.get("options", []))}
            return "Нашлось несколько — выберите:", pick(options, per_row=1)
        if current == Onboarding.kbju.state:
            targets = self.calculated(data)
            warnings = "".join(f"\n⚠️ {w}" for w in targets.warnings)
            rows = [[button(actor, token, "✅ Принять", "accept"),
                     button(actor, token, "✏️ Изменить вручную", "manual")]]
            return f"Ваша норма в день:\n{targets_line(targets)}{warnings}", rows
        if current == Onboarding.kbju_manual.state:
            return "Напишите 4 числа: ккал, белки, жиры, углеводы — например 2800 160 80 360.", []
        chosen = set(data.get("kit", []))
        options = {key: f"{'☑' if key in chosen else '☐'} {label}" for key, label in STARTER_KIT.items()}
        rows = choice_rows(actor, token, options, per_row=1, action="kit")
        rows.append([button(actor, token, "Готово", "done")])
        return "Стартовый набор — отметьте, что добавить (можно ничего):", rows

    # --- переходы ---
    async def go(self, bot: Bot, chat_id: int, actor: Actor, state: FSMContext, target: State, **data: Any) -> None:
        if data:
            await state.update_data(**data)
        await state.set_state(target)
        await self.ask(bot, chat_id, actor, state)

    async def begin(self, bot: Bot, chat_id: int, actor: Actor, state: FSMContext, tg_name: str) -> None:
        onboarding = context_for(state, ONBOARDING)
        await onboarding.clear()
        await onboarding.set_data({"tg_name": tg_name[:32]})
        await onboarding.set_state(Onboarding.name)
        await bot.send_message(chat_id, INTRO, reply_markup=ReplyKeyboardRemove())
        await self.ask(bot, chat_id, actor, onboarding)

    async def finish(
        self, bot: Bot, chat_id: int, actor: Actor, state: FSMContext, *, use_calculated: bool = False,
    ) -> None:
        data = await state.get_data()
        profile = self.profile_data(data)
        if use_calculated or "kbju" not in data:
            targets, source = self.profiles.targets(profile), "calc"
        else:
            kcal, protein, fat, carbs = (int(Decimal(v)) for v in data["kbju"])
            targets, source = Targets(kcal, protein, fat, carbs), data.get("source", "calc")
        kit = [] if use_calculated else list(data.get("kit", []))
        goal = await self.profiles.complete_onboarding(actor, profile, targets=targets, source=source, starter_kit=kit)
        await state.clear()
        await self.screens.home(bot, chat_id, actor, f"Готово, {profile.name}! Норма с сегодняшнего дня:\n"
                                                     f"{targets_line(goal)}")
        after = keyboard([[button(actor, 0, "✍️ Заполнить с помощью ИИ", "after", "ai"),
                           button(actor, 0, "Позже", "after", "later")]])
        await bot.send_message(chat_id, AFTER_TEXT, reply_markup=after)


def _city_kwargs(data: dict[str, Any]) -> dict[str, Any]:
    return {"name": data["name"], "region": data["region"], "latitude": data["lat"], "longitude": data["lon"],
            "country_code": data.get("cc", "RU")}


def build_onboarding_router(flow: OnboardingFlow) -> Router:
    router = Router(name="users.onboarding")
    in_onboarding = StateFilter(*Onboarding.__all_states__)

    def chat_of(event: Message | CallbackQuery) -> int:
        return event.chat.id if isinstance(event, Message) else event.from_user.id

    # --- начало и продолжение ---
    @router.message(needs_onboarding)
    async def begin_by_message(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        name = message.from_user.first_name if message.from_user else ""
        await flow.begin(bot, message.chat.id, actor, state, name)

    @router.callback_query(needs_onboarding)
    async def begin_by_button(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await flow.screens.close_buttons(query)
        await flow.begin(bot, query.from_user.id, actor, state, query.from_user.first_name)

    # --- ответы текстом ---
    @router.message(StateFilter(Onboarding.name), F.text)
    async def name_text(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await flow.go(bot, message.chat.id, actor, state, Onboarding.sex, name=parse_name(message.text or ""))

    @router.message(StateFilter(Onboarding.birth), F.text)
    async def birth_text(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        birth = parse_birth_date(message.text or "", flow.profiles.today())
        await flow.go(bot, message.chat.id, actor, state, Onboarding.height, birth=birth.isoformat())

    @router.message(StateFilter(Onboarding.height), F.text)
    async def height_text(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        height = parse_height(message.text or "")
        await flow.go(bot, message.chat.id, actor, state, Onboarding.weight, height=str(height))

    @router.message(StateFilter(Onboarding.weight), F.text)
    async def weight_text(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        weight = parse_weight(message.text or "")
        await flow.go(bot, message.chat.id, actor, state, Onboarding.activity, weight=str(weight))

    @router.message(StateFilter(Onboarding.target), F.text)
    async def target_text(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        data = await state.get_data()
        target = parse_weight(message.text or "")
        check_target_weight(GoalMode(data["mode"]), Decimal(data["weight"]), target)
        await flow.go(bot, message.chat.id, actor, state, Onboarding.experience, target=str(target))

    @router.message(StateFilter(Onboarding.city_text), F.text)
    async def city_text(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await choose_city(message.chat.id, bot, actor, state, message.text or "")

    @router.message(StateFilter(Onboarding.kbju_manual), F.text)
    async def kbju_text(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        kcal, protein, fat, carbs = parse_kbju_line(message.text or "")
        warnings = check_manual_targets(kcal, protein, fat, carbs)
        for warning in warnings:
            await message.answer(f"⚠️ {warning}")
        await flow.go(bot, message.chat.id, actor, state, Onboarding.kit,
                      kbju=[str(kcal), str(protein), str(fat), str(carbs)], source="manual")

    async def choose_city(chat_id: int, bot: Bot, actor: Actor, state: FSMContext, text: str) -> None:
        try:
            found = await flow.profiles.find_city(text)
        except AppError as err:  # CITY-SERVICE: сервис не ответил — снова кнопки городов
            await bot.send_message(chat_id, err.user_text())
            await flow.go(bot, chat_id, actor, state, Onboarding.city)
            return
        if found.city is not None:
            await flow.go(bot, chat_id, actor, state, Onboarding.kbju, city=city_to_data(found.city))
            return
        if found.options:
            await flow.go(bot, chat_id, actor, state, Onboarding.city_pick,
                          options=[city_to_data(c) for c in found.options])
            return
        await state.update_data(options=[city_to_data(c) for c in found.suggestions])
        await bot.send_message(chat_id, not_found_text(text, found.suggestions),
                               reply_markup=suggestion_keyboard(actor, await dialog_token(state), found.suggestions))

    # --- ответы кнопками ---
    @router.callback_query(in_onboarding, UCb.filter(F.a == "pick"))
    async def picked(query: CallbackQuery, callback_data: UCb, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await flow.screens.close_buttons(query)
        current = await state.get_state()
        value = callback_data.v
        chat_id = query.from_user.id
        data = await state.get_data()
        if current == Onboarding.name.state and value == "tg" and data.get("tg_name"):
            await flow.go(bot, chat_id, actor, state, Onboarding.sex, name=parse_name(data["tg_name"]))
        elif current == Onboarding.sex.state and value in {s.value for s in Sex}:
            await flow.go(bot, chat_id, actor, state, Onboarding.birth, sex=value)
        elif current == Onboarding.activity.state and value in {a.value for a in Activity}:
            await flow.go(bot, chat_id, actor, state, Onboarding.mode, activity=value)
        elif current == Onboarding.mode.state and value in allowed_modes(Decimal(data["weight"]),
                                                                            Decimal(data["height"])):
            await flow.go(bot, chat_id, actor, state, Onboarding.target, mode=value, target=None)
        elif current == Onboarding.experience.state and value in {e.value for e in Experience}:
            await flow.go(bot, chat_id, actor, state, Onboarding.city, experience=value)
        elif current == Onboarding.city.state and value == OTHER_CITY:
            await flow.go(bot, chat_id, actor, state, Onboarding.city_text)
        elif current == Onboarding.city.state and value.isdigit() and int(value) < len(BUTTON_CITIES):
            city = BUTTON_CITIES[int(value)]
            await flow.go(bot, chat_id, actor, state, Onboarding.kbju, city=city_to_data(city))
        elif current in (Onboarding.city_pick.state, Onboarding.city_text.state) and value.isdigit() \
                and int(value) < len(data.get("options", [])):
            await flow.go(bot, chat_id, actor, state, Onboarding.kbju, city=data["options"][int(value)])
        else:
            await flow.ask(bot, chat_id, actor, state)

    @router.callback_query(in_onboarding, UCb.filter(F.a == "back"))
    async def back(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await flow.screens.close_buttons(query)
        previous = previous_state(await state.get_state() or "")
        if previous is not None:
            await state.set_state(previous)
        await flow.ask(bot, query.from_user.id, actor, state)

    @router.callback_query(StateFilter(Onboarding.target, Onboarding.city, Onboarding.city_text,
                                       Onboarding.city_pick), UCb.filter(F.a == "skip"))
    async def skip(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await flow.screens.close_buttons(query)
        if await state.get_state() == Onboarding.target.state:
            await flow.go(bot, query.from_user.id, actor, state, Onboarding.experience, target=None)
        else:
            await flow.go(bot, query.from_user.id, actor, state, Onboarding.kbju, city=None)

    @router.callback_query(StateFilter(Onboarding.kbju), UCb.filter(F.a.in_({"accept", "manual"})))
    async def kbju_choice(query: CallbackQuery, callback_data: UCb, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await flow.screens.close_buttons(query)
        if callback_data.a == "manual":
            await flow.go(bot, query.from_user.id, actor, state, Onboarding.kbju_manual)
            return
        targets = flow.calculated(await state.get_data())
        await flow.go(bot, query.from_user.id, actor, state, Onboarding.kit,
                      kbju=[str(v) for v in targets.as_tuple()], source="calc")

    @router.callback_query(StateFilter(Onboarding.kit), UCb.filter(F.a == "kit"))
    async def toggle_kit(query: CallbackQuery, callback_data: UCb, actor: Actor, state: FSMContext) -> None:
        chosen = set((await state.get_data()).get("kit", []))
        if callback_data.v in STARTER_KIT:
            chosen ^= {callback_data.v}
        await state.update_data(kit=[k for k in STARTER_KIT if k in chosen])
        await query.answer()
        if isinstance(query.message, Message):
            token = await dialog_token(state)
            _, rows = flow.question(str(Onboarding.kit.state), await state.get_data(), actor, token)
            nav = [button(actor, token, "← Назад", "back"), button(actor, token, "Заполнить позже", "later")]
            await query.message.edit_reply_markup(reply_markup=keyboard([*rows, nav]))

    @router.callback_query(StateFilter(Onboarding.kit), UCb.filter(F.a == "done"))
    async def done(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await flow.screens.close_buttons(query)
        await flow.finish(bot, query.from_user.id, actor, state)

    @router.callback_query(in_onboarding, UCb.filter(F.a == "later"))
    async def later(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await flow.screens.close_buttons(query)
        if step_number(await state.get_state() or "") < LATER_FROM:
            await flow.ask(bot, query.from_user.id, actor, state)
            return
        if step_number(await state.get_state() or "") == LATER_FROM:
            await state.update_data(city=None)  # раздел 3.0: при «Заполнить позже» на шаге города он остаётся пустым
        await flow.finish(bot, query.from_user.id, actor, state, use_calculated=True)

    # --- после анкеты ---
    @router.callback_query(UCb.filter(F.a == "after"))
    async def after(query: CallbackQuery, callback_data: UCb, bot: Bot, actor: Actor) -> None:
        if callback_data.v == "ai":
            await flow.screens.close_buttons(query, toast=AI_SOON)
            return
        await flow.screens.close_buttons(query)
        await flow.screens.home(bot, query.from_user.id, actor, LATER_TEXT)

    # --- всё остальное во время анкеты: напомнить вопрос ---
    @router.message(in_onboarding, CommandStart())
    async def resume(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await message.answer(RESUME)
        await flow.ask(bot, message.chat.id, actor, state)

    @router.message(in_onboarding)
    async def other_message(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await message.answer(ANSWER_ABOVE)
        await flow.ask(bot, message.chat.id, actor, state)

    @router.callback_query(in_onboarding)
    async def other_button(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await flow.screens.close_buttons(query, toast=OLD_BUTTON)
        await flow.ask(bot, chat_of(query), actor, state)

    return router
