"""Общий каталог продуктов (раздел 6.1): фикстура кода, загружается в базу при старте бота, без цен."""

from __future__ import annotations

from dataclasses import dataclass

from habit_bot.modules.food.domain.nutrition import Unit


@dataclass(frozen=True, slots=True)
class CatalogProduct:
    key: str
    name: str
    unit: Unit
    kcal: float
    protein: float
    fat: float
    carbs: float
    portion_label: str | None = None


CATALOG: tuple[CatalogProduct, ...] = (
    CatalogProduct("chicken_thigh", "Куриное бедро", Unit.PIECE, 250, 23, 17, 0),
    CatalogProduct("chicken_cooked", "Курица готовая", Unit.GRAMS, 220, 28, 11, 0),
    CatalogProduct("pasta_boiled", "Макароны отварные", Unit.GRAMS, 158, 5.8, 0.9, 30.9),
    CatalogProduct("buckwheat_pack", "Гречка сухая (пакет 80 г)", Unit.PIECE, 288.8, 9.6, 2.72, 51.36),
    CatalogProduct("banana", "Банан", Unit.PIECE, 105, 1.3, 0.4, 27),
    CatalogProduct("protein_30g", "Протеин", Unit.PORTION, 111, 23.5, 2, 2.6, "30 г"),
    CatalogProduct("chickenburger_rostics", "Чикенбургер Новый (Ростикс)", Unit.PIECE, 335, 10.9, 15.9, 37.1),
    CatalogProduct("chef_basket_rostics", "Шеф Баскет (Ростикс)", Unit.PIECE, 731, 56.5, 43.4, 28.6),
    CatalogProduct("nuggets_vit", "Наггетсы (Вкусно и точка)", Unit.PORTION, 179, 11, 9, 12, "4 шт"),
    CatalogProduct("ham_toast_vit", "Тост с ветчиной (Вкусно и точка)", Unit.PIECE, 265, 14, 11, 28),
    CatalogProduct("fresh_muffin_vit", "Фреш Маффин (Вкусно и точка)", Unit.PIECE, 368, 18, 20, 28),
    CatalogProduct("pelmeni", "Пельмени", Unit.GRAMS, 260, 11, 12, 28),
)
