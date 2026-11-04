"""Дни (раздел 3.7, 4.3): подписи «Вчера (24.10)», «23.10, пт», календарь месяца, давность даты."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from habit_bot.kernel.domain.formatting import format_day

WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
MONTHS = ("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь",
          "Декабрь")
QUICK_DAYS = 6
OLD_DAYS = 30  # дата старше — с подтверждением «Это 45 дней назад, всё верно?»


def day_label(day: date) -> str:
    """Заголовок карточки: «23.10, пт»."""
    return f"{format_day(day)}, {WEEKDAYS[day.weekday()]}"


def quick_days(today: date, count: int = QUICK_DAYS) -> list[tuple[str, date]]:
    """Кнопки экрана «Другой день»: «Вчера (24.10)», «Позавчера (23.10)», «Чт (22.10)»…"""
    result: list[tuple[str, date]] = []
    for back in range(1, count + 1):
        day = today - timedelta(days=back)
        name = {1: "Вчера", 2: "Позавчера"}.get(back) or WEEKDAYS[day.weekday()].capitalize()
        result.append((f"{name} ({format_day(day)})", day))
    return result


def days_ago(day: date, today: date) -> int:
    return (today - day).days


def needs_confirmation(day: date, today: date) -> bool:
    return days_ago(day, today) > OLD_DAYS


def month_title(year: int, month: int) -> str:
    return f"{MONTHS[month - 1]} {year}"


def month_weeks(year: int, month: int) -> list[list[date | None]]:
    """Недели месяца с понедельника; пустые клетки — None."""
    weeks: list[list[date | None]] = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month):
        weeks.append([d if d.month == month else None for d in week])
    return weeks


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def days_word(n: int) -> str:
    """«45 дней», «21 день», «32 дня»."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} дня"
    return f"{n} дней"
