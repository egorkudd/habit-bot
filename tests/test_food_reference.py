"""Справочник еды (правки 1.0.4): данные, поиск по тексту, выбор по названию, пересчёт КБЖУ."""

from decimal import Decimal

import pytest

from habit_bot.modules.food.domain import reference as r
from habit_bot.modules.food.domain.nutrition import Unit


def test_data_is_consistent() -> None:
    """Названия с сетью не повторяются; калорийность сходится с Б·4 + Ж·9 + У·4 в пределах 15%; у каждой сети есть
    источник; напитков нет."""
    titles = [f.title for f in r.REFERENCE]
    assert len(titles) == len(set(titles))
    assert len(r.STAPLES) >= 50 and len(r.FAST_FOOD) >= 60
    for food in r.REFERENCE:
        atwater = 4 * food.protein + 9 * food.fat + 4 * food.carbs
        assert abs(atwater - food.kcal) <= 0.15 * food.kcal, food.title
        assert food.brand is None or food.brand in r.SOURCES
    assert {f.brand for f in r.FAST_FOOD} == set(r.SOURCES) == set(r.BRAND_WORDS)
    words = {w for t in titles for w in t.casefold().split()}
    assert not words & {"кофе", "чай", "кола", "сок", "молоко", "коктейль", "латте"}


def test_cooked_by_default_dry_only_by_pack() -> None:
    assert r.find("гречка").name == "Гречка варёная"
    assert r.find("пакет гречи").unit is Unit.PIECE
    assert r.find("рис").name == "Рис белый варёный"


def test_find() -> None:
    assert r.find("Воппер (Burger King)").brand == r.BK
    assert r.find("  воппер (burger king) ").name == "Воппер"
    assert r.find("Воппер").title == "Воппер (Burger King)"   # единственный — без сети
    assert r.find("Чизбургер") is None                         # у трёх сетей — нужна сеть
    assert r.find("Чизбургер (Ростикс)").unit is Unit.PIECE
    assert r.find("Свёкла с черносливом") is None
    assert r.find("Твистер", ()) is None


def test_search_ranks_and_limits() -> None:
    found = [f.title for f in r.search("вчера 200 г гречки и воппер в бургер кинге")]
    assert found[0] in ("Воппер (Burger King)", "Гречка варёная") and "Гречка варёная" in found
    assert "Воппер (Burger King)" in found[:3]
    assert all(f.brand in (None, r.BK) for f in r.search("воппер бургер кинг"))
    assert [f.title for f in r.search("твистер в ростиксе")][:2] == ["Твистер (Ростикс)", "Твистер острый (Ростикс)"]
    assert len(r.search("теремок", limit=5)) == 5
    assert r.search("да, ок") == [] and r.search("") == []


def test_scaled_and_describe() -> None:
    buckwheat = r.find("Гречка варёная")
    assert buckwheat.scaled(Decimal(200)).values() == (Decimal("220.00"), Decimal("8.40"), Decimal("2.20"),
                                                       Decimal("42.60"))
    assert buckwheat.describe() == "Гречка варёная — на 100 г: 110 ккал, Б 4.2, Ж 1.1, У 21.3"
    whopper = r.find("Воппер (Burger King)")
    assert whopper.scaled(Decimal(2)).kcal == Decimal(1440)
    assert whopper.describe() == "Воппер (Burger King) — на 1 шт (274 г): 720 ккал, Б 27, Ж 44, У 53"
    nuggets = r.find("Кинг Наггетс (Burger King)")
    assert nuggets.describe().startswith("Кинг Наггетс (Burger King) — на порцию (9 шт, 135 г): 380 ккал")
    assert r.find("Биг Спешиал").describe() == "Биг Спешиал (Вкусно и точка) — на 1 шт: 812 ккал, Б 44, Ж 48, У 50"


def test_rostics_per_piece_from_per_100g() -> None:
    twister = r.find("Твистер (Ростикс)")
    assert (twister.portion_label, twister.kcal, twister.protein) == ("184 г", 443.4, 20.8)


@pytest.mark.parametrize(("word", "stem"), [("гречки", "гречк"), ("рис", "рис"), ("ростиксе", "рости"),
                                            ("кинге", "кинг"), ("ая", "ая")])
def test_stem(word: str, stem: str) -> None:
    assert r._stem(word) == stem
