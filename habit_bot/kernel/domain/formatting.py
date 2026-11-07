"""Как бот показывает числа, время и даты: «77,5», «5:45», «24.10» (раздел 3, «Бот показывает числа с запятой»)."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")


def format_number(value: Decimal | int | float) -> str:
    """До 2 знаков, запятая, без лишних нулей, разряды через пробел: 77.50 → «77,5», 2340 → «2 340»."""
    number = Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    sign = "−" if number < 0 else ""
    whole, _, fraction = f"{abs(number):f}".partition(".")
    fraction = fraction.rstrip("0")
    grouped = f"{int(whole):,}".replace(",", " ")
    return f"{sign}{grouped},{fraction}" if fraction else f"{sign}{grouped}"


def format_duration(seconds: int) -> str:
    """345 → «5:45», 3723 → «1:02:03»."""
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def format_day(day: date) -> str:
    """Дата на кнопках и в сообщениях: «24.10»."""
    return f"{day.day:02d}.{day.month:02d}"


def format_date(day: date) -> str:
    """Полная дата: «20.10.2026»."""
    return f"{format_day(day)}.{day.year}"


# Таблица КБЖУ в карточке дня (правки 1.0.2): моноширинные столбцы, целые числа без разрядов — влезает в телефон.
KBJU_HEADER = f"{'':<8}{'Ккал':>6}{'Б':>5}{'Ж':>5}{'У':>5}"


def _whole(value: Decimal | int | float) -> str:
    number = int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return f"−{abs(number)}" if number < 0 else str(number)


def kbju_row(title: str, kcal: Decimal | int | float, protein: Decimal | int | float, fat: Decimal | int | float,
             carbs: Decimal | int | float) -> str:
    """«Остаток   2478  134   71  321»."""
    return f"{title:<8}{_whole(kcal):>6}{_whole(protein):>5}{_whole(fat):>5}{_whole(carbs):>5}"
