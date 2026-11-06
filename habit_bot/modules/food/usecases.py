"""Еда (раздел 3.2, 4.2): каталог, свои рецепты и продукты, записи, итог дня. Без aiogram.

Все запросы фильтруются по ``user_id`` (раздел 4.4); элементы каталога (``user_id`` пустой) только читаются и
копируются. Изменяющие сценарии принимают ``request_id``: повтор того же апдейта не создаёт вторую запись.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_bot.kernel.clock import Clock
from habit_bot.kernel.db import UowFactory
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.idempotency import IdempotencyStore
from habit_bot.kernel.identity import Actor
from habit_bot.modules.food.catalog import CATALOG
from habit_bot.modules.food.domain.nutrition import (
    DayTotals,
    Nutrients,
    Unit,
    check_quantity,
    day_totals,
    entry_values,
    rescale,
)
from habit_bot.modules.food.domain.other_line import OtherLine
from habit_bot.modules.food.models import FoodEntry, FoodItem
from habit_bot.modules.users.public import Profiles

log = logging.getLogger(__name__)
FREQUENT_DAYS = 14
RECIPE, PRODUCT = "recipe", "product"


@dataclass(frozen=True, slots=True)
class ItemView:
    public_id: str
    name: str
    kind: str
    unit: Unit
    portion_label: str | None
    nutrients: Nutrients
    price: Decimal | None
    active: bool
    is_catalog: bool
    composition: str = ""


@dataclass(frozen=True, slots=True)
class EntryView:
    public_id: str
    day: date
    name: str
    quantity: Decimal
    unit: Unit
    portion_label: str | None
    nutrients: Nutrients
    price: Decimal | None
    source: str
    item_public_id: str | None = None
    logged_at: datetime | None = None


def _dec(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _uuid(public_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(hex=public_id)
    except (ValueError, TypeError):
        return None


def item_view(item: FoodItem) -> ItemView:
    return ItemView(
        item.public_id.hex, item.name, item.kind, Unit(item.unit), item.portion_label,
        Nutrients.of(item.kcal, item.protein, item.fat, item.carbs), _dec(item.price), item.active,
        item.user_id is None, item.composition,
    )


def entry_view(entry: FoodEntry, item_public_id: str | None = None) -> EntryView:
    return EntryView(
        entry.public_id.hex, entry.day, entry.name, Decimal(str(entry.quantity)), Unit(entry.unit),
        entry.portion_label, Nutrients.of(entry.kcal, entry.protein, entry.fat, entry.carbs), _dec(entry.price),
        entry.source, item_public_id, entry.logged_at,
    )


class Food:
    def __init__(self, *, uow: UowFactory, clock: Clock, idempotency: IdempotencyStore, profiles: Profiles) -> None:
        self._uow = uow
        self._clock = clock
        self._idempotency = idempotency
        self._profiles = profiles

    # --- каталог ---
    async def seed_catalog(self) -> int:
        """Загружает общий каталог (раздел 6.1); повторный запуск только обновляет значения."""
        changed = 0
        async with self._uow() as uow:
            existing = {i.catalog_key: i for i in (await uow.session.execute(
                select(FoodItem).where(FoodItem.catalog_key.is_not(None))
            )).scalars().all()}
            for product in CATALOG:
                item = existing.get(product.key) or FoodItem(catalog_key=product.key, kind=PRODUCT, composition="")
                values = (product.name, product.unit.value, product.portion_label, product.kcal, product.protein,
                          product.fat, product.carbs)
                current = (item.name, item.unit, item.portion_label, item.kcal, item.protein, item.fat, item.carbs)
                if item.id is None or current != values:
                    (item.name, item.unit, item.portion_label, item.kcal, item.protein, item.fat,
                     item.carbs) = values
                    item.active = True
                    uow.session.add(item)
                    changed += 1
        return changed

    async def catalog(self) -> list[ItemView]:
        async with self._uow() as uow:
            rows = (await uow.session.execute(
                select(FoodItem).where(FoodItem.user_id.is_(None)).order_by(FoodItem.name)
            )).scalars().all()
            return [item_view(i) for i in rows]

    async def add_from_catalog(self, actor: Actor, catalog_public_id: str) -> tuple[ItemView, bool]:
        """«Добавить к себе»: копия продукта в личный список. Возвращает (продукт, добавлен ли сейчас)."""
        public = _uuid(catalog_public_id)
        async with self._uow() as uow:
            source = (await uow.session.execute(
                select(FoodItem).where(FoodItem.public_id == public, FoodItem.user_id.is_(None))
            )).scalar_one_or_none() if public else None
            if source is None:
                raise AppError("UI-STALE")
            existing = (await uow.session.execute(
                select(FoodItem).where(FoodItem.user_id == actor.user_id, FoodItem.source_catalog_id == source.id)
            )).scalar_one_or_none()
            if existing is not None:
                existing.active = True
                return item_view(existing), False
            copy = self._copy(source, actor.user_id)
            uow.session.add(copy)
            await uow.session.flush()
            return item_view(copy), True

    @staticmethod
    def _copy(source: FoodItem, user_id: int) -> FoodItem:
        return FoodItem(
            user_id=user_id, name=source.name, kind=PRODUCT, composition=source.composition, unit=source.unit,
            portion_label=source.portion_label, kcal=source.kcal, protein=source.protein, fat=source.fat,
            carbs=source.carbs, price=None, active=True, source_catalog_id=source.id,
        )

    async def apply_starter_kit(self, actor: Actor) -> int:
        """«Базовые продукты» из анкеты: весь каталог в личный список — один раз (раздел 3.0, шаг 12)."""
        if not await self._profiles.consume_starter(actor, "food"):
            return 0
        added = 0
        for item in await self.catalog():
            _, new = await self.add_from_catalog(actor, item.public_id)
            added += int(new)
        return added

    # --- свои рецепты и продукты ---
    async def items(self, actor: Actor, *, include_hidden: bool = False) -> list[ItemView]:
        """Свои рецепты и продукты; сверху — частые за 14 дней (раздел 3.2)."""
        since = self._clock.now().date() - timedelta(days=FREQUENT_DAYS)
        async with self._uow() as uow:
            query = select(FoodItem).where(FoodItem.user_id == actor.user_id)
            if not include_hidden:
                query = query.where(FoodItem.active.is_(True))
            items = (await uow.session.execute(query)).scalars().all()
            rows = (await uow.session.execute(
                select(FoodEntry.food_item_id, func.count()).where(
                    FoodEntry.user_id == actor.user_id, FoodEntry.deleted_at.is_(None), FoodEntry.day >= since,
                    FoodEntry.food_item_id.is_not(None),
                ).group_by(FoodEntry.food_item_id)
            )).all()
            used: Counter[int] = Counter({int(item_id): int(count) for item_id, count in rows if item_id is not None})
            ordered = sorted(items, key=lambda i: (-used.get(i.id, 0), i.name.lower()))
            return [item_view(i) for i in ordered]

    async def item(self, actor: Actor, public_id: str) -> ItemView | None:
        async with self._uow() as uow:
            found = await self._own_item(uow.session, actor, public_id)
            return item_view(found) if found else None

    async def _own_item(self, session: AsyncSession, actor: Actor, public_id: str) -> FoodItem | None:
        public = _uuid(public_id)
        if public is None:
            return None
        return (await session.execute(
            select(FoodItem).where(FoodItem.public_id == public, FoodItem.user_id == actor.user_id)
        )).scalar_one_or_none()

    async def _check_name(self, session: AsyncSession, actor: Actor, name: str, skip_id: int | None = None) -> None:
        # Сравнение без учёта регистра — в Python: lower() в SQLite не знает кириллицу.
        rows = (await session.execute(
            select(FoodItem.id, FoodItem.name).where(FoodItem.user_id == actor.user_id)
        )).all()
        wanted = name.strip().casefold()
        if [i for i, n in rows if n.casefold() == wanted and i != skip_id]:
            raise AppError("INPUT-DUPLICATE", name=name.strip())

    async def create_item(
        self, actor: Actor, *, name: str, kind: str, unit: Unit, nutrients: Nutrients, price: Decimal | None,
        portion_label: str | None = None, composition: str = "",
    ) -> ItemView:
        async with self._uow() as uow:
            await self._check_name(uow.session, actor, name)
            kcal, protein, fat, carbs = (float(v) for v in nutrients.values())
            item = FoodItem(
                user_id=actor.user_id, name=name.strip(), kind=kind, composition=composition, unit=unit.value,
                portion_label=portion_label, kcal=kcal, protein=protein, fat=fat, carbs=carbs,
                price=None if price is None else float(price), active=True,
            )
            uow.session.add(item)
            await uow.session.flush()
            return item_view(item)

    async def update_item(
        self, actor: Actor, public_id: str, *, nutrients: Nutrients | None = None, price: Any = ...,
        name: str | None = None, active: bool | None = None,
    ) -> ItemView:
        """Правка рецепта или продукта; прошлые записи не меняются — у них своя копия значений."""
        async with self._uow() as uow:
            item = await self._own_item(uow.session, actor, public_id)
            if item is None:
                raise AppError("UI-STALE")
            if name is not None:
                await self._check_name(uow.session, actor, name, skip_id=item.id)
                item.name = name.strip()
            if nutrients is not None:
                item.kcal, item.protein, item.fat, item.carbs = (float(v) for v in nutrients.values())
            if price is not ...:
                item.price = None if price is None else float(price)
            if active is not None:
                item.active = active
            await uow.session.flush()
            return item_view(item)

    # --- записи ---
    async def _once(self, actor: Actor, request_id: str | None, action: Any) -> dict[str, Any]:
        async with self._uow() as uow:
            if request_id is None:
                result: dict[str, Any] = await action(uow.session)
                return result
            return await self._idempotency.run_once(
                uow.session, user_id=actor.user_id, request_id=request_id, now=self._clock.now(),
                action=lambda: action(uow.session),
            )

    async def log_item(
        self, actor: Actor, item_public_id: str, *, quantity: Decimal, day: date, request_id: str | None = None,
    ) -> EntryView:
        """Запись еды из своего списка: количество — порции, граммы или штуки по единице продукта."""

        async def action(session: AsyncSession) -> dict[str, Any]:
            item = await self._own_item(session, actor, item_public_id)
            if item is None:
                raise AppError("UI-STALE")
            unit = Unit(item.unit)
            check_quantity(unit, quantity)
            per_unit = Nutrients.of(item.kcal, item.protein, item.fat, item.carbs)
            values, price = entry_values(per_unit, _dec(item.price), unit, quantity)
            entry = self._entry(actor, day, item.name, quantity, unit, item.portion_label, values, price, "button")
            entry.food_item_id = item.id
            session.add(entry)
            await session.flush()
            return {"entry": entry.public_id.hex}

        result = await self._once(actor, request_id, action)
        view = await self.entry(actor, result["entry"])
        assert view is not None
        return view

    async def log_other(self, actor: Actor, line: OtherLine, *, day: date, request_id: str | None = None,
                        ) -> EntryView:
        """«Другое»: запись одной строкой, без рецепта (раздел 3.2)."""

        async def action(session: AsyncSession) -> dict[str, Any]:
            values = Nutrients(*(v.quantize(Decimal("0.01")) for v in line.nutrients.values()))
            entry = self._entry(actor, day, line.name, Decimal(1), Unit.PORTION, None, values, line.price, "other")
            session.add(entry)
            await session.flush()
            return {"entry": entry.public_id.hex}

        result = await self._once(actor, request_id, action)
        view = await self.entry(actor, result["entry"])
        assert view is not None
        return view

    def _entry(
        self, actor: Actor, day: date, name: str, quantity: Decimal, unit: Unit, portion_label: str | None,
        values: Nutrients, price: Decimal | None, source: str,
    ) -> FoodEntry:
        kcal, protein, fat, carbs = (float(v) for v in values.values())
        return FoodEntry(
            user_id=actor.user_id, day=day, logged_at=self._clock.now(), name=name, quantity=float(quantity),
            unit=unit.value, portion_label=portion_label, kcal=kcal, protein=protein, fat=fat, carbs=carbs,
            price=None if price is None else float(price), source=source,
        )

    async def _own_entry(self, session: AsyncSession, actor: Actor, public_id: str) -> FoodEntry | None:
        public = _uuid(public_id)
        if public is None:
            return None
        return (await session.execute(
            select(FoodEntry).where(FoodEntry.public_id == public, FoodEntry.user_id == actor.user_id,
                                    FoodEntry.deleted_at.is_(None))
        )).scalar_one_or_none()

    async def entry(self, actor: Actor, public_id: str) -> EntryView | None:
        async with self._uow() as uow:
            found = await self._own_entry(uow.session, actor, public_id)
            if found is None:
                return None
            item_id = None
            if found.food_item_id is not None:
                item = await uow.session.get(FoodItem, found.food_item_id)
                item_id = item.public_id.hex if item else None
            return entry_view(found, item_id)

    async def set_quantity(self, actor: Actor, public_id: str, quantity: Decimal) -> EntryView:
        async with self._uow() as uow:
            entry = await self._own_entry(uow.session, actor, public_id)
            if entry is None:
                raise AppError("UI-STALE")
            check_quantity(Unit(entry.unit), quantity)
            old = Decimal(str(entry.quantity))
            values, price = rescale(Nutrients.of(entry.kcal, entry.protein, entry.fat, entry.carbs),
                                    _dec(entry.price), old, quantity)
            entry.quantity = float(quantity)
            entry.kcal, entry.protein, entry.fat, entry.carbs = (float(v) for v in values.values())
            entry.price = None if price is None else float(price)
            return entry_view(entry)

    async def multiply(self, actor: Actor, public_id: str, factor: Decimal) -> EntryView:
        """«×0,5», «×2» под карточкой записи."""
        current = await self.entry(actor, public_id)
        if current is None:
            raise AppError("UI-STALE")
        return await self.set_quantity(actor, public_id, current.quantity * factor)

    async def restore_entry(self, actor: Actor, public_id: str) -> bool:
        """Вернуть удалённую запись («↩️ Отменить всё» после команды текстом, раздел 3.10)."""
        public = _uuid(public_id)
        if public is None:
            return False
        async with self._uow() as uow:
            entry = (await uow.session.execute(select(FoodEntry).where(
                FoodEntry.public_id == public, FoodEntry.user_id == actor.user_id))).scalar_one_or_none()
            if entry is None:
                return False
            entry.deleted_at = None
            return True

    async def delete_item(self, actor: Actor, public_id: str) -> bool:
        """Удалить свой рецепт совсем (отмена его создания командой текстом); записи остаются без ссылки."""
        async with self._uow() as uow:
            item = await self._own_item(uow.session, actor, public_id)
            if item is None:
                return False
            await uow.session.delete(item)
            return True

    async def delete_entry(self, actor: Actor, public_id: str) -> EntryView | None:
        """Удалённая запись не видна в боте и в итогах; через 30 дней стирается совсем."""
        async with self._uow() as uow:
            entry = await self._own_entry(uow.session, actor, public_id)
            if entry is None:
                return None
            entry.deleted_at = self._clock.now()
            return entry_view(entry)

    async def entries(self, actor: Actor, day: date) -> list[EntryView]:
        async with self._uow() as uow:
            rows = (await uow.session.execute(
                select(FoodEntry).where(FoodEntry.user_id == actor.user_id, FoodEntry.day == day,
                                        FoodEntry.deleted_at.is_(None)).order_by(FoodEntry.logged_at, FoodEntry.id)
            )).scalars().all()
            return [entry_view(e) for e in rows]

    async def totals(self, actor: Actor, day: date) -> DayTotals:
        return day_totals((e.nutrients, e.price) for e in await self.entries(actor, day))

    async def entries_between(self, actor: Actor, start: date, end: date) -> list[EntryView]:
        """Записи еды за период по порядку — для экспорта."""
        async with self._uow() as uow:
            rows = (await uow.session.execute(
                select(FoodEntry).where(FoodEntry.user_id == actor.user_id, FoodEntry.day >= start,
                                        FoodEntry.day <= end, FoodEntry.deleted_at.is_(None))
                .order_by(FoodEntry.day, FoodEntry.logged_at, FoodEntry.id)
            )).scalars().all()
            return [entry_view(e) for e in rows]

    async def daily_totals(self, actor: Actor, start: date, end: date) -> dict[date, DayTotals]:
        """Итоги по дням периода одним запросом — для светофора и экспорта (дни без записей не попадают)."""
        async with self._uow() as uow:
            rows = (await uow.session.execute(
                select(FoodEntry).where(FoodEntry.user_id == actor.user_id, FoodEntry.day >= start,
                                        FoodEntry.day <= end, FoodEntry.deleted_at.is_(None))
            )).scalars().all()
        by_day: dict[date, list[EntryView]] = {}
        for row in rows:
            by_day.setdefault(row.day, []).append(entry_view(row))
        return {d: day_totals((e.nutrients, e.price) for e in found) for d, found in by_day.items()}

    async def save_other_as_recipe(
        self, actor: Actor, entry_public_id: str, *, name: str | None = None, overwrite: bool = False,
    ) -> ItemView:
        """«Сохранить как рецепт» из записи «Другое»; дубль названия — «Обновить» или другое имя."""
        current = await self.entry(actor, entry_public_id)
        if current is None:
            raise AppError("UI-STALE")
        per_portion = current.nutrients.scaled(Decimal(1) / current.quantity)
        price = None if current.price is None else (current.price / current.quantity).quantize(Decimal("0.01"))
        recipe_name = (name or current.name).strip()
        if overwrite:
            existing = [i for i in await self.items(actor, include_hidden=True)
                        if i.name.lower() == recipe_name.lower()]
            if existing:
                return await self.update_item(actor, existing[0].public_id, nutrients=per_portion, price=price,
                                              active=True)
        return await self.create_item(actor, name=recipe_name, kind=RECIPE, unit=Unit.PORTION,
                                      nutrients=per_portion, price=price)

    # --- перенос (раздел 3.7) ---
    async def day_of(self, actor: Actor, public_id: str) -> date | None:
        found = await self.entry(actor, public_id)
        return found.day if found else None

    async def move(self, actor: Actor, public_id: str, day: date) -> None:
        async with self._uow() as uow:
            entry = await self._own_entry(uow.session, actor, public_id)
            if entry is not None:
                entry.day = day
