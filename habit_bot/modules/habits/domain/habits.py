"""Свои привычки (раздел 3.6, 4.6): типы, шаблоны, выполнение за день, расписание и серии. Чистые функции.

Выполнение за день — сумма записей (для отметки — число отметок). Цель выполнена, если выполнение ≥ цели; без цели —
при любой записи. Серия — дни подряд по расписанию с выполненной целью, назад от сегодня: невыполненный сегодняшний
день серию не обрывает, дни не по расписанию и «Выходные» пропускаются.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from habit_bot.kernel.domain.formatting import format_number
from habit_bot.kernel.domain.parsing import parse_number_in_range

MAX_VALUE = Decimal(1_000_000)
MAX_QUICK = 4
STREAK_LOOKBACK = 400  # дней назад, дальше серию не считаем
WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


class Measure(StrEnum):
    CHECK = "check"        # отметка: +1 за нажатие
    AMOUNT = "amount"      # количество в своей единице, дробное допустимо
    DURATION = "duration"  # минуты


class Period(StrEnum):
    """За какой срок цель (правки 1.0.2): в день (с расписанием по дням недели), в неделю (с понедельника), в месяц."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"


PERIOD_GOAL = {Period.DAY: "в день", Period.WEEK: "в неделю", Period.MONTH: "в месяц"}
PERIOD_SHORT = {Period.DAY: "", Period.WEEK: "нед.", Period.MONTH: "мес."}


def period_bounds(day: date, period: Period) -> tuple[date, date]:
    """Неделя с понедельника или календарный месяц, в которые попадает день; для «в день» — сам день."""
    if period is Period.WEEK:
        start = day - timedelta(days=day.weekday())
        return start, start + timedelta(days=6)
    if period is Period.MONTH:
        start = day.replace(day=1)
        following = (start + timedelta(days=32)).replace(day=1)
        return start, following - timedelta(days=1)
    return day, day


def period_streak(today: date, period: Period, done: Callable[[date], bool]) -> int:
    """Серия недель или месяцев подряд с выполненной целью, назад от текущего; невыполненный текущий не обрывает."""
    count = 0
    start = period_bounds(today, period)[0]
    for _ in range(STREAK_LOOKBACK // 7):
        if done(start):
            count += 1
        elif start != period_bounds(today, period)[0]:
            break
        start = period_bounds(start - timedelta(days=1), period)[0]
    return count


def streak_word(n: int, period: Period) -> str:
    """«3 дня», «2 недели», «5 месяцев»."""
    if period is Period.WEEK:
        forms = ("неделя", "недели", "недель")
    elif period is Period.MONTH:
        forms = ("месяц", "месяца", "месяцев")
    else:
        return days_word(n)
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {forms[0]}"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} {forms[1]}"
    return f"{n} {forms[2]}"


MEASURE_LABELS = {Measure.CHECK: "Отметка", Measure.AMOUNT: "Количество", Measure.DURATION: "Длительность"}
DEFAULT_STEP = {Measure.CHECK: Decimal(1), Measure.AMOUNT: Decimal(1), Measure.DURATION: Decimal(10)}


@dataclass(frozen=True, slots=True)
class Template:
    key: str
    emoji: str
    name: str
    short: str
    measure: Measure
    unit: str
    goal: Decimal | None
    step: Decimal | None  # None — нажатие спрашивает число


# Раздел 3.6: шаблоны привычек.
TEMPLATES: tuple[Template, ...] = (
    Template("eyes", "👁", "Зарядка для глаз", "Глаза", Measure.CHECK, "", Decimal(3), Decimal(1)),
    Template("water", "💧", "Вода", "Вода", Measure.AMOUNT, "стак.", Decimal(8), Decimal(1)),
    Template("vitamins", "💊", "Витамины", "Витамины", Measure.CHECK, "", Decimal(1), Decimal(1)),
    Template("steps", "🚶", "Шаги", "Шаги", Measure.AMOUNT, "шагов", Decimal(10_000), None),
    Template("sleep", "😴", "Сон", "Сон", Measure.AMOUNT, "ч", Decimal(8), None),
    Template("reading", "📖", "Чтение", "Чтение", Measure.DURATION, "мин", Decimal(20), Decimal(10)),
    Template("no_sugar", "🍬", "Без сладкого", "Без сладкого", Measure.CHECK, "", Decimal(1), Decimal(1)),
)
TEMPLATE_BY_KEY = {t.key: t for t in TEMPLATES}
STARTER = ("eyes", "water", "vitamins")  # «Примеры привычек» из анкеты; «Глаза» — на главном экране
STARTER_ON_HOME = ("eyes",)


def unit_of(measure: Measure, unit: str) -> str:
    return "мин" if measure is Measure.DURATION else ("" if measure is Measure.CHECK else unit)


def parse_value(measure: Measure, text: str, field: str = "Значение") -> Decimal:
    """Число для записи или цели: дробное через точку или запятую; отметка — целым числом."""
    value = parse_number_in_range(text, low=Decimal("0.01"), high=MAX_VALUE, field=field, unit="")
    if measure is Measure.CHECK:
        value = value.to_integral_value()
    return value


def format_value(value: Decimal, measure: Measure, unit: str) -> str:
    """«1,5 стак.», «20 мин», «3»."""
    shown = unit_of(measure, unit)
    return f"{format_number(value)} {shown}".rstrip()


def progress_label(fact: Decimal, goal: Decimal | None) -> str:
    """«2/3»; без цели — сколько сделано («1,5»)."""
    return f"{format_number(fact)}/{format_number(goal)}" if goal is not None else format_number(fact)


def is_done(fact: Decimal, goal: Decimal | None) -> bool:
    return fact >= goal if goal is not None else fact > 0


def is_scheduled(weekdays: Sequence[int] | None, day: date) -> bool:
    """Расписание: ``None`` — каждый день, иначе номера дней недели (0 — понедельник)."""
    return weekdays is None or day.weekday() in weekdays


def schedule_label(weekdays: Sequence[int] | None, period: Period = Period.DAY) -> str:
    if period is not Period.DAY:
        return "в любые дни"
    if weekdays is None or len(set(weekdays)) == 7:
        return "каждый день"
    return ", ".join(WEEKDAYS[d] for d in sorted(set(weekdays))) or "ни одного дня"


def streak(today: date, done: Callable[[date], bool], scheduled: Callable[[date], bool],
           day_off: Callable[[date], bool]) -> int:
    """Серия дней по расписанию с выполненной целью, назад от сегодня (раздел 4.6)."""
    count = 0
    day = today
    for _ in range(STREAK_LOOKBACK):
        if scheduled(day) and not day_off(day):
            if done(day):
                count += 1
            elif day != today:
                break
        day -= timedelta(days=1)
    return count


def days_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} день"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} дня"
    return f"{n} дней"


def daily_totals(entries: Iterable[tuple[date, Decimal]]) -> dict[date, Decimal]:
    totals: dict[date, Decimal] = {}
    for day, value in entries:
        totals[day] = totals.get(day, Decimal(0)) + value
    return totals


def parse_quick(measure: Measure, text: str) -> list[Decimal]:
    """Быстрые значения строкой: «0,5 1 1,5 2» — до четырёх, по возрастанию, без повторов."""
    values = sorted({parse_value(measure, part) for part in text.replace(";", " ").split()})
    return values[:MAX_QUICK]
