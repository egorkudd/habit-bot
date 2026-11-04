"""Карточка дня в Telegram (раздел 3.1): короткий текст моноширинным блоком."""

from __future__ import annotations

import html
from decimal import Decimal

from habit_bot.kernel.domain.days import day_label
from habit_bot.kernel.domain.formatting import format_number
from habit_bot.modules.days.usecases import DayCardData

EMPTY = "Записей пока нет"


def goal_text(kcal: Decimal, protein: Decimal, fat: Decimal, carbs: Decimal) -> str:
    n = format_number
    return f"Цель: {n(kcal)} ккал · Б {n(protein)} · Ж {n(fat)} · У {n(carbs)}"


def render_card(data: DayCardData) -> str:
    """HTML для parse_mode="HTML": «<pre>23.10, пт · 🛌 выходной …</pre>»."""
    title = day_label(data.day) + (" · 🛌 выходной" if data.day_off else "")
    lines = [title]
    if data.goal is not None:
        lines.append(goal_text(*data.goal.values()))
    lines.extend(data.lines or (EMPTY,))
    return "<pre>" + html.escape("\n".join(lines)) + "</pre>"
