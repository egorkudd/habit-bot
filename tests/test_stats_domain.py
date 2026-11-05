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
    ("2947", "2800", C.GREEN), ("3080", "2800", C.GREEN), ("2400", "2800", C.YELLOW), ("3400", "2800", C.RED),
    ("100", None, C.GRAY), (None, "2800", C.GRAY), ("100", "0", C.GRAY),
])
def test_kcal(fact: str | None, goal: str | None, color: C) -> None:
    """Калории: отклонение ≤ 10% — зелёный, 10–20% — жёлтый, больше — красный."""
    assert t.kcal(D(fact) if fact else None, D(goal) if goal else None) is color


def test_protein_and_macros() -> None:
    """Пример 22.10: белки 189 / 160 — зелёный, жиры 112 / 80 — красный (140%), углеводы 289 / 360 — жёлтый (80%)."""
    assert t.protein(D(189), D(160)) is C.GREEN
    assert t.protein(D(130), D(160)) is C.YELLOW and t.protein(D(100), D(160)) is C.RED
    assert t.protein(None, D(160)) is C.GRAY
    assert t.macro(D(112), D(80)) is C.RED and t.macro(D(289), D(360)) is C.YELLOW
    assert t.macro(D(85), D(80)) is C.GREEN


def test_warmup_weekly_habit() -> None:
    assert [t.warmup(n, 2) for n in (3, 2, 1, 0)] == [C.GREEN, C.GREEN, C.YELLOW, C.RED]
    assert t.warmup(1, 0) is C.GREEN
    assert [t.weekly(n, 3) for n in (3, 2, 1, 0)] == [C.GREEN, C.YELLOW, C.RED, C.RED]
    assert [t.habit(D(n), D(3)) for n in (3, 2, 1)] == [C.GREEN, C.YELLOW, C.RED]
    assert t.habit(D(1), None) is C.GREEN and t.habit(D(0), None) is C.RED


@pytest.mark.parametrize(("delta", "direction", "color"), [
    (None, 1, C.GRAY), ("0.1", 1, C.YELLOW), ("0.1", 0, C.GREEN), ("0.5", 0, C.YELLOW),
    ("0.5", 1, C.GREEN), ("-0.5", 1, C.RED), ("-0.5", -1, C.GREEN), ("0.5", -1, C.RED),
])
def test_weight(delta: str | None, direction: int, color: C) -> None:
    """Вес за неделю: в сторону цели — зелёный, ±0,2 кг — жёлтый (при поддержании — зелёный), против — красный."""
    assert t.weight(D(delta) if delta else None, direction) is color


def test_share_and_streak() -> None:
    cells = (C.RED, C.GREEN, C.GRAY, C.GREEN, C.YELLOW, C.GREEN, C.GRAY, C.GREEN, C.EMPTY)
    assert t.green_share(cells) == 67
    assert t.green_share((C.GRAY, C.EMPTY)) is None
    assert t.current_streak(cells) == 2  # серые и пустые серию не прерывают
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
    assert text_bar(Bar("Ккал", D("2947.24"), D(2800), C.GREEN)) == "Ккал   ████████████ 105%  2 947 / 2 800  🟢"
    assert text_bar(Bar("Вода", D("1.5"), None, C.GRAY)) == "Вода   ░░░░░░░░░░░░    —  1,5  ⚪"
    assert day_text(DayStats("Бег · 22.10 (чт)", empty=True)) == "Бег · 22.10 (чт)\nЗаписей нет"
    assert plain("🏆 Рекорд 👁 Глаза") == "★ Рекорд  Глаза"
    days = tuple(date(2026, 10, d) for d in range(1, 32))
    row = TrafficRow("Калории", (C.GREEN,) * 31, 100, 31)
    month = overview_text(Overview("Месяц", days, (row,)))
    assert month.split("\n")[1:3] == ["Калории  100% · серия 31", "  ●●●●●●●"]
    quarter = overview_text(Overview("3 месяца", days * 3, (TrafficRow("Калории", (C.GREEN,) * 93, None, 0),)))
    assert quarter.split("\n")[1] == "Калории  — · серия 0"
    assert overview_text(Overview("Неделя", days[:7])) == "Неделя\nЗа этот период записей нет"
    assert overview_png(Overview("Неделя", days[:7])).startswith(b"\x89PNG")
