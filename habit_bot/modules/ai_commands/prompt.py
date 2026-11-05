"""Запрос к модели (раздел 3.10, 7.2). Неизменная инструкция и схема — в начале, чтобы попадать в кэш провайдера.

В модель уходит только нужное для разбора: текст, даты, названия рецептов, продуктов, привычек и упражнений
пользователя и записи упомянутых дней. Имя, Telegram-ID и профиль (пол, возраст, вес, рост) не отправляются.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SYSTEM = """Ты разбираешь сообщение пользователя дневника привычек в список действий. Ничего не придумывай.
Ответ — только JSON: {"actions": [...], "question": null} или {"actions": [], "question": {"text": "...",
"options": ["...", "..."]}}, если неясно, о каком объекте речь (2–6 вариантов из списков контекста).

Даты — ГГГГ-ММ-ДД. «Сегодня», «вчера», «позавчера», дни недели считай от даты today из контекста. Сутки
начинаются в 04:00. Будущих дат не бывает. Числа — точкой: 4.5. Время — «мм:сс» или «ч:мм:сс».

Действия (поле type и поля):
- food.add: day, item (название из foods, если подходит; иначе как написал пользователь), quantity (порции,
  граммы или штуки — как единица продукта в foods), для блюда, которого нет в foods, — оценка kcal, protein, fat,
  carbs на всё количество и quantity 1; price — если назван.
- food.quantity: day, item, quantity, time (если записей несколько). food.delete: day, item, time.
- food.move: day, item, to_day, time.
- warmup.add: day, values — {короткое название упражнения из warmup: "значение"}; повторы числом, время "6:15".
- warmup.edit: day, number (какая зарядка в дне, 1 — первая), exercise, value.
- habit.mark: day, habit (название из habits), times. habit.value: day, habit, value — для количества.
- workout.set: day, exercise (из exercises), weight (кг, если есть), reps — список повторов по подходам
  («4×8» → [8,8,8,8]) или seconds — для упражнений на время.
- run.add: day, distance_km, time. day.off: day. weight.record: day, kg.
Заполнение (пользователь переносит свои данные):
- recipe.create: name, unit ("portion" | "100g" | "piece"), kcal, protein, fat, carbs, price, composition.
- habit.create: name, emoji, measure ("check" | "amount" | "duration"), unit, goal.
- goal.set: start_date, kcal, protein, fat, carbs. exercise_goal.set: exercise, value, date.
- warmup.set: exercises — [{name, measure ("reps" | "sec"), step}].
Уведомления, планы тренировок и всё, чего нет в списке, не выполняй — верни пустой список."""


@dataclass(frozen=True, slots=True)
class Context:
    """Что знает модель: даты, названия и записи упомянутых дней. Без имени, ID и профиля."""

    today: str
    now: str
    foods: list[str] = field(default_factory=list)
    habits: list[str] = field(default_factory=list)
    warmup: list[str] = field(default_factory=list)
    exercises: list[str] = field(default_factory=list)
    days: dict[str, dict[str, Any]] = field(default_factory=dict)

    def as_json(self) -> str:
        return json.dumps({"today": self.today, "now": self.now, "foods": self.foods, "habits": self.habits,
                           "warmup": self.warmup, "exercises": self.exercises, "days": self.days},
                          ensure_ascii=False)


def build_messages(context: Context, text: str, *, previous: str | None = None) -> list[dict[str, str]]:
    """``previous`` — прошлое понимание при «✏️ Исправить» или ответе на вопрос: разбор повторяется с его учётом."""
    user = f"Контекст: {context.as_json()}\n\nСообщение: {text}"
    if previous:
        user += f"\n\nРаньше понял так (исправь по сообщению): {previous}"
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
