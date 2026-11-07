"""Карточка дня в Telegram (раздел 3.1): короткий текст моноширинным блоком."""

from __future__ import annotations

import html

from habit_bot.kernel.domain.days import day_label
from habit_bot.kernel.domain.formatting import KBJU_HEADER, kbju_row
from habit_bot.modules.days.usecases import DayCardData

EMPTY = "Записей пока нет"


def render_card(data: DayCardData) -> str:
    """HTML для parse_mode="HTML": «<pre>23.10, пт · 🛌 выходной …</pre>»."""
    title = day_label(data.day) + (" · 🛌 выходной" if data.day_off else "")
    lines = [title]
    if data.goal is not None:  # таблица КБЖУ: «Цель», ниже — «Факт» и «Остаток» из раздела еды
        lines += [KBJU_HEADER, kbju_row("Цель", *data.goal.values())]
    lines.extend(data.lines or (EMPTY,))
    return "<pre>" + html.escape("\n".join(lines)) + "</pre>"
