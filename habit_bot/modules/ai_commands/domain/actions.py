"""Закрытый набор действий, которые может вернуть модель (раздел 3.10). Модель ничего не пишет в базу: бот разбирает
ответ по этой схеме, проверяет каждое действие и выполняет только после подтверждения.

Ответ модели — JSON ``{"actions": [...], "question": {"text": "...", "options": ["..."]} | null}``.
Каждое действие разбирается отдельно: непонятное отбрасывается, остальные остаются.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

MAX_ACTIONS = 50
MAX_TEXT = 1000       # обычная команда
MAX_FILL_TEXT = 4000  # режим заполнения (раздел 3.12), предел Telegram


class _Action(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


Positive = Annotated[Decimal, Field(gt=0, le=100_000)]
NonNegative = Annotated[Decimal, Field(ge=0, le=100_000)]


class FoodAdd(_Action):
    """Еда: своё блюдо по названию; незнакомое — с оценкой КБЖУ (``approx``)."""

    type: Literal["food.add"]
    day: date
    item: str = Field(min_length=1, max_length=64)
    quantity: Positive = Decimal(1)
    kcal: NonNegative | None = None
    protein: NonNegative | None = None
    fat: NonNegative | None = None
    carbs: NonNegative | None = None
    price: NonNegative | None = None


class FoodQuantity(_Action):
    type: Literal["food.quantity"]
    day: date
    item: str = Field(min_length=1, max_length=64)
    quantity: Positive
    time: str | None = None  # «09:12» — какая из записей, если их несколько


class FoodDelete(_Action):
    type: Literal["food.delete"]
    day: date
    item: str = Field(min_length=1, max_length=64)
    time: str | None = None


class FoodMove(_Action):
    type: Literal["food.move"]
    day: date
    item: str = Field(min_length=1, max_length=64)
    to_day: date
    time: str | None = None


class WarmupAdd(_Action):
    """Зарядка: значения по коротким названиям упражнений набора («Планка»: «6:15»)."""

    type: Literal["warmup.add"]
    day: date
    values: dict[str, str] = Field(min_length=1, max_length=20)


class WarmupEdit(_Action):
    type: Literal["warmup.edit"]
    day: date
    number: int = Field(default=1, ge=1, le=10)  # какая зарядка в дне
    exercise: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=16)


class HabitMark(_Action):
    type: Literal["habit.mark"]
    day: date
    habit: str = Field(min_length=1, max_length=64)
    times: int = Field(default=1, ge=1, le=50)


class HabitValue(_Action):
    type: Literal["habit.value"]
    day: date
    habit: str = Field(min_length=1, max_length=64)
    value: Positive


class WorkoutSet(_Action):
    """Тренировка: подходы упражнения из базы — вес и повторы или секунды по подходам."""

    type: Literal["workout.set"]
    day: date
    exercise: str = Field(min_length=1, max_length=64)
    weight: Annotated[Decimal, Field(gt=0, le=500)] | None = None
    reps: list[Annotated[int, Field(ge=1, le=200)]] | None = Field(default=None, max_length=12)
    seconds: list[Annotated[int, Field(ge=1, le=3600)]] | None = Field(default=None, max_length=12)


class RunAdd(_Action):
    type: Literal["run.add"]
    day: date
    distance_km: Annotated[Decimal, Field(gt=0, le=300)]
    time: str = Field(min_length=1, max_length=10)  # «28:40», «1:05:10», «28»


class DayOff(_Action):
    type: Literal["day.off"]
    day: date


class WeightRecord(_Action):
    type: Literal["weight.record"]
    day: date
    kg: Annotated[Decimal, Field(ge=30, le=300)]


class RecipeCreate(_Action):
    """Заполнение (раздел 3.12): свой рецепт или продукт."""

    type: Literal["recipe.create"]
    name: str = Field(min_length=1, max_length=64)
    unit: Literal["portion", "100g", "piece"] = "portion"
    kcal: NonNegative
    protein: NonNegative
    fat: NonNegative
    carbs: NonNegative
    price: NonNegative | None = None
    composition: str = Field(default="", max_length=500)


class HabitCreate(_Action):
    type: Literal["habit.create"]
    name: str = Field(min_length=1, max_length=64)
    emoji: str = Field(default="", max_length=8)
    measure: Literal["check", "amount", "duration"] = "check"
    unit: str = Field(default="", max_length=16)
    goal: Positive | None = None


class GoalSet(_Action):
    type: Literal["goal.set"]
    start_date: date
    kcal: Annotated[int, Field(ge=800, le=10_000)]
    protein: Annotated[int, Field(ge=0, le=1000)]
    fat: Annotated[int, Field(ge=0, le=1000)]
    carbs: Annotated[int, Field(ge=0, le=2000)]


class ExerciseGoalSet(_Action):
    type: Literal["exercise_goal.set"]
    exercise: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=16)
    date: date


class WarmupExercise(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    name: str = Field(min_length=1, max_length=64)
    measure: Literal["reps", "sec"] = "reps"
    step: Annotated[int, Field(ge=1, le=600)] | None = None


class WarmupSetDefine(_Action):
    """Набор зарядки: упражнения и шаги (добавляются к набору, существующие получают шаг)."""

    type: Literal["warmup.set"]
    exercises: list[WarmupExercise] = Field(min_length=1, max_length=20)


Action = Annotated[
    FoodAdd | FoodQuantity | FoodDelete | FoodMove | WarmupAdd | WarmupEdit | HabitMark | HabitValue | WorkoutSet
    | RunAdd | DayOff | WeightRecord | RecipeCreate | HabitCreate | GoalSet | ExerciseGoalSet | WarmupSetDefine,
    Field(discriminator="type"),
]
ACTION_TYPES = (
    "day.off", "exercise_goal.set", "food.add", "food.delete", "food.move", "food.quantity", "goal.set",
    "habit.create", "habit.mark", "habit.value", "recipe.create", "run.add", "warmup.add", "warmup.edit",
    "warmup.set", "weight.record", "workout.set",
)
_ADAPTER: TypeAdapter[Any] = TypeAdapter(Action)


class Question(BaseModel):
    """Неясность — вопрос с вариантами, бот показывает их кнопками («Какой творог?»)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    text: str = Field(min_length=1, max_length=200)
    options: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(min_length=2, max_length=6)


class ParsedReply(BaseModel):
    model_config = ConfigDict(frozen=True)

    actions: tuple[Any, ...] = ()
    question: Question | None = None
    dropped: int = 0  # действия, которые не прошли схему


class ReplyInvalid(Exception):
    """Ответ модели — не JSON нужного вида: один повтор, затем «попробуйте кнопками» (раздел 7.2)."""


def parse_reply(text: str) -> ParsedReply:
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise ReplyInvalid("не JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("actions", []), list):
        raise ReplyInvalid("нет списка actions")
    actions, dropped = [], 0
    for raw in payload.get("actions", [])[:MAX_ACTIONS]:
        try:
            actions.append(_ADAPTER.validate_python(raw))
        except ValidationError:
            dropped += 1
    question = None
    if payload.get("question"):
        try:
            question = Question.model_validate(payload["question"])
        except ValidationError:
            question = None
    return ParsedReply(actions=tuple(actions), question=question, dropped=dropped)
