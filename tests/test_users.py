"""Раздел 3.0 и критерии раздела 9 «Регистрация»: первый администратор, гости, роль по списку."""

from typing import Any

from sqlalchemy import func, select

from habit_bot.kernel.identity import Identity, Provider, Role, User, UserStatus
from habit_bot.modules.users.usecases import SignInTelegram, SyncAdminRoles
from tests.conftest import ADMIN_ID, OTHER_ID
from tests.fakes import message_update


async def _count_users(app: Any) -> int:
    async with app.ctx.uow() as uow:
        return int((await uow.session.execute(select(func.count()).select_from(User))).scalar_one())


async def test_admin_start_without_invite(app: Any, fake_session: Any) -> None:
    """Раздел 9: ID из ADMIN_TG_IDS пишет /start без ссылки → регистрация и роль «Администратор»."""
    await app.telegram.dispatcher.feed_raw_update(app.telegram.bot, message_update(1, ADMIN_ID, "/start"))
    texts = fake_session.texts(ADMIN_ID)
    assert len(texts) == 1
    assert texts[0].startswith("Привет, администратор")
    async with app.ctx.uow() as uow:
        identity = (await uow.session.execute(select(Identity))).scalar_one()
        user = await uow.session.get(User, identity.user_id)
    assert identity.provider == Provider.TELEGRAM
    assert identity.external_id == str(ADMIN_ID)
    assert user is not None and user.role == Role.ADMIN
    assert user.status == UserStatus.ONBOARDING
    assert user.name == "Егор"


async def test_guest_without_invite(app: Any, fake_session: Any) -> None:
    """Раздел 9: другой ID без приглашения — «Бот доступен по приглашению», пользователь не создаётся."""
    await app.telegram.dispatcher.feed_raw_update(app.telegram.bot, message_update(1, OTHER_ID, "/start"))
    assert fake_session.texts(OTHER_ID) == [
        "Бот доступен по приглашению. Если у вас есть ссылка — откройте её ещё раз",
    ]
    assert await _count_users(app) == 0


async def test_repeated_start_does_not_duplicate(app: Any, fake_session: Any) -> None:
    """Повторный /start не создаёт второго пользователя."""
    for update_id in (1, 2):
        await app.telegram.dispatcher.feed_raw_update(app.telegram.bot, message_update(update_id, ADMIN_ID, "/start"))
    assert await _count_users(app) == 1
    assert len(fake_session.texts(ADMIN_ID)) == 2


async def test_unknown_text_gets_fallback(app: Any, fake_session: Any) -> None:
    """Пока разделов нет, любое сообщение получает подсказку про /start."""
    await app.telegram.dispatcher.feed_raw_update(app.telegram.bot, message_update(1, ADMIN_ID, "привет"))
    assert fake_session.texts(ADMIN_ID) == ["Этот раздел появится в следующих частях. Напишите /start."]


async def test_role_follows_admin_list(app: Any) -> None:
    """Раздел 9: ID убран из ADMIN_TG_IDS → после перезапуска роль снята, данные на месте; вернули — роль снова."""
    sign_in: SignInTelegram = app.ctx.services["users.sign_in"]
    actor = await sign_in.execute(ADMIN_ID, "Егор")
    assert actor is not None and actor.is_admin

    assert await SyncAdminRoles(uow=app.ctx.uow, admin_tg_ids=[]).execute() == (0, 1)
    async with app.ctx.uow() as uow:
        user = await uow.session.get(User, actor.user_id)
    assert user is not None and user.role == Role.USER

    assert await SyncAdminRoles(uow=app.ctx.uow, admin_tg_ids=[ADMIN_ID]).execute() == (1, 0)
    assert await SyncAdminRoles(uow=app.ctx.uow, admin_tg_ids=[ADMIN_ID]).execute() == (0, 0)


async def test_blocked_user_has_no_access(app: Any) -> None:
    """Заблокированный пользователь не проходит вход."""
    sign_in: SignInTelegram = app.ctx.services["users.sign_in"]
    actor = await sign_in.execute(ADMIN_ID, "")
    assert actor is not None
    async with app.ctx.uow() as uow:
        user = await uow.session.get(User, actor.user_id)
        assert user is not None
        assert user.name == "Администратор"
        user.status = UserStatus.BLOCKED
    assert await sign_in.execute(ADMIN_ID, "Егор") is None


async def test_activity_time_does_not_change_version(app: Any, clock: Any) -> None:
    """Время последней активности обновляется не чаще раза в минуту и не меняет версию профиля."""
    sign_in: SignInTelegram = app.ctx.services["users.sign_in"]
    actor = await sign_in.execute(ADMIN_ID, "Егор")
    assert actor is not None
    async with app.ctx.uow() as uow:
        before = await uow.session.get(User, actor.user_id)
    clock.advance(minutes=5)
    await sign_in.execute(ADMIN_ID, "Егор")
    async with app.ctx.uow() as uow:
        after = await uow.session.get(User, actor.user_id)
    assert before is not None and after is not None
    assert after.last_active_at == clock.now()
    assert after.version == before.version
    assert after.updated_at == before.updated_at


async def test_bot_and_anonymous_updates_ignored(app: Any, fake_session: Any) -> None:
    """Сообщения от ботов и апдейты без отправителя не обрабатываются."""
    update = message_update(1, OTHER_ID, "/start")
    update["message"]["from"]["is_bot"] = True
    await app.telegram.dispatcher.feed_raw_update(app.telegram.bot, update)
    channel_post = {"update_id": 2, "channel_post": {
        "message_id": 1, "date": 1, "chat": {"id": -100, "type": "channel"}, "text": "x"}}
    await app.telegram.dispatcher.feed_raw_update(app.telegram.bot, channel_post)
    assert fake_session.sent() == []
