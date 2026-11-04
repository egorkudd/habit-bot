"""Раздел 4.12 (распознавание города) и 3.13 (приглашения): чистые функции."""

from datetime import UTC, date, datetime, timedelta

import pytest

from habit_bot.kernel.errors import AppError
from habit_bot.modules.users.domain.city import City, normalize, pick_matches, resolve_local, short_region, suggest
from habit_bot.modules.users.domain.invites import check_invite, days_label, uses_label

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("text", ["МОСКВА", "москва", " Москва ", "мск", "Москва."])
def test_moscow_variants(text: str) -> None:
    """Раздел 9: «МОСКВА», «москва» и « Москва » распознаются как Москва — без запроса к сервису."""
    query, city = resolve_local(text)
    assert city is not None and city.name == "Москва"
    assert query in {"Москва", text.strip()}


@pytest.mark.parametrize("text", ["питер", "СПб", "санкт-петербург", "Санкт Петербург"])
def test_piter_variants(text: str) -> None:
    """Раздел 9: «питер» и «СПб» — Санкт-Петербург."""
    _, city = resolve_local(text)
    assert city is not None and city.name == "Санкт-Петербург"


def test_normalize() -> None:
    """Регистр, ё, дефис, точки и кавычки: «ростов-на-дону» = «Ростов на Дону»."""
    assert normalize("ростов-на-дону") == normalize("Ростов на Дону") == "ростов на дону"
    assert normalize("«Орёл»") == "орел"


def test_synonym_to_search() -> None:
    """Синонимы, которых нет среди кнопок, уходят в поиск полным названием: «екб» → Екатеринбург."""
    assert resolve_local("екб") == ("Екатеринбург", None)
    assert resolve_local("Кировск") == ("Кировск", None)


def test_suggestions() -> None:
    """Раздел 9: «Масква» — похожий вариант «Москва»; совсем непохожее — без вариантов."""
    assert [c.name for c in suggest("Масква")] == ["Москва"]
    assert suggest("Ыыыыыыы") == []
    assert len(suggest("а", limit=3)) <= 3


def test_pick_matches() -> None:
    """Только Россия и соседи, без повторов; точные совпадения названия — первыми."""
    found = [
        City("Кировск", "Мурманская обл.", 67.6, 33.6),
        City("Кировск", "Мурманская обл.", 67.6, 33.6),
        City("Кировское", "Крым", 45.2, 35.2),
        City("Kirovsk", "Somewhere", 1, 1, "US"),
    ]
    assert [c.label for c in pick_matches("Кировск", found)] == ["Кировск, Мурманская обл."]
    assert [c.name for c in pick_matches("Кировс", found)] == ["Кировск", "Кировское"]
    assert pick_matches("x", [City("Paris", "IDF", 1, 1, "FR")]) == []


def test_region_and_label() -> None:
    """«Мурманская область» → «Мурманская обл.»; у города-региона регион не повторяется."""
    assert short_region("Мурманская область") == "Мурманская обл."
    assert short_region("Ростовская Область") == "Ростовская обл."  # так отвечает настоящий Open-Meteo
    assert short_region("Область Абай") == "обл. Абай"
    assert short_region(None) == ""
    assert City("Москва", "Москва", 0, 0).label == "Москва"
    assert City("Тула", "", 0, 0).label == "Тула"


def test_invite_valid_and_problems() -> None:
    """Раздел 9: отозванный или исчерпанный код не работает; истёкший — с датой."""
    check_invite(max_uses=5, uses=4, expires_at=NOW + timedelta(days=1), revoked_at=None, now=NOW)
    check_invite(max_uses=1, uses=0, expires_at=None, revoked_at=None, now=NOW)
    cases = [
        ({"max_uses": 1, "uses": 0, "expires_at": None, "revoked_at": NOW}, "отозвана"),
        ({"max_uses": 1, "uses": 1, "expires_at": None, "revoked_at": None}, "все места уже заняты"),
        ({"max_uses": 3, "uses": 0, "expires_at": NOW - timedelta(days=1), "revoked_at": None}, "истекла 03.11"),
    ]
    for kwargs, reason in cases:
        with pytest.raises(AppError) as err:
            check_invite(now=NOW, **kwargs)  # type: ignore[arg-type]
        assert err.value.user_text() == (
            f"Эта ссылка больше не действует ({reason}). Попросите новую у того, кто её прислал")
    with pytest.raises(AppError) as err:
        check_invite(max_uses=3, uses=0, expires_at=NOW, revoked_at=None, now=NOW, expires_local=date(2026, 10, 20))
    assert "истекла 20.10" in err.value.user_text()


def test_invite_labels() -> None:
    """Подписи кнопок приглашений."""
    assert uses_label(1) == "одноразовое"
    assert uses_label(5) == "на 5 человек"
    assert days_label(0) == "без срока"
    assert days_label(1) == "1 день"
    assert days_label(7) == "7 дней"
