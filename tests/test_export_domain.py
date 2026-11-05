"""Раздел 3.12: формат CSV для Excel и нейросетей; период «📅 Выбрать даты»."""

from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest

from habit_bot.kernel.errors import AppError
from habit_bot.modules.export.domain.csv_format import Column, TableSpec, cell, readme, to_csv
from habit_bot.modules.export.domain.period import parse_range
from habit_bot.modules.food.domain.nutrition import Unit

SPEC = TableSpec("t", "t.csv", "Тест", "одна проверка", (Column("a", "первая", "кг"), Column("b", "вторая")))


@pytest.mark.parametrize(("value", "text"), [
    (None, ""), (True, "true"), (False, "false"), (Unit.GRAMS, "100g"), (date(2026, 10, 22), "2026-10-22"),
    (datetime(2026, 10, 22, 9, 5, tzinfo=UTC), "09:05"), (time(7, 30), "07:30"), (Decimal("2947.24"), "2947.24"),
    (Decimal("2800.00"), "2800"), (2800.0, "2800"), (Decimal("0.001"), "0"), (Decimal("-0.001"), "0"),
    (Decimal("-147.24"), "-147.24"), (5, "5"), ("Творог, ужин", "Творог, ужин"),
])
def test_cell(value: object, text: str) -> None:
    """Десятичная точка без экспоненты и лишних нулей, ISO-даты, ЧЧ:ММ, пусто вместо «нет»."""
    assert cell(value) == text  # type: ignore[arg-type]


def test_csv_bom_comma_and_quotes() -> None:
    raw = to_csv(SPEC, [(Decimal("4.5"), "Творог, ужин"), (None, 'кавычки "да"')])
    assert raw.startswith(b"\xef\xbb\xbf")
    assert raw.decode("utf-8-sig") == 'a,b\r\n4.5,"Творог, ужин"\r\n,"кавычки ""да"""\r\n'
    with pytest.raises(ValueError):
        to_csv(SPEC, [(1,)])
    assert readme([SPEC]).decode("utf-8-sig").splitlines() == [
        "file,column,description,unit", "t.csv,,одна строка — одна проверка,", "t.csv,a,первая,кг",
        "t.csv,b,вторая,"]


def test_parse_range() -> None:
    today = date(2026, 10, 22)
    assert parse_range("01.10–22.10", today) == (date(2026, 10, 1), date(2026, 10, 22))
    assert parse_range("с 22.10 по 01.10.2026", today) == (date(2026, 10, 1), date(2026, 10, 22))
    for wrong in ("вчера", "01.10", "01.10 02.10 03.10"):
        with pytest.raises(AppError) as err:
            parse_range(wrong, today)
        assert err.value.code == "INPUT-PERIOD"
    with pytest.raises(AppError) as err:
        parse_range("01.10–25.10", today)
    assert err.value.code == "INPUT-FUTURE"
