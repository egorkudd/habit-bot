"""Разбор ввода пользователя (раздел 3, «Ввод чисел»; раздел 7.4.1). Одна общая функция на весь бот.

Чистые функции: без базы, сети и Telegram. Ошибка ввода — ``AppError`` с кодом ``INPUT-*``,
канал показывает текст из каталога, а диалог при этом не сбрасывается.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, tzinfo
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from habit_bot.kernel.domain.formatting import format_day, format_number
from habit_bot.kernel.errors import AppError

MAX_NUMBER_LENGTH = 15
DAY_BOUNDARY_HOUR = 4  # раздел 4.3: записи с 00:00 до 03:59 относятся к предыдущему дню
HALF_YEAR = timedelta(days=183)

_NUMBER = re.compile(r"^\+?(\d+)(?:[.,](\d+))?$")
_MIN_SEC = re.compile(r"^(\d{1,3})[:.,](\d{2})$")
_HOUR_MIN_SEC = re.compile(r"^(\d{1,2})[:.](\d{2})[:.](\d{2})$")
_PLAIN = re.compile(r"^\d{1,5}$")
_DATE = re.compile(r"^(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2}|\d{4}))?$")
_RELATIVE_DAYS = {"сегодня": 0, "вчера": 1, "позавчера": 2}


class PlainUnit(StrEnum):
    """Как понимать время без двоеточия: «345» — секунды (планка), «70» — минуты (тренировка)."""

    SECONDS = "seconds"
    MINUTES = "minutes"


_PLAIN_HINT = {PlainUnit.SECONDS: "в секундах: 345", PlainUnit.MINUTES: "в минутах: 70"}


def parse_number(text: str) -> Decimal:
    """«77.5» и «77,5» — одно и то же число; «4,5,1», «abc», пустая строка — ``INPUT-NUMBER``."""
    raw = text.strip()
    match = _NUMBER.match(raw) if len(raw) <= MAX_NUMBER_LENGTH else None
    if match is None:
        raise AppError("INPUT-NUMBER", value=raw)
    whole, fraction = match.groups()
    try:
        return Decimal(f"{whole}.{fraction}" if fraction else whole)
    except InvalidOperation:  # pragma: no cover — регулярное выражение пропускает только цифры
        raise AppError("INPUT-NUMBER", value=raw) from None


def parse_number_in_range(text: str, *, low: Decimal | int, high: Decimal | int, field: str, unit: str) -> Decimal:
    """Число в допустимых границах. Похоже на ×10 или ÷10 от допустимого — подсказка про цифру."""
    value = parse_number(text)
    low_d, high_d = Decimal(low), Decimal(high)
    if low_d <= value <= high_d:
        return value
    if low_d <= value / 10 <= high_d:
        guess = " — может, лишняя цифра?"
    elif low_d <= value * 10 <= high_d:
        guess = " — может, не хватает цифры?"
    else:
        guess = ""
    raise AppError(
        "INPUT-RANGE", field=field, low=format_number(low_d), high=format_number(high_d), unit=unit,
        value=text.strip(), guess=guess,
    )


def parse_duration(text: str, plain: PlainUnit = PlainUnit.SECONDS) -> int:
    """Длительность в секундах: «5:45», «5.45», «28.40», «1:02:03» или одно число (секунды или минуты)."""
    raw = text.strip()
    seconds: int | None = None
    if _PLAIN.match(raw):
        seconds = int(raw) * (60 if plain is PlainUnit.MINUTES else 1)
    elif match := _MIN_SEC.match(raw):
        minutes, secs = int(match[1]), int(match[2])
        seconds = minutes * 60 + secs if secs < 60 else None
    elif match := _HOUR_MIN_SEC.match(raw):
        hours, minutes, secs = int(match[1]), int(match[2]), int(match[3])
        seconds = hours * 3600 + minutes * 60 + secs if minutes < 60 and secs < 60 else None
    if not seconds:
        raise AppError("INPUT-TIME", value=raw, plain=_PLAIN_HINT[plain])
    return seconds


def parse_date(text: str, today: date) -> date:
    """«20.10», «20.10.2026», «20/10/26», «вчера». Без года — ближайшая прошедшая такая дата.

    Если дата без года в этом году ещё не наступила больше чем на полгода (в январе пишут «28.12»),
    берётся прошлый год. Будущую дату проверяет ``ensure_not_future``.
    """
    raw = text.strip().lower()
    if raw in _RELATIVE_DAYS:
        return today - timedelta(days=_RELATIVE_DAYS[raw])
    match = _DATE.match(raw)
    if match is None:
        raise AppError("INPUT-DATE", value=text.strip())
    day, month, year_text = int(match[1]), int(match[2]), match[3]
    year = today.year if year_text is None else int(year_text) + (2000 if len(year_text) == 2 else 0)
    try:
        result = date(year, month, day)
        if year_text is None and result - today > HALF_YEAR:
            result = date(year - 1, month, day)
    except ValueError:
        raise AppError("INPUT-DATE", value=text.strip()) from None
    return result


def ensure_not_future(day: date, today: date) -> date:
    """Будущие даты запрещены (раздел 4.3)."""
    if day > today:
        raise AppError("INPUT-FUTURE", day=format_day(day), today=format_day(today))
    return day


def logical_day(moment: datetime, tz: tzinfo, boundary_hour: int = DAY_BOUNDARY_HOUR) -> date:
    """Логический день записи: до 04:00 по местному времени — ещё предыдущий день (раздел 4.3)."""
    if moment.tzinfo is None:
        raise ValueError("Нужно время с часовым поясом")
    return (moment.astimezone(tz) - timedelta(hours=boundary_hour)).date()
