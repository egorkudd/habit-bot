"""Раскладка кнопок по ширине подписи: всё, что не помещается, Telegram обрезает многоточием.

Telegram делит ряд поровну между кнопками и не переносит подпись на вторую строку. Bot API не сообщает
ширину, поэтому бюджет — в «знаках»: средняя буква кириллицы = 1, цифра = 0,85, пробел, скобки и узкая
пунктуация = 0,5, эмодзи = 2. Бюджеты посчитаны для узкого телефона (≈360 pt, шрифт по умолчанию) с запасом и сверены
с живым клиентом: в ряду из трёх даже «Отжимания» обрезалось (раздел 3.1 требований, «Кнопки»).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Сколько «знаков» помещается в одну кнопку, когда в ряду N кнопок.
BUDGET: dict[int, float] = {1: 30, 2: 15, 3: 8.5, 4: 6, 5: 4.5, 6: 3.5, 7: 3, 8: 2.5}
NARROW = frozenset(" .,:;!|'·()[]-/")
DIGITS = frozenset("0123456789")
_EMOJI_RANGES = ((0x2300, 0x23FF), (0x2600, 0x27BF), (0x2B00, 0x2BFF), (0x1F000, 0x1FAFF))


def _is_emoji(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in _EMOJI_RANGES)


def label_width(text: str) -> float:
    """Ширина подписи в «знаках»: «🏋️ Тренировка» = 2 + 0,5 + 10 = 12,5."""
    width = 0.0
    for char in text:
        if unicodedata.category(char) in {"Mn", "Me", "Cf"} or 0xFE00 <= ord(char) <= 0xFE0F:
            continue  # вариационные селекторы, ZWJ и надстрочные знаки ширины не добавляют
        if _is_emoji(char):
            width += 2
        elif char in NARROW:
            width += 0.5
        elif char in DIGITS:
            width += 0.85  # цифры уже средней буквы
        else:
            width += 1
    return width


def budget(columns: int) -> float:
    return BUDGET.get(columns, 1.0)


def fits(labels: Sequence[str]) -> bool:
    """Помещаются ли подписи в один ряд. Одна кнопка в ряду помещается всегда — шире ей не стать."""
    return len(labels) <= 1 or all(label_width(label) <= budget(len(labels)) for label in labels)


def text_of(button: object) -> str:
    return str(getattr(button, "text", button))


def fit_rows[B](buttons: Sequence[B], max_cols: int = 2) -> list[list[B]]:
    """По порядку: в ряд берётся столько кнопок (не больше ``max_cols``), сколько помещается целиком.

    Короткие подписи («×0,5», «×2») встают по две, длинное название рецепта — одно в ряду.
    """
    rows: list[list[B]] = []
    row: list[B] = []
    for button in buttons:
        candidate = [*row, button]
        if row and (len(candidate) > max_cols or not fits([text_of(b) for b in candidate])):
            rows.append(row)
            candidate = [button]
        row = candidate
    if row:
        rows.append(row)
    return rows


def row_problem(labels: Sequence[str]) -> str | None:
    """Для проверок: какая подпись обрежется в этом ряду."""
    if fits(labels):
        return None
    worst = max(labels, key=label_width)
    return (f"«{worst}» ({label_width(worst):g} зн.) не помещается в ряд из {len(labels)} "
            f"(до {budget(len(labels)):g} зн.): {list(labels)}")


def reflow[B](rows: Sequence[Sequence[B]]) -> list[list[B]]:
    """Ряды как задумал экран, но ряд, где подпись обрежется, делится на несколько (порядок кнопок тот же)."""
    result: list[list[B]] = []
    for row in rows:
        if not row:
            continue
        result += fit_rows(list(row), max_cols=len(row))
    return result


def inline(rows: Sequence[Sequence[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    """Кнопки под сообщением: ряды экрана с переносом того, что не помещается."""
    return InlineKeyboardMarkup(inline_keyboard=reflow(rows))
