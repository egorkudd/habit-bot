"""Проверки ответов анкеты и профиля (раздел 3.0): имя, дата рождения, ручные КБЖУ."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from habit_bot.kernel.domain.formatting import format_date
from habit_bot.kernel.domain.parsing import ensure_not_future, parse_date, parse_number
from habit_bot.kernel.errors import AppError

NAME_LENGTH = (1, 32)
EARLIEST_BIRTH = date(1900, 1, 1)
HEIGHT_RANGE = (120, 230)
WEIGHT_RANGE = (35, 250)
_FULL_YEAR = re.compile(r"\d{4}\s*$")
_SEPARATORS = re.compile(r"[\s/;]+")


def parse_name(text: str) -> str:
    name = " ".join(text.split())
    low, high = NAME_LENGTH
    if not low <= len(name) <= high:
        raise AppError("INPUT-TEXT", field="Имя", low=low, high=high, length=len(name))
    return name


def parse_birth_date(text: str, today: date) -> date:
    """ДД.ММ.ГГГГ: год полностью, не в будущем, не раньше 1900 года."""
    if not _FULL_YEAR.search(text):
        raise AppError("INPUT-DATE", value=text.strip())
    birth = ensure_not_future(parse_date(text, today), today)
    if birth < EARLIEST_BIRTH:
        raise AppError("INPUT-RANGE", field="Дата рождения", low=format_date(EARLIEST_BIRTH), high=format_date(today),
                       unit="", value=text.strip(), guess="")
    return birth


def parse_kbju_line(text: str) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """«2800 160 80 360» или «2800/160/80/360» → ккал, белки, жиры, углеводы."""
    parts = [p for p in _SEPARATORS.split(text.strip()) if p]
    if len(parts) != 4:
        raise AppError("INPUT-KBJU")
    kcal, protein, fat, carbs = (parse_number(p) for p in parts)
    return kcal, protein, fat, carbs
