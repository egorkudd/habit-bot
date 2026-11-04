"""Части каркаса диалогов по отдельности: области и сроки, хранилище, меню, очередь апдейтов, фоновые задачи."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiogram.filters.callback_data import CallbackData
from aiogram.types import Update

from habit_bot.channels.telegram.channel import ErrorMiddleware
from habit_bot.channels.telegram.dialogs.fsm import DbFsmStorage, scope_of, user_key
from habit_bot.channels.telegram.dialogs.middleware import ActivityMiddleware, UserLocks
from habit_bot.channels.telegram.dialogs.policy import (
    DIALOG,
    IDLE_TIMEOUT,
    ONBOARDING,
    OTHER_DAY,
    WORKOUT,
    InactivityPolicy,
)
from habit_bot.channels.telegram.dialogs.store import DialogStore, random_token
from habit_bot.channels.telegram.ui.callbacks import CancelCb, owner_and_token
from habit_bot.channels.telegram.ui.menu import MenuEntry, MenuRegistry, Place, soon_text
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.identity import Actor, Role
from habit_bot.kernel.jobs import JobSpec, run_safely
from tests.conftest import ADMIN_ID
from tests.fakes import callback_update

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def _actor(user_id: int = 1, role: Role = Role.ADMIN) -> Actor:
    return Actor(user_id=user_id, role=role, channel="telegram", request_time=NOW)


async def _user(app: Any) -> int:
    sign_in = app.ctx.services["users.sign_in"]
    actor = await sign_in.execute(ADMIN_ID, "Егор")
    return int(actor.user_id)


def test_policy_scopes() -> None:
    """Раздел 3: ввод и «Другой день» — 15 минут, тренировка — 3 часа, анкета не сбрасывается."""
    policy = InactivityPolicy()
    assert policy.ttl_for(DIALOG) == IDLE_TIMEOUT == timedelta(minutes=15)
    assert policy.ttl_for(OTHER_DAY) == timedelta(minutes=15)
    assert policy.ttl_for(WORKOUT) == timedelta(hours=3)
    assert policy.ttl_for(ONBOARDING) is None
    assert policy.ttl_for("новая_область") == IDLE_TIMEOUT
    assert ONBOARDING not in policy.expiring_scopes()
    assert policy.known_scopes() == {DIALOG, OTHER_DAY, WORKOUT, ONBOARDING, "lost_day"}


async def test_workout_and_onboarding_survive_15_minutes(app: Any) -> None:
    """Раздел 9: идущая тренировка с паузой 20 минут не сбрасывается, через 3 часа — да; анкета продолжается."""
    user_id = await _user(app)
    store: DialogStore = app.telegram.dialogs
    for scope in (DIALOG, WORKOUT, ONBOARDING):
        await store.set_state(user_id, scope, "Шаг:один", NOW)
    assert await store.expire(NOW + timedelta(minutes=20)) == [(user_id, DIALOG)]
    assert await store.expire(NOW + timedelta(hours=3), user_id) == [(user_id, WORKOUT)]
    assert await store.expire(NOW + timedelta(days=30)) == []
    snapshot = await store.get(user_id, ONBOARDING)
    assert snapshot is not None and snapshot.state == "Шаг:один"


async def test_store_rows_and_versions(app: Any) -> None:
    """Пустое состояние без данных — строки нет; данные без состояния хранятся; версия растёт с каждым изменением."""
    user_id = await _user(app)
    store: DialogStore = app.telegram.dialogs
    assert await store.get(user_id, DIALOG) is None
    await store.set_data(user_id, DIALOG, {}, NOW)
    assert await store.get(user_id, DIALOG) is None
    await store.set_data(user_id, DIALOG, {"вес": "77.5"}, NOW)
    first = await store.get(user_id, DIALOG)
    assert first is not None and first.state is None and first.data == {"вес": "77.5"}
    await store.set_state(user_id, DIALOG, "Еда:граммы", NOW + timedelta(minutes=1))
    second = await store.get(user_id, DIALOG)
    assert second is not None and second.token == first.token and second.data == {"вес": "77.5"}
    assert second.last_action_at == NOW + timedelta(minutes=1)
    await store.set_state(user_id, DIALOG, None, NOW)
    assert await store.get(user_id, DIALOG) is not None  # данные ещё есть
    await store.set_data(user_id, DIALOG, {}, NOW)
    assert await store.get(user_id, DIALOG) is None
    assert await store.clear(user_id, DIALOG) is False

    async with app.ctx.uow() as uow:
        from sqlalchemy import select

        from habit_bot.channels.telegram.dialogs.models import DialogState

        await store.set_state(user_id, OTHER_DAY, "x", NOW)
        await store.set_state(user_id, OTHER_DAY, "y", NOW)
        row = (await uow.session.execute(select(DialogState))).scalar_one()
        assert row.version == 2
    assert await store.active_tokens(user_id) == {row.token}
    assert await store.clear(user_id, OTHER_DAY) is True


async def test_fsm_storage(app: Any) -> None:
    """Хранилище aiogram: ключ по user_id бота, «default» — это область «dialog»."""
    user_id = await _user(app)
    storage: DbFsmStorage = app.telegram.storage
    key = user_key(app.telegram.bot.id, user_id)
    assert scope_of(key) == DIALOG
    assert scope_of(user_key(1, user_id, WORKOUT)) == WORKOUT
    assert await storage.get_state(key) is None
    assert await storage.get_data(key) == {}
    assert await storage.token(key) == 0
    await storage.set_data(key, {"a": 1})
    assert await storage.get_data(key) == {"a": 1}
    assert await storage.token(key) > 0
    await storage.close()


def test_random_token_range() -> None:
    """Номер ввода — положительное число, помещается в данные кнопки."""
    assert all(0 < random_token() < 2**31 for _ in range(100))


def test_owner_and_token() -> None:
    """Проверяются только кнопки с полями владельца и номера ввода."""

    class Plain(CallbackData, prefix="p"):
        x: int

    assert owner_and_token(CancelCb(o=5, t=7)) == (5, 7)
    assert owner_and_token(Plain(x=1)) is None
    assert owner_and_token("строка") is None
    assert len(CancelCb(o=2**31, t=2**31).pack()) <= 64


def test_menu_registry() -> None:
    """Раздел 3.1: до 8 кнопок, «Ещё» всегда последняя; «Админ» только у администратора."""
    menu = MenuRegistry()
    user = _actor(role=Role.USER)
    more = [e.key for e in menu.entries(Place.MORE, user)]
    assert "admin" not in more
    assert "admin" in [e.key for e in menu.entries(Place.MORE, _actor())]
    for i in range(10):
        menu.add(MenuEntry(f"h{i}", f"Привычка {i}", 100 + i))
    home = menu.entries(Place.HOME, user)
    assert len(home) == 8
    assert home[-1].key == "more"
    assert menu.by_label(None) is None
    assert menu.by_label(" 🍽 Еда ") is not None
    assert menu.by_label("📅 Другой день") is None  # пункты «Ещё» — не текстовые кнопки
    menu.mark_ready("food")
    food = menu.get("food")
    assert food is not None and food.ready
    assert soon_text(MenuEntry("x", "Икс", 1)) == "Икс — скоро: раздел появится позже плана."


async def test_user_locks_serialize_and_clean_up() -> None:
    """Апдейты одного пользователя — по очереди; после обработки замки не копятся."""
    locks = UserLocks()
    order: list[str] = []

    async def work(name: str, delay: float) -> None:
        async with locks.hold(1):
            order.append(f"{name}+")
            await asyncio.sleep(delay)
            order.append(f"{name}-")

    await asyncio.gather(work("a", 0.02), work("b", 0))
    assert order == ["a+", "a-", "b+", "b-"]
    assert len(locks) == 0


async def test_activity_middleware_without_actor(app: Any) -> None:
    """Апдейт без пользователя (вход не пройден) идёт дальше без состояния ввода."""
    middleware = ActivityMiddleware(app.telegram.storage, app.telegram.clock, app.telegram.tz)
    seen: dict[str, Any] = {}

    async def handler(event: Any, data: dict[str, Any]) -> str:
        seen.update(data)
        return "ok"

    assert await middleware(handler, object(), {"bot": app.telegram.bot}) == "ok"
    assert "state" not in seen


async def test_error_on_button_answers_callback(app: Any, fake_session: Any) -> None:
    """Ошибка ввода после нажатия кнопки: текст ошибки пользователю и ответ на нажатие (кнопка не «крутится»)."""
    middleware = ErrorMiddleware(None)

    async def handler(event: Any, data: dict[str, Any]) -> None:
        raise AppError("INPUT-DATE")

    update = Update.model_validate(callback_update(1, ADMIN_ID, "x"), context={"bot": app.telegram.bot})
    await middleware(handler, update, {"bot": app.telegram.bot})
    assert fake_session.texts(ADMIN_ID) == ["Дату пишите как 20.10 или 20.10.2026"]
    assert fake_session.answers()[-1].callback_query_id == "cb1"


async def test_job_errors_do_not_stop_bot(caplog: pytest.LogCaptureFixture) -> None:
    """Упавшая фоновая задача пишется в лог, бот продолжает работу."""

    async def broken() -> None:
        raise RuntimeError("сломалось")

    async def fine() -> None:
        return None

    assert await run_safely(JobSpec("сломанная", timedelta(minutes=1), broken)) is False
    assert await run_safely(JobSpec("рабочая", timedelta(minutes=1), fine)) is True
    assert "сломанная" in caplog.text
