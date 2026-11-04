"""Фикстуры поведенческих сценариев: мир с ботом, владелец и гости."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from tests.conftest import ADMIN_ID
from tests.scenarios.harness import Persona, World


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/scenarios/" in str(item.fspath):
            item.add_marker(pytest.mark.scenario)


@pytest.fixture
async def world(settings: Any, fake_session: Any, clock: Any, geocoder: Any) -> AsyncIterator[World]:
    w = await World(settings, fake_session, clock, geocoder).start()
    yield w
    await w.stop()


async def pass_onboarding(user: Persona, *, birth: str = "15.03.2003", height: str = "178", weight: str = "75",
                          activity: str = "Лёгкая", goal: str = "Набор массы", city: str = "Москва") -> None:
    """Пройти анкету кнопками и ответами, как это делает человек."""
    await user.say("/start")
    await user.tap(user.first_name)
    await user.tap("Мужской")
    await user.say(birth)
    await user.say(height)
    await user.say(weight)
    await user.tap(activity)
    await user.tap(goal)
    await user.tap("Пропустить")
    await user.tap("Средний")
    await user.tap(city)
    await user.tap("✅ Принять")
    await user.tap("Готово")
    await user.tap("Позже")


@pytest.fixture
async def owner(world: World) -> Persona:
    """Владелец из ADMIN_TG_IDS, прошедший анкету."""
    user = world.person(ADMIN_ID, "Егор")
    await pass_onboarding(user)
    return user


async def invite_guest(world: World, owner: Persona, tg_id: int, name: str) -> Persona:
    """Владелец создаёт ссылку в «Админ», гость открывает её."""
    await owner.tap("☰ Ещё")
    await owner.tap("🛠 Админ")
    await owner.tap("🎟 Приглашения")
    await owner.tap("➕ Новое приглашение")
    await owner.tap("1")
    text = await owner.tap("7 дней")
    code = text.split("?start=")[1].split()[0]
    guest = world.person(tg_id, name)
    await guest.say(f"/start {code}")
    return guest


async def finish_guest_onboarding(user: Persona) -> None:
    """Гость отвечает на анкету с шага 1 и пропускает шаги 10–12 «Заполнить позже»."""
    await user.tap(user.first_name)
    await user.tap("Женский")
    await user.say("10.01.1996")
    await user.say("165")
    await user.say("60")
    await user.tap("Средняя")
    await user.tap("Поддержание")
    await user.tap("Пропустить")
    await user.tap("Новичок")
    await user.tap("Заполнить позже")
    await user.tap("Позже")
