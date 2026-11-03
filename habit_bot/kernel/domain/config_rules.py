"""Правила разбора настроек из .env — без ввода-вывода, чтобы их можно было проверить полностью."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_BOT_TOKEN = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
_PROXY_SCHEMES = ("http://", "https://", "socks5://")


def split_list(raw: str | None) -> tuple[str, ...]:
    """«users, food ,,stats» → ("users", "food", "stats"): пустые элементы и пробелы убираются."""
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def parse_id_list(raw: str | None) -> tuple[frozenset[int], tuple[str, ...]]:
    """Разбирает список Telegram-ID через запятую.

    Возвращает найденные ID и элементы, которые не похожи на ID (чтобы показать их в ошибке).
    """
    ids: set[int] = set()
    bad: list[str] = []
    for item in split_list(raw):
        if item.isdigit() and int(item) > 0:
            ids.add(int(item))
        else:
            bad.append(item)
    return frozenset(ids), tuple(bad)


def looks_like_bot_token(raw: str | None) -> bool:
    """Токен от @BotFather выглядит как 123456789:AA… (цифры, двоеточие, не меньше 30 символов)."""
    if not raw:
        return False
    return _BOT_TOKEN.fullmatch(raw.strip()) is not None


def parse_positive_decimal(raw: str | None) -> Decimal | None:
    """«5», «7.5» и «7,5» → Decimal; ноль, отрицательные и не числа → None."""
    if raw is None:
        return None
    text = raw.strip().replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if not value.is_finite() or value <= 0:
        return None
    return value


def is_valid_proxy(raw: str) -> bool:
    """Прокси задаётся адресом с поддерживаемой схемой."""
    return raw.strip().lower().startswith(_PROXY_SCHEMES)


def mask_secret(raw: str) -> str:
    """Показывает в отчёте только начало значения: «1234…»."""
    raw = raw.strip()
    if len(raw) <= 4:
        return "…"
    return f"{raw[:4]}…"
