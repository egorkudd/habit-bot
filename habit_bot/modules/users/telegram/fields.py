"""Поля анкеты и профиля в Telegram: подписи, кнопки и разбор ответов. Общие для анкеты и «Настроек»."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from habit_bot.channels.telegram.ui.layout import fit_rows, inline
from habit_bot.kernel.domain.formatting import format_date, format_day, format_number
from habit_bot.kernel.domain.parsing import parse_number_in_range
from habit_bot.kernel.identity import Actor
from habit_bot.modules.users.domain.city import BUTTON_CITIES, City
from habit_bot.modules.users.domain.kbju import Activity, Experience, GoalMode, Sex, Targets
from habit_bot.modules.users.domain.profile import HEIGHT_RANGE, WEIGHT_RANGE
from habit_bot.modules.users.dto import GoalView, ProfileView


class UCb(CallbackData, prefix="u"):
    """Кнопки модуля users: ``a`` — действие, ``v`` — значение."""

    o: int
    t: int
    a: str
    v: str | None = None  # пустое значение aiogram распаковывает как None

    @property
    def value(self) -> str:
        return self.v or ""


SEX_LABELS = {Sex.MALE: "Мужской", Sex.FEMALE: "Женский"}
ACTIVITY_LABELS = {
    Activity.MINIMAL: ("Минимальная", "сидячая работа, почти без спорта"),
    Activity.LIGHT: ("Лёгкая", "1–3 тренировки в неделю или много ходьбы"),
    Activity.MEDIUM: ("Средняя", "3–5 тренировок в неделю"),
    Activity.HIGH: ("Высокая", "6–7 тренировок в неделю"),
    Activity.VERY_HIGH: ("Очень высокая", "физическая работа + тренировки"),
}
MODE_LABELS = {GoalMode.GAIN: "Набор массы", GoalMode.MAINTAIN: "Поддержание", GoalMode.LOSS: "Снижение веса"}
EXPERIENCE_LABELS = {
    Experience.BEGINNER: "Новичок", Experience.INTERMEDIATE: "Средний", Experience.ADVANCED: "Продвинутый",
}
STARTER_KIT = {
    "food": "Базовые продукты",
    "warmup": "Зарядка по умолчанию",
    "gym_plan": "Шаблон плана для зала",
    "habits": "Примеры привычек",
}
OTHER_CITY = "other"


def button(actor: Actor, token: int, text: str, action: str, value: str = "") -> InlineKeyboardButton:
    data = UCb(o=actor.user_id, t=token, a=action, v=value or None).pack()
    return InlineKeyboardButton(text=text, callback_data=data)


def keyboard(rows: Sequence[Sequence[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return inline(rows)


def choice_rows(
    actor: Actor, token: int, options: dict[str, str], *, per_row: int = 2, action: str = "pick",
) -> list[list[InlineKeyboardButton]]:
    buttons = [button(actor, token, label, action, value) for value, label in options.items()]
    return fit_rows(buttons, per_row)


def city_options() -> dict[str, str]:
    options = {str(i): city.name for i, city in enumerate(BUTTON_CITIES)}
    options[OTHER_CITY] = "Другой"
    return options


def parse_height(text: str) -> Decimal:
    low, high = HEIGHT_RANGE
    return parse_number_in_range(text, low=low, high=high, field="Рост", unit="см")


def parse_weight(text: str) -> Decimal:
    low, high = WEIGHT_RANGE
    return parse_number_in_range(text, low=low, high=high, field="Вес", unit="кг")


def targets_line(values: Targets | GoalView) -> str:
    if isinstance(values, Targets):
        kcal, protein, fat, carbs = (Decimal(v) for v in values.as_tuple())
    else:
        kcal, protein, fat, carbs = values.values()
    n = format_number
    return f"{n(kcal)} ккал · Б {n(protein)} · Ж {n(fat)} · У {n(carbs)}"


def city_text(city: City | None) -> str:
    return city.label if city else "не указан"


def profile_card(view: ProfileView) -> str:
    target = f"{format_number(view.target_weight)} кг" if view.target_weight is not None else "не задан"
    activity, hint = ACTIVITY_LABELS[view.activity]
    return "\n".join([
        "👤 Профиль",
        f"Имя: {view.name}",
        f"Пол: {SEX_LABELS[view.sex]}",
        f"Дата рождения: {format_date(view.birth_date)} ({view.age} лет)",
        f"Рост: {format_number(view.height_cm)} см",
        f"Вес: {format_number(view.weight_kg)} кг",
        f"Активность: {activity} — {hint}",
        f"Цель: {MODE_LABELS[view.mode]}",
        f"Целевой вес: {target}",
        f"Опыт тренировок: {EXPERIENCE_LABELS[view.experience]}",
        f"Город: {city_text(view.city)}",
    ])


def goal_line(goal: GoalView, today: date) -> str:
    source = "расчёт" if goal.source == "calc" else "вручную"
    since = "сегодня" if goal.start_date == today else f"с {format_day(goal.start_date)}"
    return f"{since}: {targets_line(goal)} ({source})"
