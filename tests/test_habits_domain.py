"""Раздел 3.6, 4.6 и критерии раздела 9 «Привычки»: выполнение, расписание, серии, разбор значений."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from habit_bot.kernel.errors import AppError
from habit_bot.modules.habits.domain.habits import (
    STARTER,
    STREAK_LOOKBACK,
    TEMPLATE_BY_KEY,
    TEMPLATES,
    Measure,
    daily_totals,
    days_word,
    format_value,
    is_done,
    is_scheduled,
    parse_quick,
    parse_value,
    progress_label,
    schedule_label,
    streak,
    unit_of,
)

TODAY = date(2026, 10, 25)  # воскресенье


def test_templates_match_requirements() -> None:
    assert [t.short for t in TEMPLATES] == ["Глаза", "Вода", "Витамины", "Шаги", "Сон", "Чтение", "Без сладкого"]
    eyes, steps = TEMPLATE_BY_KEY["eyes"], TEMPLATE_BY_KEY["steps"]
    assert (eyes.measure, eyes.goal, eyes.step) == (Measure.CHECK, 3, 1)
    assert steps.step is None and steps.goal == 10_000
    assert set(STARTER) <= set(TEMPLATE_BY_KEY)


def test_values_and_labels() -> None:
    assert parse_value(Measure.AMOUNT, "1,5") == Decimal("1.5") == parse_value(Measure.AMOUNT, "1.5")
    assert parse_value(Measure.CHECK, "2") == 2
    with pytest.raises(AppError) as err:
        parse_value(Measure.AMOUNT, "0")
    assert err.value.code == "INPUT-RANGE"
    assert format_value(Decimal("1.5"), Measure.AMOUNT, "стак.") == "1,5 стак."
    assert format_value(Decimal(20), Measure.DURATION, "") == "20 мин"
    assert format_value(Decimal(3), Measure.CHECK, "раз") == "3"
    assert unit_of(Measure.CHECK, "x") == ""
    assert progress_label(Decimal(2), Decimal(3)) == "2/3"
    assert progress_label(Decimal("1.5"), None) == "1,5"
    assert is_done(Decimal(3), Decimal(3)) and not is_done(Decimal(2), Decimal(3))
    assert is_done(Decimal("0.5"), None) and not is_done(Decimal(0), None)
    assert parse_quick(Measure.AMOUNT, "2 0,5; 1 1 1,5 3") == [Decimal("0.5"), 1, Decimal("1.5"), 2]
    assert daily_totals([(TODAY, Decimal(1)), (TODAY, Decimal("0.5"))]) == {TODAY: Decimal("1.5")}


def test_schedule() -> None:
    assert is_scheduled(None, TODAY) and is_scheduled([6], TODAY) and not is_scheduled([0, 1], TODAY)
    assert schedule_label(None) == schedule_label(list(range(7))) == "каждый день"
    assert schedule_label([2, 0]) == "Пн, Ср"
    assert schedule_label([]) == "ни одного дня"


def test_streak_rules() -> None:
    """Раздел 9: при выполненной цели 23.10 и 24.10 серия 25.10 — 3 дня; невыполненный сегодня день не обрывает;
    выходные и дни не по расписанию пропускаются; пропуск по расписанию — обрывает."""
    done = {date(2026, 10, 23), date(2026, 10, 24), TODAY}
    every_day = lambda d: True  # noqa: E731
    no_off = lambda d: False  # noqa: E731
    assert streak(TODAY, done.__contains__, every_day, no_off) == 3
    assert streak(TODAY, (done - {TODAY}).__contains__, every_day, no_off) == 2
    gap = {TODAY, date(2026, 10, 23)}
    assert streak(TODAY, gap.__contains__, every_day, no_off) == 1
    assert streak(TODAY, gap.__contains__, every_day, lambda d: d == date(2026, 10, 24)) == 2
    weekdays = lambda d: d.weekday() < 5  # noqa: E731
    fridays = {date(2026, 10, 23), date(2026, 10, 22)}
    assert streak(TODAY, fridays.__contains__, weekdays, no_off) == 2
    always = lambda d: True  # noqa: E731
    assert streak(TODAY, always, every_day, no_off) == STREAK_LOOKBACK
    assert streak(TODAY, always, lambda d: False, no_off) == 0
    assert TODAY - timedelta(days=1) in done


@pytest.mark.parametrize(("n", "text"), [(1, "1 день"), (2, "2 дня"), (5, "5 дней"), (11, "11 дней"),
                                         (12, "12 дней"), (21, "21 день"), (22, "22 дня")])
def test_days_word(n: int, text: str) -> None:
    assert days_word(n) == text
