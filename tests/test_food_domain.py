"""Раздел 4.2 и критерии раздела 9 «Еда»: КБЖУ записи, итог дня, остаток, строка «Другое»."""

from decimal import Decimal

import pytest

from habit_bot.kernel.errors import AppError
from habit_bot.modules.food.domain.nutrition import (
    NOTHING,
    Nutrients,
    Unit,
    check_quantity,
    day_totals,
    entry_values,
    quantity_label,
    rescale,
    unit_factor,
)
from habit_bot.modules.food.domain.other_line import parse_other_line, parse_values_line

THIGH = Nutrients.of(250, 23, 17, 0)
COCKTAIL = Nutrients.of(322, 26, 9, 39)


def test_two_thighs() -> None:
    """Раздел 9: «Куриные бёдра» → «2 шт»: 500 ккал / Б 46 / Ж 34 / У 0; 72 ₽ за 1 шт → 144 ₽."""
    values, price = entry_values(THIGH, Decimal(72), Unit.PIECE, Decimal(2))
    assert values == Nutrients.of(500, 46, 34, 0)
    assert price == Decimal("144.00")


def test_recipe_and_grams() -> None:
    """Рецепт × множитель; продукт на вес — на 100 г × граммы / 100; без цены — None («без цены»)."""
    assert entry_values(COCKTAIL, Decimal(140), Unit.PORTION, Decimal(1)) == (COCKTAIL.scaled(Decimal(1)),
                                                                             Decimal("140.00"))
    pasta = Nutrients.of(158, "5.8", "0.9", "30.9")
    values, price = entry_values(pasta, None, Unit.GRAMS, Decimal(150))
    assert values == Nutrients.of(237, "8.7", "1.35", "46.35")
    assert price is None
    assert unit_factor(Unit.GRAMS, Decimal(250)) == Decimal("2.5")


def test_rescale_and_totals() -> None:
    """×2 удваивает копию записи; итог дня — сумма, расход и число записей без цены; остаток = цель − факт."""
    doubled, price = rescale(COCKTAIL, Decimal(140), Decimal(1), Decimal(2))
    assert doubled == Nutrients.of(644, 52, 18, 78) and price == Decimal("280.00")
    assert rescale(THIGH, None, Decimal(1), Decimal(3))[1] is None
    totals = day_totals([(COCKTAIL, Decimal(140)), (THIGH, None)])
    assert totals.fact == Nutrients.of(572, 49, 26, 39)
    assert (totals.cost, totals.without_price, totals.count) == (Decimal("140.00"), 1, 2)
    goal = Nutrients.of(2800, 160, 80, 360)
    assert goal - totals.fact == Nutrients.of(2228, 111, 54, 321)
    assert day_totals([]).fact == NOTHING


@pytest.mark.parametrize(
    ("unit", "qty", "ok"),
    [(Unit.GRAMS, "150", True), (Unit.GRAMS, "0", False), (Unit.GRAMS, "6000", False),
     (Unit.PIECE, "0.5", True), (Unit.PIECE, "60", False), (Unit.PORTION, "0.5", True), (Unit.PORTION, "25", False)],
)
def test_quantity_limits(unit: Unit, qty: str, ok: bool) -> None:
    """Количество в разумных границах; иначе — INPUT-RANGE с единицей."""
    if ok:
        assert check_quantity(unit, Decimal(qty)) == Decimal(qty)
    else:
        with pytest.raises(AppError) as err:
            check_quantity(unit, Decimal(qty))
        assert err.value.code == "INPUT-RANGE"


def test_quantity_labels() -> None:
    """«150 г», «2 шт», «1 порция (30 г)», «×0,5»."""
    assert quantity_label(Unit.GRAMS, Decimal(150)) == "150 г"
    assert quantity_label(Unit.PIECE, Decimal(2)) == "2 шт"
    assert quantity_label(Unit.PORTION, Decimal(1), "30 г") == "1 порция (30 г)"
    assert quantity_label(Unit.PORTION, Decimal("0.5")) == "×0,5"


@pytest.mark.parametrize("text", ["Маффин 320 4.5 15 41", "Маффин 320 4,5 15 41", "  Маффин   320 4,5 15 41 "])
def test_other_line_dot_and_comma(text: str) -> None:
    """Раздел 9: «Маффин 320 4.5 15 41» и «Маффин 320 4,5 15 41» дают одинаковую запись."""
    line = parse_other_line(text)
    assert (line.name, line.nutrients, line.price) == ("Маффин", Nutrients.of(320, "4.5", 15, 41), None)


def test_other_line_with_price_and_long_name() -> None:
    """Название из нескольких слов и цена в конце."""
    line = parse_other_line("Фреш маффин двойной 368 18 20 28 90")
    assert (line.name, line.price) == ("Фреш маффин двойной", Decimal(90))


def test_other_line_errors() -> None:
    """Раздел 9: «4,5,1» — подсказка про число; «Маффин 320 4,5 15» → «Не хватает: углеводы» с примером."""
    with pytest.raises(AppError) as err:
        parse_other_line("Маффин 320 4,5,1 15 41")
    assert err.value.code == "INPUT-NUMBER"
    with pytest.raises(AppError) as err:
        parse_other_line("Маффин 320 4,5 15")
    assert err.value.user_text() == ("Не хватает: углеводы. Формат: название, ккал, белки, жиры, углеводы, [цена]. "
                                     "Пример: Маффин 320 4,5 15 41 90")
    with pytest.raises(AppError) as err:
        parse_other_line("320 4 15 41")
    assert err.value.user_text().startswith("Не хватает названия.")
    with pytest.raises(AppError) as err:
        parse_other_line("Маффин 1 2 3 4 5 6")
    assert err.value.user_text().startswith("Лишнее число: 6.")
    with pytest.raises(AppError) as err:
        parse_other_line("я" * 65 + " 1 2 3 4")
    assert err.value.code == "INPUT-TEXT"


def test_values_line() -> None:
    """Значения своего рецепта: 4 числа и цена по желанию."""
    assert parse_values_line("322 26 9 39 140") == (COCKTAIL, Decimal(140))
    assert parse_values_line("250 23 17 0") == (THIGH, None)
    with pytest.raises(AppError):
        parse_values_line("322 26")
    with pytest.raises(AppError):
        parse_values_line("1 2 3 4 5 6")
