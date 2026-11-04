"""Расчёты еды (раздел 4.2): КБЖУ записи по единице и количеству, итог дня, остаток, цена.

Рецепт = КБЖУ порции × множитель; продукт на вес = значение на 100 г × граммы / 100; в штуках = на 1 шт × штуки.
Итог дня = сумма записей; Остаток = Цель − Факт (отрицательный — превышение). Нет цены — 0 и пометка «без цены».
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from habit_bot.kernel.domain.formatting import format_number
from habit_bot.kernel.errors import AppError

TWO = Decimal("0.01")
ZERO = Decimal(0)


class Unit(StrEnum):
    PORTION = "portion"  # порция рецепта или фасовка каталога («30 г», «4 шт»)
    GRAMS = "100g"       # продукт на вес: значения на 100 г, количество — в граммах
    PIECE = "piece"      # продукт в штуках: значения на 1 шт


QUICK_AMOUNTS: dict[Unit, tuple[int, ...]] = {Unit.GRAMS: (100, 150, 200, 300), Unit.PIECE: (1, 2, 3, 4)}
LIMITS: dict[Unit, tuple[Decimal, Decimal, str, str]] = {
    Unit.PORTION: (Decimal("0.1"), Decimal(20), "Порции", ""),
    Unit.GRAMS: (Decimal(1), Decimal(5000), "Вес", "г"),
    Unit.PIECE: (Decimal("0.25"), Decimal(50), "Количество", "шт"),
}


@dataclass(frozen=True, slots=True)
class Nutrients:
    kcal: Decimal
    protein: Decimal
    fat: Decimal
    carbs: Decimal

    @staticmethod
    def of(kcal: object, protein: object, fat: object, carbs: object) -> Nutrients:
        return Nutrients(*(Decimal(str(v)) for v in (kcal, protein, fat, carbs)))

    def __add__(self, other: Nutrients) -> Nutrients:
        return Nutrients(self.kcal + other.kcal, self.protein + other.protein, self.fat + other.fat,
                         self.carbs + other.carbs)

    def __sub__(self, other: Nutrients) -> Nutrients:
        return Nutrients(self.kcal - other.kcal, self.protein - other.protein, self.fat - other.fat,
                         self.carbs - other.carbs)

    def scaled(self, factor: Decimal) -> Nutrients:
        return Nutrients(*(round2(v * factor) for v in self.values()))

    def values(self) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        return self.kcal, self.protein, self.fat, self.carbs


NOTHING = Nutrients(ZERO, ZERO, ZERO, ZERO)


def round2(value: Decimal) -> Decimal:
    return value.quantize(TWO, rounding=ROUND_HALF_UP)


def unit_factor(unit: Unit, quantity: Decimal) -> Decimal:
    """Во сколько раз запись больше значений «на единицу»."""
    return quantity / 100 if unit is Unit.GRAMS else quantity


def check_quantity(unit: Unit, quantity: Decimal) -> Decimal:
    low, high, field, suffix = LIMITS[unit]
    if not low <= quantity <= high:
        raise AppError("INPUT-RANGE", field=field, low=format_number(low), high=format_number(high),
                       unit=f" {suffix}" if suffix else "", value=format_number(quantity), guess="")
    return quantity


def entry_values(
    per_unit: Nutrients, price: Decimal | None, unit: Unit, quantity: Decimal,
) -> tuple[Nutrients, Decimal | None]:
    """КБЖУ и цена записи: копия на момент записи (правка рецепта потом прошлое не меняет)."""
    factor = unit_factor(unit, quantity)
    return per_unit.scaled(factor), None if price is None else round2(price * factor)


def rescale(values: Nutrients, price: Decimal | None, old_qty: Decimal, new_qty: Decimal,
            ) -> tuple[Nutrients, Decimal | None]:
    """Новое количество записи: значения пересчитываются от её же копии."""
    factor = new_qty / old_qty
    return values.scaled(factor), None if price is None else round2(price * factor)


@dataclass(frozen=True, slots=True)
class DayTotals:
    fact: Nutrients
    cost: Decimal
    without_price: int
    count: int


def day_totals(entries: Iterable[tuple[Nutrients, Decimal | None]]) -> DayTotals:
    fact, cost, without_price, count = NOTHING, ZERO, 0, 0
    for values, price in entries:
        fact = fact + values
        count += 1
        if price is None:
            without_price += 1
        else:
            cost += price
    return DayTotals(fact, round2(cost), without_price, count)


def quantity_label(unit: Unit, quantity: Decimal, portion_label: str | None = None) -> str:
    """«2 шт», «150 г», «1 порция», «×0,5 (30 г)»."""
    if unit is Unit.GRAMS:
        return f"{format_number(quantity)} г"
    if unit is Unit.PIECE:
        return f"{format_number(quantity)} шт"
    base = f" ({portion_label})" if portion_label else ""
    if quantity == 1:
        return f"1 порция{base}"
    return f"×{format_number(quantity)}{base}"
