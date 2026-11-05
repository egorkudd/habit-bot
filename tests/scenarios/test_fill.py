"""Поведенческие сценарии: первоначальное заполнение через ИИ на данных владельца (раздел 3.12, 6.2; критерии
раздела 9 «Первоначальное заполнение»). Модель — на записанных ответах."""

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from tests.conftest import ADMIN_ID
from tests.fakes import FakeLlm
from tests.scenarios.conftest import pass_onboarding
from tests.scenarios.harness import Persona, World

RECIPES = [  # раздел 6.2, на 1 порцию
    ("Обед", "Усреднённый комплексный обед в столовой", "701.6", "40.04", "32.22", "61.5", 330),
    ("Коктейль", "Молоко 200 мл, банан, протеин 23 г", "322", "26", "9", "39", 140),
    ("Творог ужин", "Творог 5% 200 г, йогурт 280 г", "421.04", "52.4", "15.6", "17.76", 250),
    ("Пакет гречи", "Гречка 80 г", "288.8", "9.6", "2.72", "51.36", 20),
]
RECIPES_TEXT = "Мои рецепты: " + "; ".join(
    f"{n} — {c}, {k} ккал, Б {p}, Ж {f}, У {u}, {price} ₽" for n, c, k, p, f, u, price in RECIPES)
GOALS_TEXT = "цели: с 22.09.2026 2410/140/70/305, с 09.10.2026 2800/160/80/360"
LONG_TEXT = "Мои продукты: " + "; ".join(f"Продукт {i} — {100 + i} ккал, Б 10, Ж 5, У 12" for i in range(1, 91))


def recipe_actions() -> list[dict[str, Any]]:
    return [{"type": "recipe.create", "name": n, "composition": c, "kcal": float(k), "protein": float(p),
             "fat": float(f), "carbs": float(u), "price": price} for n, c, k, p, f, u, price in RECIPES]


@pytest.fixture
async def fill_world(settings: Any, fake_session: Any, clock: Any, geocoder: Any) -> AsyncIterator[World]:
    llm = FakeLlm({
        "Мои рецепты:": {"actions": recipe_actions()},
        "цели:": {"actions": [
            {"type": "goal.set", "start_date": "2026-09-22", "kcal": 2410, "protein": 140, "fat": 70, "carbs": 305},
            {"type": "goal.set", "start_date": "2026-10-09", "kcal": 2800, "protein": 160, "fat": 80, "carbs": 360},
        ]},
        "Мои продукты:": {"actions": [
            {"type": "recipe.create", "name": f"Продукт {i}", "unit": "100g", "kcal": 100 + i, "protein": 10,
             "fat": 5, "carbs": 12} for i in range(1, 41)]},
    })
    w = await World(settings, fake_session, clock, geocoder, llm=llm).start()
    yield w
    await w.stop()


@pytest.fixture
async def me(fill_world: World) -> Persona:
    user = fill_world.person(ADMIN_ID, "Егор")
    await pass_onboarding(user)
    await user.tap("☰ Ещё")
    await user.tap("⚙️ Настройки")
    return user


async def test_s121_owner_recipes_goals_and_repeat(fill_world: World, me: Persona) -> None:
    """S-121. Раздел 9: 4 рецепта владельца из 6.2 одним сообщением → карточка «Рецепты: 4»; после подтверждения
    КБЖУ и цена совпадают с таблицей; две цели «с 22.09 … с 09.10» создают обе — остаток за 01.10 считается от 2410,
    за 22.10 — от 2800; повторная отправка рецептов предлагает «обновлю / Пропустить», дублей нет."""
    await me.tap("✍️ Заполнить с помощью ИИ")
    card = await me.say(RECIPES_TEXT)
    assert card.startswith("Понял так:\nРецепты: 4\n1. 🍽 Рецепт «Обед»")
    assert "Убрать 4" in me.labels()
    await me.tap("✅ Выполнить всё")
    actor = await fill_world.service("users.sign_in").execute(ADMIN_ID, "")
    items = {i.name: i for i in await fill_world.service("food").items(actor, include_hidden=True)}
    for name, _, k, p, f, u, price in RECIPES:
        n = items[name].nutrients
        assert (n.kcal, n.protein, n.fat, n.carbs, items[name].price) == (
            Decimal(k), Decimal(p), Decimal(f), Decimal(u), Decimal(price)), name

    await me.tap("☰ Ещё")
    await me.tap("⚙️ Настройки")
    await me.tap("✍️ Заполнить с помощью ИИ")
    assert (await me.say(GOALS_TEXT)).startswith("Понял так:\nЦели: 2\n1. 🎯 Цель КБЖУ с 22.09: 2 410 ккал")
    await me.tap("✅ Выполнить всё")
    profiles = fill_world.service("users.profiles")
    assert (await profiles.goal_on(actor, date(2026, 10, 1))).kcal == 2410
    assert (await profiles.goal_on(actor, date(2026, 10, 22))).kcal == 2800

    await me.tap("☰ Ещё")
    await me.tap("⚙️ Настройки")
    await me.tap("✍️ Заполнить с помощью ИИ")
    again = await me.say(RECIPES_TEXT)
    assert "1. ♻️ Рецепт «Обед» уже есть — обновлю:" in again
    assert me.labels()[2:6] == ["Пропустить 1", "Пропустить 2", "Пропустить 3", "Пропустить 4"]
    await me.tap("✅ Выполнить всё")
    names = [i.name for i in await fill_world.service("food").items(actor, include_hidden=True)]
    assert sorted(n for n in names if n in {r[0] for r in RECIPES}) == sorted(r[0] for r in RECIPES)


async def test_s122_long_message_paged(fill_world: World, me: Persona) -> None:
    """S-122. Раздел 9: сообщение длиной 3500 символов разбирается; карточка листается по страницам."""
    text = LONG_TEXT[:3500]
    assert len(text) == 3500
    await me.tap("✍️ Заполнить с помощью ИИ")
    card = await me.say(text)
    assert card.startswith("Понял так:\nРецепты: 40\nСтраница 1 из 4\n1. 🍽 Рецепт «Продукт 1» (на 100 г)")
    assert "Страница 2 из 4\n11. 🍽 Рецепт «Продукт 11»" in await me.tap("Дальше ▶")
    assert "Страница 3 из 4" in await me.tap("Дальше ▶")
    assert "Страница 2 из 4" in await me.tap("◀ Назад")
