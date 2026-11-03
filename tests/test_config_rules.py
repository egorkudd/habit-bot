"""Бизнес-логика разбора настроек: покрытие 100% (раздел 7.3)."""

from decimal import Decimal

import pytest

from habit_bot.kernel.domain.config_rules import (
    is_valid_proxy,
    looks_like_bot_token,
    mask_secret,
    parse_id_list,
    parse_positive_decimal,
    split_list,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, ()), ("", ()), (" users , food ,, stats ", ("users", "food", "stats"))],
)
def test_split_list(raw: str | None, expected: tuple[str, ...]) -> None:
    """Списки в .env: пробелы и пустые элементы игнорируются."""
    assert split_list(raw) == expected


def test_parse_id_list_valid_and_bad() -> None:
    """Раздел 3.0: ADMIN_TG_IDS — Telegram-ID через запятую; ошибочные элементы показываются в сообщении."""
    ids, bad = parse_id_list("111, 222,abc, 0, -5, 111")
    assert ids == frozenset({111, 222})
    assert bad == ("abc", "0", "-5")


def test_parse_id_list_empty() -> None:
    """Пустой список — нет ни ID, ни ошибочных элементов."""
    assert parse_id_list(None) == (frozenset(), ())


@pytest.mark.parametrize(
    ("raw", "ok"),
    [
        (None, False),
        ("", False),
        ("12345:short", False),
        ("not-a-token", False),
        ("123456789:" + "A" * 35, True),
        (" 123456789:" + "A" * 35 + " ", True),
    ],
)
def test_looks_like_bot_token(raw: str | None, ok: bool) -> None:
    """Раздел 7.4.3: токен должен выглядеть как 123456789:AA…"""
    assert looks_like_bot_token(raw) is ok


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("abc", None),
        ("0", None),
        ("-1", None),
        ("inf", None),
        ("NaN", None),
        ("5", Decimal("5")),
        ("7.5", Decimal("7.5")),
        ("7,5", Decimal("7.5")),
    ],
)
def test_parse_positive_decimal(raw: str | None, expected: Decimal | None) -> None:
    """Числа принимаются с точкой и запятой; ноль, отрицательные и не числа отклоняются."""
    assert parse_positive_decimal(raw) == expected


@pytest.mark.parametrize(
    ("raw", "ok"),
    [("socks5://1.2.3.4:1080", True), ("HTTP://proxy:3128", True), ("https://p", True), ("ftp://x", False)],
)
def test_is_valid_proxy(raw: str, ok: bool) -> None:
    """Прокси для Telegram: только http, https или socks5."""
    assert is_valid_proxy(raw) is ok


def test_mask_secret() -> None:
    """В отчёт попадает только начало секрета."""
    assert mask_secret("123456789:AAE") == "1234…"
    assert mask_secret("abc") == "…"
