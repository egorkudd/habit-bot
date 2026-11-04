"""Настоящий Open-Meteo Geocoding: формат ответа и случаи из раздела 9 «Город».

Здесь же сверяются записанные ответы, на которых работают обычные тесты (tests/fakes.py, GEOCODER_ANSWERS).
"""

from habit_bot.modules.users.domain.city import normalize, pick_matches, resolve_local, suggest
from habit_bot.modules.users.usecases import _city
from habit_bot.platform.sources.geocoding import OpenMeteoGeocoder


async def _matches(text: str) -> list[str]:
    query, local = resolve_local(text)
    assert local is None
    places = await OpenMeteoGeocoder().search(query)
    return [c.label for c in pick_matches(query, [_city(p) for p in places])]


async def test_kirovsk_has_regions() -> None:
    """«Кировск» — несколько городов с регионами, среди них Мурманская и Ленинградская области."""
    labels = await _matches("Кировск")
    assert "Кировск, Мурманская обл." in labels
    assert "Кировск, Ленинградская обл." in labels


async def test_rostov_single_exact() -> None:
    """«ростов-на-дону» — Ростов-на-Дону, Ростовская область."""
    labels = await _matches("ростов-на-дону")
    assert labels[0] == "Ростов-на-Дону, Ростовская обл."


async def test_typo_not_found_and_suggested() -> None:
    """«Масква» — сервис не находит Москву, бот предлагает её по похожести написания."""
    labels = await _matches("Масква")
    assert all(normalize(label.split(",")[0]) != "москва" for label in labels)
    assert [c.name for c in suggest("Масква")] == ["Москва"]


async def test_new_city_coordinates() -> None:
    """Новосибирск — координаты как в записанном ответе (±0,1°)."""
    places = await OpenMeteoGeocoder().search("Новосибирск")
    city = next(p for p in places if p.country_code == "RU" and p.name == "Новосибирск")
    assert abs(city.latitude - 55.04) < 0.1 and abs(city.longitude - 82.93) < 0.1
