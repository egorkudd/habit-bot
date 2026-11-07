"""Поведенческие сценарии: настройки, удаление аккаунта и сбои (части 1 и 3)."""

from typing import Any

from habit_bot.modules.users.telegram import settings as settings_ui
from tests.conftest import ADMIN_ID
from tests.scenarios.harness import Persona, World


async def test_s22_weight_changed_then_hesitates(world: World, owner: Persona) -> None:
    """S-22. Похудел на весах: вес 80 → «Пересчитать»; потом рост 190 → «Оставить как есть»; цели — история."""
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("👤 Профиль")
    await owner.tap("Вес")
    assert "Новые КБЖУ: 2 900 ккал" in await owner.say("80")
    assert (await owner.tap("🔄 Пересчитать")).startswith("Новая цель с 03.11: 2 900 ккал")
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("👤 Профиль")
    await owner.tap("Рост")
    await owner.say("190")
    assert (await owner.tap("Оставить как есть")).startswith("КБЖУ оставлены как есть.")
    await owner.tap("✅ Привычки")
    await owner.tap("⚙️ Настроить")
    await owner.tap("🍽 Еда")
    history = await owner.tap("🎯 Цели КБЖУ")
    assert history.count("сегодня:") == 2


async def test_s23_starts_edit_and_walks_away(world: World, owner: Persona) -> None:
    """S-23. Начал менять вес, отвлёкся на 15 минут, потом ввёл число — оно уже не принимается за вес."""
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("👤 Профиль")
    await owner.tap("Вес")
    await world.wait(minutes=15)
    assert await owner.say("90") == "Не понял. Выберите раздел в меню 👇"
    profile = await world.service("users.profiles").profile(
        await world.service("users.sign_in").execute(ADMIN_ID, ""))
    assert profile.weight_kg == 75


async def test_s24_only_admin_cannot_leave(world: World, owner: Persona, monkeypatch: Any) -> None:
    """S-24. Единственный администратор пытается удалить аккаунт — отказ с подсказкой, данные на месте."""
    monkeypatch.setattr(settings_ui, "DELETE_BUTTON", True)  # кнопка спрятана с 1.0.2, удаление работает
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("🗑 Удалить аккаунт")
    assert (await owner.tap("🗑 Да, удалить всё")).startswith("Вы единственный администратор")
    assert (await owner.say("/start")).startswith("Привет, администратор")


async def test_s25_user_blocked_the_bot(world: World, owner: Persona) -> None:
    """S-25. Пользователь заблокировал бота: ответы не доходят, но бот не падает и продолжает работать."""
    world.session.blocked_chats.add(ADMIN_ID)
    await owner.tap("📊 Итоги")
    world.session.blocked_chats.clear()
    assert await owner.tap("📊 Итоги") == "📊 Еда · 03.11 (вт)"


async def test_s26_city_service_down(world: World, owner: Persona) -> None:
    """S-26. Сервис поиска городов не отвечает — бот объясняет и предлагает кнопки; город можно выбрать кнопкой."""
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("👤 Профиль")
    await owner.tap("Город")
    await owner.tap("Другой")
    await owner.say("сломано")
    assert owner.replies()[0].startswith("Поиск городов сейчас не отвечает.")
    assert "Город: Санкт-Петербург" in await owner.tap("Санкт-Петербург")


async def test_s132_settings_without_delete_and_default(world: World, owner: Persona) -> None:
    """S-132. Правки 1.0.2: в «⚙️ Настройки» нет «🗑 Удалить аккаунт» (удаляет администратор в «🛠 Админ»), в
    «🏠 Главный экран» нет «↩ По умолчанию» — только «✅ Готово»; старая кнопка «По умолчанию» устарела."""
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    assert not owner.sees("🗑 Удалить аккаунт") and owner.sees("🏠 Главный экран")
    await owner.tap("🏠 Главный экран")
    assert owner.labels()[-1] == "✅ Готово" and "↩ По умолчанию" not in owner.labels()
    old = owner.find_button("✅ Готово").replace(":hm_s:", ":hm_r:")
    await owner.press_data(old)
    assert owner.last() == "Это меню устарело. Вот главное меню 👇"
