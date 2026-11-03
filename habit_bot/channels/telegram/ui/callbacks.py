"""Данные кнопок. Каждая кнопка несёт владельца ``o`` и номер ввода ``t`` (0 — кнопка не устаревает).

Telegram ограничивает данные кнопки 64 байтами, поэтому имена полей короткие.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class MenuCb(CallbackData, prefix="m"):
    """Пункт меню «Ещё»."""

    o: int
    t: int
    k: str


class CancelCb(CallbackData, prefix="c"):
    """«✕ Отмена» в многошаговом вводе."""

    o: int
    t: int


class StepCb(CallbackData, prefix="s"):
    """Действие внутри ввода: «Готово», «Назад» и т. п."""

    o: int
    t: int
    a: str


def owner_and_token(data: object) -> tuple[int, int] | None:
    """(владелец, номер ввода) для кнопок с проверкой; ``None`` — у данных нет этих полей."""
    if not isinstance(data, CallbackData):
        return None
    owner, token = getattr(data, "o", None), getattr(data, "t", None)
    if isinstance(owner, int) and isinstance(token, int):
        return owner, token
    return None
