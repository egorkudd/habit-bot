"""Зарядка (раздел 3.3, 4.5): значения упражнений, шаги, номер в дне, личные цели и темп.

Повторы — целое число, время — секунды («5:45» = 345). «+шаг» прибавляет шаг к черновику; шаг по умолчанию:
время — 15 сек, повторы — 5. Нужный темп = (цель − лучший результат) / дни до даты; фактический — за 14 дней;
контрольная линия — от результата на дату постановки до цели; отставание больше 5% от цели — предупреждение.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from habit_bot.kernel.domain.formatting import format_duration, format_number
from habit_bot.kernel.domain.parsing import parse_duration, parse_number_in_range
from habit_bot.kernel.errors import AppError

PACE_DAYS = 14
BEHIND_SHARE = Decimal("0.05")
MAX_REPS = 10_000
MAX_SECONDS = 4 * 3600


class Measure(StrEnum):
    REPS = "reps"
    SECONDS = "sec"


DEFAULT_STEP = {Measure.REPS: 5, Measure.SECONDS: 15}


@dataclass(frozen=True, slots=True)
class DefaultExercise:
    name: str
    short: str
    measure: Measure


# Раздел 3.3 и 6.1: отжимания (+5), ягодичный мостик (+5), планка (+15 сек), спина (+5).
DEFAULT_SET: tuple[DefaultExercise, ...] = (
    DefaultExercise("Отжимания", "Отжимания", Measure.REPS),
    DefaultExercise("Ягодичный мостик", "Мостик", Measure.REPS),
    DefaultExercise("Планка", "Планка", Measure.SECONDS),
    DefaultExercise("Спина", "Спина", Measure.REPS),
)


def format_value(measure: Measure, value: int) -> str:
    """50 повторов → «50», 345 секунд → «5:45»."""
    return format_duration(value) if measure is Measure.SECONDS else str(value)


def format_step(measure: Measure, step: int) -> str:
    """Подпись шага на кнопке: «+5», «+15 сек», «+1:00»."""
    if measure is Measure.SECONDS:
        return f"+{step} сек" if step < 60 else f"+{format_duration(step)}"
    return f"+{step}"


def parse_value(measure: Measure, text: str, field: str = "Значение") -> int:
    """Повторы — целым числом; время — «5:45», «5.45» или секунды."""
    if measure is Measure.SECONDS:
        seconds = parse_duration(text)
        if seconds > MAX_SECONDS:
            raise AppError("INPUT-TIME", value=text.strip(), plain="в секундах: 345")
        return seconds
    value = parse_number_in_range(text, low=0, high=MAX_REPS, field=field, unit="")
    if value != value.to_integral_value():
        raise AppError("INPUT-NUMBER", value=text.strip())
    return int(value)


def format_minus_step(measure: Measure, step: int) -> str:
    """«−5», «−15 сек», «−1:00» — подпись кнопки «убавить»."""
    return "−" + format_step(measure, step)[1:]


EXAMPLE_VALUE = {Measure.REPS: "20", Measure.SECONDS: "1:00"}


def values_example(measures: Sequence[Measure], values: Sequence[int] | None = None) -> str:
    """Пример строки со всеми значениями по порядку: «50 50 5:45 25»; без значений — «20 20 1:00 20»."""
    if values is not None and any(values):
        return " ".join(format_value(m, v) for m, v in zip(measures, values, strict=True))
    return " ".join(EXAMPLE_VALUE[m] for m in measures)


def parse_values_line(exercises: Sequence[tuple[str, Measure]], text: str) -> list[int]:
    """Все значения зарядки одной строкой по порядку набора: «55 50 6:15 25»."""
    parts = text.split()
    example = values_example([m for _, m in exercises])
    if len(parts) < len(exercises):
        missing = ", ".join(name for name, _ in exercises[len(parts):])
        raise AppError("INPUT-WARMUP-LINE", problem=f"Не хватает: {missing}", count=len(exercises), example=example)
    if len(parts) > len(exercises):
        raise AppError("INPUT-WARMUP-LINE", problem=f"Лишнее значение: {parts[len(exercises)]}",
                       count=len(exercises), example=example)
    return [parse_value(measure, part, name) for (name, measure), part in zip(exercises, parts, strict=True)]


def parse_step(measure: Measure, text: str) -> int:
    step = parse_value(measure, text, "Шаг")
    if step <= 0:
        raise AppError("INPUT-RANGE", field="Шаг", low=1, high=format_number(MAX_REPS), unit="", value=text.strip(),
                       guess="")
    return step


def apply_step(value: int, step: int, direction: int = 1) -> int:
    """«+шаг» / «−шаг»; значение не уходит ниже нуля."""
    return max(0, value + direction * step)


def next_number(numbers_in_day: Iterable[int]) -> int:
    """Номер зарядки в дне: 1-я, 2-я… — следующий после уже записанных."""
    return max(numbers_in_day, default=0) + 1


def ordinal(number: int) -> str:
    return f"{number}-я"


@dataclass(frozen=True, slots=True)
class GoalProgress:
    best: int
    target: int
    left: int
    days_left: int
    needed_per_day: Decimal
    actual_per_day: Decimal
    expected_today: int
    achieved: bool
    behind: bool


def goal_progress(
    *, target: int, target_date: date, start_value: int, set_on: date, today: date, best: int, best_before_window: int,
) -> GoalProgress:
    """Строка прогресса личной цели (раздел 4.5).

    ``best_before_window`` — лучший результат на дату 14 дней назад: по нему считается фактический темп.
    """
    days_left = max((target_date - today).days, 1)
    left = max(target - best, 0)
    needed = (Decimal(left) / days_left).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    actual = (Decimal(best - best_before_window) / PACE_DAYS).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    total = max((target_date - set_on).days, 1)
    elapsed = min(max((today - set_on).days, 0), total)
    expected = start_value + (target - start_value) * elapsed / total
    behind = best < target and expected - best > target * BEHIND_SHARE
    return GoalProgress(best, target, left, days_left, needed, actual, round(expected), best >= target, behind)


def progress_line(name: str, measure: Measure, progress: GoalProgress, target_date: date) -> str:
    """«🎯 Планка: лучший 6:00 · цель 11:00 к 03.12 · осталось 5:00 · нужно +10 сек/день · за 14 дней +2 сек/день»."""

    def value(v: int) -> str:
        return format_value(measure, v)

    if progress.achieved:
        return f"🎯 {name}: цель {value(progress.target)} достигнута — лучший {value(progress.best)}"
    unit = " сек/день" if measure is Measure.SECONDS else "/день"
    line = (f"🎯 {name}: лучший {value(progress.best)} · цель {value(progress.target)} к "
            f"{target_date.day:02d}.{target_date.month:02d} · осталось {value(progress.left)} · "
            f"нужно +{format_number(progress.needed_per_day)}{unit} · "
            f"за 14 дней {'+' if progress.actual_per_day >= 0 else ''}{format_number(progress.actual_per_day)}{unit}")
    if progress.behind:
        line += f" · ⚠️ отставание: по плану сейчас {value(progress.expected_today)}"
    return line
