"""Раздел 4.10: цвета светофора; раздел 3.8.2: периоды обзора; «Текстом» — моноширинная таблица."""

from datetime import date
from decimal import Decimal as D

import pytest

from habit_bot.channels.telegram.render.stats import day_text, overview_png, overview_text, plain, text_bar
from habit_bot.modules.stats.domain.periods import Kind, day_title, period, word
from habit_bot.platform.stats.data import Bar, DayStats, Overview, TrafficRow
from habit_bot.platform.stats.domain import traffic as t
from habit_bot.platform.stats.domain.traffic import Color as C


@pytest.mark.parametrize(("fact", "goal", "color"), [
    ("2947", "2800", C.DONE), ("3080", "2800", C.DONE), ("2400", "2800", C.PARTIAL), ("3400", "2800", C.PARTIAL),
    ("100", None, C.PARTIAL), (None, "2800", C.NONE), ("0", "2800", C.NONE), ("100", "0", C.PARTIAL),
])
def test_kcal(fact: str | None, goal: str | None, color: C) -> None:
    """Калории: отклонение от цели ≤ 10% — выполнено (чёрная), записано, но мимо — частично (серая), ничего —
    белая."""
    assert t.kcal(D(fact) if fact else None, D(goal) if goal else None) is color


def test_protein_and_macros() -> None:
    """Пример 22.10: белки 189 / 160 — выполнено; жиры 112 / 80 (140%) и углеводы 289 / 360 (80%) — частично."""
    assert t.protein(D(189), D(160)) is C.DONE
    assert t.protein(D(130), D(160)) is C.PARTIAL and t.protein(None, D(160)) is C.NONE
    assert t.protein(D(100), None) is C.PARTIAL
    assert t.macro(D(112), D(80)) is C.PARTIAL and t.macro(D(289), D(360)) is C.PARTIAL
    assert t.macro(D(85), D(80)) is C.DONE and t.macro(None, D(80)) is C.NONE and t.macro(D(5), None) is C.PARTIAL


def test_warmup_weekly_habit() -> None:
    """Сколько надо и больше — чёрная, часть — серая, ноль — белая."""
    assert [t.warmup(n, 2) for n in (3, 2, 1, 0)] == [C.DONE, C.DONE, C.PARTIAL, C.NONE]
    assert t.warmup(1, 0) is C.DONE
    assert [t.weekly(n, 3) for n in (3, 2, 1, 0)] == [C.DONE, C.PARTIAL, C.PARTIAL, C.NONE]
    assert [t.habit(D(n), D(3)) for n in (4, 3, 2, 1, 0)] == [C.DONE, C.DONE, C.PARTIAL, C.PARTIAL, C.NONE]
    assert t.habit(D(1), None) is C.DONE and t.habit(D(0), None) is C.NONE


@pytest.mark.parametrize(("delta", "direction", "color"), [
    (None, 1, C.NONE), ("0.1", 1, C.PARTIAL), ("0.1", 0, C.DONE), ("0.5", 0, C.PARTIAL),
    ("0.5", 1, C.DONE), ("-0.5", 1, C.PARTIAL), ("-0.5", -1, C.DONE), ("0.5", -1, C.PARTIAL),
])
def test_weight(delta: str | None, direction: int, color: C) -> None:
    """Вес за неделю: в сторону цели (при поддержании — на месте ±0,2 кг) — выполнено, иначе — частично."""
    assert t.weight(D(delta) if delta else None, direction) is color


def test_share_and_streak() -> None:
    cells = (C.NONE, C.DONE, C.OFF, C.DONE, C.PARTIAL, C.DONE, C.SKIP, C.DONE, C.FUTURE)
    assert t.green_share(cells) == 67
    assert t.green_share((C.OFF, C.SKIP, C.FUTURE)) is None
    assert t.current_streak(cells) == 2  # выходные и неоценённые дни серию не прерывают
    assert t.percent(D(289), D(360)) == 80 and t.percent(D(1), None) is None


def test_periods() -> None:
    today = date(2026, 11, 5)
    week = period(Kind.WEEK, today)
    assert (week.start, week.end, week.title) == (date(2026, 11, 2), date(2026, 11, 8), "Неделя · 02.11–08.11")
    assert period(Kind.WEEK, today, -1).start == date(2026, 10, 26)
    assert period(Kind.WEEK, today, 2).shift == 0  # в будущее не листается
    month = period(Kind.MONTH, today, -10)
    assert (month.start, month.end, month.title) == (date(2026, 1, 1), date(2026, 1, 31), "Месяц · январь 2026")
    assert len(period(Kind.MONTH, date(2026, 2, 10)).days) == 28
    q = period(Kind.QUARTER, today)
    assert (q.start, q.end, q.title) == (date(2026, 9, 1), date(2026, 11, 30), "3 месяца · сентябрь–ноябрь 2026")
    q = period(Kind.QUARTER, date(2026, 1, 20))
    assert q.title == "3 месяца · ноябрь–январь 2025–2026"
    assert day_title(date(2026, 10, 22)) == "22.10 (чт)"
    assert [word(n, "блюдо", "блюда", "блюд") for n in (1, 3, 5, 11, 21, 12, 22)] == [
        "блюдо", "блюда", "блюд", "блюд", "блюдо", "блюд", "блюда"]


def test_text_rendering() -> None:
    assert text_bar(Bar("Ккал", D("2947.24"), D(2800), C.DONE)) == "Ккал   ████████████ 105%  2 947 / 2 800  ●"
    assert text_bar(Bar("Вода", D("1.5"), None, C.PARTIAL)) == "Вода   ░░░░░░░░░░░░    —  1,5  ◐"
    assert day_text(DayStats("Бег · 22.10 (чт)", empty=True)) == "Бег · 22.10 (чт)\nЗаписей нет"
    assert plain("🏆 Рекорд 👁 Глаза") == "★ Рекорд  Глаза"
    days = tuple(date(2026, 10, d) for d in range(1, 32))
    row = TrafficRow("Калории", (C.DONE,) * 31, 100, 31)
    month = overview_text(Overview("Месяц", days, (row,)))
    assert month.split("\n")[1:3] == ["Калории  100% · серия 31", "  ●●●●●●●"]
    quarter = overview_text(Overview("3 месяца", days * 3, (TrafficRow("Калории", (C.DONE,) * 93, None, 0),)))
    assert quarter.split("\n")[1] == "Калории  — · серия 0"
    assert overview_text(Overview("Неделя", days[:7])) == "Неделя\nЗа этот период записей нет"
    assert overview_png(Overview("Неделя", days[:7])).startswith(b"\x89PNG")
