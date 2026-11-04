"""Распознавание города (раздел 4.12): нормализация, синонимы, кнопки с зашитыми координатами, похожие варианты."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True, slots=True)
class City:
    name: str
    region: str
    latitude: float
    longitude: float
    country_code: str = "RU"

    @property
    def label(self) -> str:
        return f"{self.name}, {self.region}" if self.region and self.region != self.name else self.name


# Кнопки анкеты и настроек — координаты зашиты в программу.
BUTTON_CITIES: tuple[City, ...] = (
    City("Москва", "Москва", 55.7558, 37.6173),
    City("Санкт-Петербург", "Санкт-Петербург", 59.9386, 30.3141),
    City("Череповец", "Вологодская обл.", 59.1333, 37.9000),
)
# Крупные города — для подсказки «Может, …?», когда поиск ничего не нашёл.
KNOWN_CITIES: tuple[City, ...] = (
    *BUTTON_CITIES,
    City("Новосибирск", "Новосибирская обл.", 55.0415, 82.9346),
    City("Екатеринбург", "Свердловская обл.", 56.8519, 60.6122),
    City("Казань", "Республика Татарстан", 55.7887, 49.1221),
    City("Нижний Новгород", "Нижегородская обл.", 56.3287, 44.0020),
    City("Челябинск", "Челябинская обл.", 55.1544, 61.4297),
    City("Самара", "Самарская обл.", 53.2001, 50.1500),
    City("Омск", "Омская обл.", 54.9924, 73.3686),
    City("Ростов-на-Дону", "Ростовская обл.", 47.2313, 39.7233),
    City("Уфа", "Республика Башкортостан", 54.7431, 55.9678),
    City("Красноярск", "Красноярский край", 56.0184, 92.8672),
    City("Воронеж", "Воронежская обл.", 51.6720, 39.1843),
    City("Пермь", "Пермский край", 58.0105, 56.2502),
    City("Волгоград", "Волгоградская обл.", 48.7194, 44.5018),
    City("Краснодар", "Краснодарский край", 45.0448, 38.9760),
    City("Вологда", "Вологодская обл.", 59.2187, 39.8886),
    City("Ярославль", "Ярославская обл.", 57.6299, 39.8737),
    City("Тюмень", "Тюменская обл.", 57.1522, 65.5272),
    City("Саратов", "Саратовская обл.", 51.5336, 46.0343),
)
SYNONYMS: dict[str, str] = {
    "питер": "Санкт-Петербург",
    "спб": "Санкт-Петербург",
    "санкт петербург": "Санкт-Петербург",
    "петербург": "Санкт-Петербург",
    "мск": "Москва",
    "нск": "Новосибирск",
    "екб": "Екатеринбург",
}
# Россия и соседние страны: результаты поиска из других стран не показываются.
ALLOWED_COUNTRIES = ("RU", "BY", "KZ", "UA", "GE", "AM", "AZ", "UZ", "KG", "TJ", "MD", "LV", "LT", "EE", "FI", "MN")
SUGGESTIONS = 3
SIMILARITY = 0.7

_STRIP = re.compile(r"[.\"'«»„“”`]")
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """«  МОСКВА. » → «москва»; ё = е, дефис = пробел, точки и кавычки убираются."""
    clean = _STRIP.sub("", text.lower().replace("ё", "е").replace("-", " ").replace("—", " "))
    return _SPACES.sub(" ", clean).strip()


def resolve_local(text: str) -> tuple[str, City | None]:
    """Название для поиска и, если это город с кнопки, — сам город без запроса к сервису."""
    key = normalize(text)
    name = SYNONYMS.get(key)
    query = name or text.strip()
    target = normalize(query)
    city = next((c for c in BUTTON_CITIES if normalize(c.name) == target), None)
    return query, city


def short_region(region: str | None) -> str:
    """«Мурманская область» → «Мурманская обл.»."""
    if not region:
        return ""
    return region.replace(" область", " обл.").replace("Область ", "обл. ")


def suggest(text: str, limit: int = SUGGESTIONS) -> list[City]:
    """До трёх похожих по написанию городов: «Масква» → Москва."""
    key = normalize(text)
    scored = [(SequenceMatcher(None, key, normalize(c.name)).ratio(), c) for c in KNOWN_CITIES]
    good = sorted((pair for pair in scored if pair[0] >= SIMILARITY), key=lambda pair: -pair[0])
    return [city for _, city in good[:limit]]


def pick_matches(text: str, found: list[City]) -> list[City]:
    """Из ответа сервиса: только разрешённые страны, без повторов; сначала точные совпадения названия."""
    allowed = [c for c in found if c.country_code in ALLOWED_COUNTRIES]
    unique: list[City] = []
    for city in allowed:
        if all((city.name, city.region) != (u.name, u.region) for u in unique):
            unique.append(city)
    exact = [c for c in unique if normalize(c.name) == normalize(text)]
    return exact or unique[:5]
