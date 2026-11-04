"""Сценарии модуля food без Telegram (раздел 9 «Архитектура»: тот же результат, что через кнопки) и изоляция."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from habit_bot.kernel.errors import AppError
from habit_bot.modules.food.catalog import CATALOG
from habit_bot.modules.food.domain.nutrition import Nutrients, Unit
from habit_bot.modules.food.domain.other_line import parse_other_line
from tests.conftest import OTHER_ID, register_active

DAY = date(2026, 11, 3)


async def _two_users(app: Any) -> tuple[Any, Any]:
    admin = await register_active(app)
    invite = await app.ctx.services["users.invites"].create(admin, max_uses=1, days=1)
    guest = await register_active(app, OTHER_ID, invite_code=invite.code, name="Аня")
    return admin, guest


async def test_catalog_seed_is_idempotent(app: Any) -> None:
    """Каталог (раздел 6.1) загружается при старте; повторная загрузка ничего не меняет."""
    food = app.ctx.services["food"]
    assert len(await food.catalog()) == len(CATALOG)
    assert await food.seed_catalog() == 0


async def test_starter_kit_copies_catalog_once(app: Any) -> None:
    """«Базовые продукты» из анкеты: весь каталог в личный список — один раз."""
    actor = await register_active(app)
    profiles, food = app.ctx.services["users.profiles"], app.ctx.services["food"]
    async with app.ctx.uow() as uow:
        from sqlalchemy import select

        from habit_bot.modules.users.models import Profile

        profile = (await uow.session.execute(select(Profile))).scalar_one()
        profile.starter_kit = ["food", "habits"]
    assert await food.apply_starter_kit(actor) == len(CATALOG)
    assert await food.apply_starter_kit(actor) == 0
    assert len(await food.items(actor)) == len(CATALOG)
    assert (await profiles.profile(actor)).starter_kit == ("habits",)


async def test_isolation(app: Any) -> None:
    """Раздел 9 «Изоляция»: B не видит рецептов и записей A и не может записать еду по его рецепту."""
    a, b = await _two_users(app)
    food = app.ctx.services["food"]
    recipe = await food.create_item(a, name="Коктейль", kind="recipe", unit=Unit.PORTION,
                                    nutrients=Nutrients.of(322, 26, 9, 39), price=Decimal(140))
    entry = await food.log_item(a, recipe.public_id, quantity=Decimal(1), day=DAY)
    assert await food.items(b) == []
    assert await food.entries(b, DAY) == []
    assert await food.entry(b, entry.public_id) is None
    with pytest.raises(AppError):
        await food.log_item(b, recipe.public_id, quantity=Decimal(1), day=DAY)
    with pytest.raises(AppError):
        await food.update_item(b, recipe.public_id, name="Моё")
    assert await food.delete_entry(b, entry.public_id) is None
    assert await food.item(a, "не-uuid") is None
    assert await food.entry(a, "не-uuid") is None
    assert await food.day_of(b, entry.public_id) is None
    same_name = await food.create_item(b, name="Коктейль", kind="recipe", unit=Unit.PORTION,
                                       nutrients=Nutrients.of(1, 1, 1, 1), price=None)
    assert same_name.name == "Коктейль"  # одинаковые названия у разных людей — не дубль


async def test_without_telegram_same_result(app: Any) -> None:
    """Раздел 9: сценарии записи еды без Telegram дают тот же результат, что через кнопки."""
    actor = await register_active(app)
    food = app.ctx.services["food"]
    other = await food.log_other(actor, parse_other_line("Маффин 320 4,5 15 41"), day=DAY, request_id="r1")
    again = await food.log_other(actor, parse_other_line("Маффин 320 4,5 15 41"), day=DAY, request_id="r1")
    assert other == again and len(await food.entries(actor, DAY)) == 1
    with pytest.raises(AppError) as err:
        await food.set_quantity(actor, other.public_id, Decimal(30))
    assert err.value.code == "INPUT-RANGE"
    half = await food.multiply(actor, other.public_id, Decimal("0.5"))
    assert half.nutrients == Nutrients.of(160, "2.25", "7.5", "20.5")
    recipe = await food.save_other_as_recipe(actor, other.public_id)
    assert recipe.nutrients == Nutrients.of(320, "4.5", 15, 41)
    assert (await food.update_item(actor, recipe.public_id, name="маффин")).name == "маффин"  # своё же имя — не дубль
    renamed = await food.save_other_as_recipe(actor, other.public_id, name="Маффин 2")
    assert renamed.name == "Маффин 2"
    with pytest.raises(AppError):
        await food.update_item(actor, renamed.public_id, name="МАФФИН")
    with pytest.raises(AppError):
        await food.multiply(actor, "0" * 32, Decimal(2))
    with pytest.raises(AppError):
        await food.add_from_catalog(actor, "0" * 32)
