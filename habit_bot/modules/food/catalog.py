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


# Правки 1.0.2: базовый набор владельца. Значения — типичные из таблиц состава (на 1 шт / пакет или на 100 г).
# Старый набор (бедро, курица готовая, макароны, протеин, фастфуд, пельмени) убран миграцией 0014 — и у тех, кому
# его скопировала анкета («Базовые продукты»).
CATALOG: tuple[CatalogProduct, ...] = (
    CatalogProduct("buckwheat_pack", "Гречка сухая (пакет 80 г)", Unit.PIECE, 288.8, 9.6, 2.72, 51.36),
    CatalogProduct("banana", "Банан", Unit.PIECE, 105, 1.3, 0.4, 27),
    CatalogProduct("chicken_fillet", "Куриное филе", Unit.GRAMS, 113, 23.6, 1.9, 0.4),
    CatalogProduct("cottage_cheese_5", "Творог 5%", Unit.GRAMS, 121, 17.2, 5, 1.8),
    CatalogProduct("rice_pack", "Рис сухой (пакет 80 г)", Unit.PIECE, 275.2, 5.36, 0.56, 63.12),
    CatalogProduct("potato", "Картофель", Unit.GRAMS, 77, 2, 0.4, 16.3),
)
