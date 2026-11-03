"""Раздел 3 «Ввод чисел», 4.3 и 7.4.1: разбор чисел, времени и дат во всём боте."""

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from habit_bot.kernel.domain.formatting import format_date, format_day, format_duration, format_number
from habit_bot.kernel.domain.parsing import (
    PlainUnit,
    ensure_not_future,
    logical_day,
    parse_date,
    parse_duration,
    parse_number,
    parse_number_in_range,
)
from habit_bot.kernel.errors import AppError

MSK = timezone(timedelta(hours=3))


@pytest.mark.parametrize(
    ("text", "expected"),
    [("77.5", "77.5"), ("77,5", "77.5"), (" 77,5 ", "77.5"), ("75", "75"), ("+3", "3"), ("0,25", "0.25")],
)
def test_number_with_dot_or_comma(text: str, expected: str) -> None:
    """Раздел 9: вес «77.5» и «77,5» сохраняются одинаково."""
    assert parse_number(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["4,5,1", "abc", "", " ", "4.", ",5", "-5", "1 000", "1" * 16, "5кг"])
def test_bad_number(text: str) -> None:
    """Раздел 9: «4,5,1» → «Не понял число „4,5,1“. Напишите, например, 4,5 или 4.5»."""
    with pytest.raises(AppError) as err:
        parse_number(text)
    assert err.value.code == "INPUT-NUMBER"
    if text == "4,5,1":
        assert err.value.user_text() == "Не понял число „4,5,1“. Напишите, например, 4,5 или 4.5"


def test_number_in_range() -> None:
    """Число в границах возвращается как есть."""
    assert parse_number_in_range("178", low=120, high=230, field="Рост", unit="см") == Decimal(178)


def test_range_extra_digit() -> None:
    """Раздел 9: рост «1780» → подсказка «может, лишняя цифра?»."""
    with pytest.raises(AppError) as err:
        parse_number_in_range("1780", low=120, high=230, field="Рост", unit="см")
    assert err.value.code == "INPUT-RANGE"
    assert err.value.user_text() == "Рост — от 120 до 230 см. Вы ввели 1780 — может, лишняя цифра?"


def test_range_missing_digit_and_far_off() -> None:
    """Значение в 10 раз меньше допустимого — «не хватает цифры?»; далеко за границами — без догадки."""
    with pytest.raises(AppError) as err:
        parse_number_in_range("17,8", low=120, high=230, field="Рост", unit="см")
    assert err.value.user_text() == "Рост — от 120 до 230 см. Вы ввели 17,8 — может, не хватает цифры?"
    with pytest.raises(AppError) as err:
        parse_number_in_range("5", low=120, high=230, field="Рост", unit="см")
    assert err.value.user_text() == "Рост — от 120 до 230 см. Вы ввели 5"


@pytest.mark.parametrize(
    ("text", "plain", "expected"),
    [
        ("5:45", PlainUnit.SECONDS, 345),
        ("5.45", PlainUnit.SECONDS, 345),
        ("28.40", PlainUnit.SECONDS, 1720),
        ("28:40", PlainUnit.SECONDS, 1720),
        ("28,40", PlainUnit.SECONDS, 1720),
        ("345", PlainUnit.SECONDS, 345),
        ("1:02:03", PlainUnit.SECONDS, 3723),
        ("1.02.03", PlainUnit.SECONDS, 3723),
        ("70", PlainUnit.MINUTES, 4200),
        (" 6:00 ", PlainUnit.SECONDS, 360),
    ],
)
def test_duration_formats(text: str, plain: PlainUnit, expected: int) -> None:
    """Раздел 9: «28.40» и «28:40» равнозначны; планка 5:45; тренировка «70» — минуты."""
    assert parse_duration(text, plain) == expected


@pytest.mark.parametrize("text", ["5:75", "5:7", "1:60:00", "0", "0:00", "abc", "5:45:", "", "123456", "1:00:60"])
def test_bad_duration(text: str) -> None:
    """Неверное время — «Время пишите как 5:45, 5.45 или в секундах: 345»."""
    with pytest.raises(AppError) as err:
        parse_duration(text)
    assert err.value.code == "INPUT-TIME"
    assert err.value.user_text() == "Время пишите как 5:45, 5.45 или в секундах: 345"


def test_bad_duration_minutes_hint() -> None:
    """Там, где одно число — минуты, подсказка говорит про минуты."""
    with pytest.raises(AppError) as err:
        parse_duration("х", PlainUnit.MINUTES)
    assert err.value.user_text() == "Время пишите как 5:45, 5.45 или в минутах: 70"


TODAY = date(2026, 10, 26)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("20.10", date(2026, 10, 20)),
        ("20.10.2026", date(2026, 10, 20)),
        ("20/10/26", date(2026, 10, 20)),
        ("1-9", date(2026, 9, 1)),
        ("Вчера", date(2026, 10, 25)),
        ("позавчера", date(2026, 10, 24)),
        ("сегодня", TODAY),
        ("27.10", date(2026, 10, 27)),
    ],
)
def test_dates(text: str, expected: date) -> None:
    """Даты как 20.10 или 20.10.2026; «вчера» и «позавчера» — от сегодняшнего дня."""
    assert parse_date(text, TODAY) == expected


def test_date_without_year_in_january() -> None:
    """В январе «28.12» — это декабрь прошлого года, а не будущее."""
    assert parse_date("28.12", date(2027, 1, 5)) == date(2026, 12, 28)


@pytest.mark.parametrize("text", ["31.02", "20.13", "завтра", "2026-10-20", "", "29.02.2027"])
def test_bad_dates(text: str) -> None:
    """Неверная дата — «Дату пишите как 20.10 или 20.10.2026»."""
    with pytest.raises(AppError) as err:
        parse_date(text, TODAY)
    assert err.value.code == "INPUT-DATE"
    assert err.value.user_text() == "Дату пишите как 20.10 или 20.10.2026"


def test_future_date() -> None:
    """Раздел 9: будущую дату выбрать нельзя — «Нельзя записать на 27.10 — это будущее. Сегодня 26.10»."""
    assert ensure_not_future(TODAY, TODAY) == TODAY
    with pytest.raises(AppError) as err:
        ensure_not_future(parse_date("27.10", TODAY), TODAY)
    assert err.value.user_text() == "Нельзя записать на 27.10 — это будущее. Сегодня 26.10"


@pytest.mark.parametrize(
    ("local", "expected"),
    [
        (datetime(2026, 10, 25, 0, 20, tzinfo=MSK), date(2026, 10, 24)),
        (datetime(2026, 10, 25, 4, 5, tzinfo=MSK), date(2026, 10, 25)),
        (datetime(2026, 10, 25, 3, 58, tzinfo=MSK), date(2026, 10, 24)),
        (datetime(2026, 10, 25, 4, 0, tzinfo=MSK), date(2026, 10, 25)),
        (datetime(2026, 10, 24, 21, 30, tzinfo=UTC), date(2026, 10, 24)),
    ],
)
def test_logical_day(local: datetime, expected: date) -> None:
    """Раздел 9: запись 25.10 в 00:20 — в 24.10, в 04:05 — в 25.10, в 03:58 — в 24.10."""
    assert logical_day(local, MSK) == expected


def test_logical_day_needs_timezone() -> None:
    """Время без часового пояса — ошибка программиста."""
    with pytest.raises(ValueError, match="часовым поясом"):
        logical_day(datetime(2026, 10, 25, 0, 20), MSK)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("77.5"), "77,5"),
        (Decimal("77.50"), "77,5"),
        (75, "75"),
        (2340, "2 340"),
        (Decimal("0.125"), "0,13"),
        (Decimal("-12.3"), "−12,3"),
        (1234567.891, "1 234 567,89"),
    ],
)
def test_format_number(value: Decimal | int | float, expected: str) -> None:
    """Бот показывает числа с запятой, до 2 знаков, разряды через пробел."""
    assert format_number(value) == expected


def test_format_time_and_dates() -> None:
    """«5:45», «1:02:03», «24.10», «20.10.2026»."""
    assert format_duration(345) == "5:45"
    assert format_duration(360) == "6:00"
    assert format_duration(3723) == "1:02:03"
    assert format_day(date(2026, 10, 24)) == "24.10"
    assert format_date(date(2026, 10, 20)) == "20.10.2026"
