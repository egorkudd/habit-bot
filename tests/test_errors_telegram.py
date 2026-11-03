"""Раздел 7.4 и критерии «Понятные ошибки»: код E-xxxx пользователю, оповещение администратору, склейка за час."""

import re
from pathlib import Path
from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, Update

from habit_bot import ops
from habit_bot.app import build_app
from habit_bot.channels.telegram.channel import chat_id_of, error_location
from habit_bot.kernel.errors import AppError
from tests.conftest import ADMIN_ID, OTHER_ID
from tests.fakes import message_update

INCIDENT = re.compile(r"E-[0-9A-F]{4}")


async def _app_with_broken_handler(settings: Any, fake_session: Any, clock: Any) -> Any:
    application = build_app(settings, telegram_session=fake_session, clock=clock)
    router = Router(name="broken")

    @router.message(Command("boom"))
    async def boom(message: Message) -> None:
        ops.restore_backup(Path("/нет/такого/бэкапа"), Path("/tmp/x.db"))

    @router.message(Command("deny"))
    async def deny(message: Message) -> None:
        raise AppError("ACCESS-NO-INVITE")

    application.telegram.add_router(router)
    await application.startup()
    return application


async def test_internal_error_user_and_admin(settings: Any, fake_session: Any, clock: Any) -> None:
    """Раздел 9: внутренняя ошибка — пользователь видит код E-xxxx, администратор — тот же код, раздел и файл."""
    application = await _app_with_broken_handler(settings, fake_session, clock)
    try:
        await application.telegram.dispatcher.feed_raw_update(
            application.telegram.bot, message_update(1, ADMIN_ID, "/boom"))
    finally:
        await application.close()
    user_text, admin_text = fake_session.texts(ADMIN_ID)
    assert user_text.startswith("Что-то пошло не так, ничего не сохранено.")
    incident = INCIDENT.search(user_text)
    assert incident is not None
    assert admin_text.startswith(f"⚠️ {incident.group(0)} · «ops.restore_backup», пользователь #1")
    assert "FileNotFoundError" in admin_text
    assert "ops.py:" in admin_text
    assert "1 раз за час" in admin_text
    assert "Что сделать: передайте код Claude для исправления." in admin_text


async def test_five_same_errors_one_alert(settings: Any, fake_session: Any, clock: Any) -> None:
    """Раздел 9: 5 одинаковых ошибок за час — одно оповещение со счётчиком."""
    application = await _app_with_broken_handler(settings, fake_session, clock)
    try:
        for update_id in range(1, 6):
            clock.advance(minutes=1)
            await application.telegram.dispatcher.feed_raw_update(
                application.telegram.bot, message_update(update_id, ADMIN_ID, "/boom"))
    finally:
        await application.close()
    admin_alerts = [t for t in fake_session.texts(ADMIN_ID) if t.startswith("⚠️")]
    assert len(admin_alerts) == 1
    edits = fake_session.edits()
    assert len(edits) == 4
    assert "5 раз за час" in edits[-1].text


async def test_app_error_shows_user_text(settings: Any, fake_session: Any, clock: Any) -> None:
    """Ожидаемая ошибка (AppError) показывает пользователю текст из каталога без оповещения администратору."""
    application = await _app_with_broken_handler(settings, fake_session, clock)
    try:
        await application.telegram.dispatcher.feed_raw_update(
            application.telegram.bot, message_update(1, ADMIN_ID, "/deny"))
    finally:
        await application.close()
    assert fake_session.texts(ADMIN_ID) == [
        "Бот доступен по приглашению. Если у вас есть ссылка — откройте её ещё раз",
    ]


async def test_error_reply_when_user_blocked_bot(settings: Any, fake_session: Any, clock: Any) -> None:
    """Если пользователь заблокировал бота, ошибка отправки не роняет обработку."""
    application = await _app_with_broken_handler(settings, fake_session, clock)
    fake_session.blocked_chats.add(ADMIN_ID)
    try:
        await application.telegram.dispatcher.feed_raw_update(
            application.telegram.bot, message_update(1, ADMIN_ID, "/boom"))
        assert await application.telegram.notifier.send(ADMIN_ID, "x") is None
        assert await application.telegram.notifier.edit(ADMIN_ID, 1, "x") is False
    finally:
        await application.close()


def test_chat_id_of_and_location() -> None:
    """Куда отвечать: сообщение, нажатие кнопки или некуда; место ошибки вне кода бота."""
    callback = Update.model_validate({"update_id": 1, "callback_query": {
        "id": "1", "chat_instance": "c", "from": {"id": OTHER_ID, "is_bot": False, "first_name": "А"}}})
    assert isinstance(callback.callback_query, CallbackQuery)
    assert chat_id_of(callback) == OTHER_ID
    assert chat_id_of(Update(update_id=2)) is None
    try:
        raise ValueError("вне бота")
    except ValueError as exc:
        assert error_location(exc) == ("обработчик", "вне кода бота")
