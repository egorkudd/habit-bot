"""«📅 Выбрать даты» в экспорте: «01.10–22.10», «с 01.10 по 22.10», «01.10.2026 22.10.2026»."""

from __future__ import annotations

import re
from datetime import date

from habit_bot.kernel.domain.parsing import ensure_not_future, parse_date
from habit_bot.kernel.errors import AppError

_DATE = re.compile(r"\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?")


def parse_range(text: str, today: date) -> tuple[date, date]:
    found = _DATE.findall(text)
    if len(found) != 2:
        raise AppError("INPUT-PERIOD")
    first, second = (ensure_not_future(parse_date(x, today), today) for x in found)
    return (first, second) if first <= second else (second, first)
