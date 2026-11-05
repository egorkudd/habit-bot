"""Периоды обзора (раздел 3.8.2): неделя с понедельника, календарный месяц, 3 календарных месяца;
«◀ / ▶» сдвигают период целиком."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from habit_bot.kernel.domain.formatting import format_day

MONTHS = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь",
          "декабрь")
WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


class Kind(StrEnum):
    WEEK = "w"
    MONTH = "m"
    QUARTER = "q"


LABELS = {Kind.WEEK: "Неделя", Kind.MONTH: "Месяц", Kind.QUARTER: "3 месяца"}


@dataclass(frozen=True, slots=True)
class Period:
    kind: Kind
    start: date
    end: date
    shift: int

    @property
    def days(self) -> tuple[date, ...]:
        return tuple(self.start + timedelta(days=i) for i in range((self.end - self.start).days + 1))

    @property
    def title(self) -> str:
        if self.kind is Kind.WEEK:
            return f"Неделя · {format_day(self.start)}–{format_day(self.end)}"
        if self.kind is Kind.MONTH:
            return f"Месяц · {MONTHS[self.start.month - 1]} {self.start.year}"
        years = f"{self.start.year}" if self.start.year == self.end.year else f"{self.start.year}–{self.end.year}"
        return f"3 месяца · {MONTHS[self.start.month - 1]}–{MONTHS[self.end.month - 1]} {years}"


def _month_start(day: date, shift: int) -> date:
    index = day.year * 12 + day.month - 1 + shift
    return date(index // 12, index % 12 + 1, 1)


def _month_end(start: date) -> date:
    return _month_start(start, 1) - timedelta(days=1)


def period(kind: Kind, today: date, shift: int = 0) -> Period:
    """Период, в который входит ``today``, сдвинутый на ``shift`` периодов (−1 — прошлый). Будущее не листается."""
    shift = min(shift, 0)
    if kind is Kind.WEEK:
        start = today - timedelta(days=today.weekday()) + timedelta(weeks=shift)
        return Period(kind, start, start + timedelta(days=6), shift)
    if kind is Kind.MONTH:
        start = _month_start(today, shift)
        return Period(kind, start, _month_end(start), shift)
    last = _month_start(today, 3 * shift)
    return Period(kind, _month_start(last, -2), _month_end(last), shift)


def day_title(day: date) -> str:
    """«22.10 (чт)»."""
    return f"{format_day(day)} ({WEEKDAYS[day.weekday()]})"


def word(n: int, one: str, few: str, many: str) -> str:
    """1 блюдо, 3 блюда, 5 блюд."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many
