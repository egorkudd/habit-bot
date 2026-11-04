"""Строка «Другое» (раздел 3.2): «Маффин 320 4,5 15 41 [цена]» — название, ккал, белки, жиры, углеводы, цена."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from habit_bot.kernel.domain.parsing import parse_number
from habit_bot.kernel.errors import AppError
from habit_bot.modules.food.domain.nutrition import Nutrients

FIELDS = ("ккал", "белки", "жиры", "углеводы")
NAME_MAX = 64
_NUMERIC = re.compile(r"^\+?\d")


@dataclass(frozen=True, slots=True)
class OtherLine:
    name: str
    nutrients: Nutrients
    price: Decimal | None


def parse_other_line(text: str) -> OtherLine:
    """Числа с точкой и запятой равнозначны: «4.5» = «4,5». Ошибка — подсказка, ввод не сбрасывается."""
    tokens = text.split()
    first_number = next((i for i, t in enumerate(tokens) if _NUMERIC.match(t)), len(tokens))
    name = " ".join(tokens[:first_number])
    numbers = tokens[first_number:]
    if not name:
        raise AppError("INPUT-FOOD-LINE", problem="Не хватает названия")
    if len(name) > NAME_MAX:
        raise AppError("INPUT-TEXT", field="Название", low=1, high=NAME_MAX, length=len(name))
    if len(numbers) < len(FIELDS):
        raise AppError("INPUT-FOOD-LINE", problem="Не хватает: " + ", ".join(FIELDS[len(numbers):]))
    if len(numbers) > len(FIELDS) + 1:
        raise AppError("INPUT-FOOD-LINE", problem=f"Лишнее число: {numbers[len(FIELDS) + 1]}")
    values = [parse_number(n) for n in numbers]
    price = values[4] if len(values) == len(FIELDS) + 1 else None
    return OtherLine(name, Nutrients(*values[:4]), price)


def parse_values_line(text: str) -> tuple[Nutrients, Decimal | None]:
    """Значения своего рецепта или продукта: «322 26 9 39 140» — ккал, Б, Ж, У и цена по желанию."""
    numbers = text.split()
    if len(numbers) < len(FIELDS):
        raise AppError("INPUT-FOOD-LINE", problem="Не хватает: " + ", ".join(FIELDS[len(numbers):]))
    if len(numbers) > len(FIELDS) + 1:
        raise AppError("INPUT-FOOD-LINE", problem=f"Лишнее число: {numbers[len(FIELDS) + 1]}")
    values = [parse_number(n) for n in numbers]
    return Nutrients(*values[:4]), values[4] if len(values) == len(FIELDS) + 1 else None
