"""Раздел 3.7 и 4.3: подписи дней, календарь месяца, давность даты."""

from datetime import date

from habit_bot.kernel.domain.days import (
    day_label,
    days_ago,
    days_word,
    month_title,
    month_weeks,
    needs_confirmation,
    quick_days,
    shift_month,
)


def test_quick_days() -> None:
    """Раздел 9: экран «Другой день» 25.10 показывает «Вчера (24.10)», «Позавчера (23.10)», далее «Чт (22.10)»…"""
    labels = [label for label, _ in quick_days(date(2026, 10, 25))]
    assert labels == ["Вчера (24.10)", "Позавчера (23.10)", "Чт (22.10)", "Ср (21.10)", "Вт (20.10)", "Пн (19.10)"]


def test_day_label() -> None:
    """Каждая карточка начинается с даты: «23.10, пт»."""
    assert day_label(date(2026, 10, 23)) == "23.10, пт"


def test_old_dates() -> None:
    """Дата старше 30 дней требует подтверждения; 30 дней — нет."""
    today = date(2026, 11, 4)
    assert days_ago(date(2026, 9, 20), today) == 45
    assert needs_confirmation(date(2026, 9, 20), today)
    assert not needs_confirmation(date(2026, 10, 5), today)


def test_calendar() -> None:
    """Календарь месяца с понедельника; соседние месяцы — пустые клетки; переход через год."""
    weeks = month_weeks(2026, 11)
    assert weeks[0][:6] == [None] * 6 and weeks[0][6] == date(2026, 11, 1)
    assert all(len(w) == 7 for w in weeks)
    assert month_title(2026, 11) == "Ноябрь 2026"
    assert shift_month(2026, 1, -1) == (2025, 12)
    assert shift_month(2026, 12, 1) == (2027, 1)


def test_days_word() -> None:
    """«45 дней», «31 день», «32 дня», «11 дней»."""
    assert [days_word(n) for n in (45, 31, 32, 11, 12, 22, 111)] == [
        "45 дней", "31 день", "32 дня", "11 дней", "12 дней", "22 дня", "111 дней"]
