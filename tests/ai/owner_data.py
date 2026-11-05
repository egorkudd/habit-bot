"""Данные владельца для эталонных фраз (раздел 6.2): рецепты, продукты, привычки, зарядка и записи 03.11.2026."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from habit_bot.modules.food.domain.nutrition import Nutrients, Unit

TODAY = date(2026, 11, 3)


async def fill(app: Any, actor: Any, clock: Any) -> None:
    food = app.ctx.services["food"]
    for name, unit, values, price in (
        ("Коктейль", Unit.PORTION, (322, 26, 9, 39), Decimal(140)),
        ("Творог ужин", Unit.PORTION, (421, Decimal("52.4"), Decimal("15.6"), Decimal("17.8")), Decimal(250)),
        ("Творог 5%", Unit.GRAMS, (121, 17, 5, Decimal("1.8")), None),
        ("Куриное бедро", Unit.PIECE, (250, 23, 17, 0), None),
        ("Гречка сухая (пакет 80 г)", Unit.PIECE, (Decimal("288.8"), Decimal("9.6"), Decimal("2.72"),
                                                   Decimal("51.36")), None),
        ("Пельмени", Unit.GRAMS, (260, 11, 12, 28), None),
    ):
        await food.create_item(actor, name=name, kind="recipe" if unit is Unit.PORTION else "product", unit=unit,
                               nutrients=Nutrients.of(*values), price=price)
    items = {i.name: i for i in await food.items(actor)}
    clock.current = datetime(2026, 11, 3, 6, 12, tzinfo=UTC)  # 09:12 по Москве
    await food.log_item(actor, items["Коктейль"].public_id, quantity=Decimal(1), day=TODAY)
    clock.current = datetime(2026, 11, 3, 9, 30, tzinfo=UTC)
    await food.log_item(actor, items["Творог ужин"].public_id, quantity=Decimal(1), day=TODAY)
    clock.current = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    habits = app.ctx.services["habits"]
    for key in ("eyes", "water", "vitamins", "steps"):
        await habits.from_template(actor, key)
    warmup = app.ctx.services["warmup"]
    exercises = await warmup.use_default_set(actor)
    for values in ((50, 50, 345, 25), (50, 50, 360, 25)):
        await warmup.record(actor, {e.public_id: v for e, v in zip(exercises, values, strict=True)}, day=TODAY)
