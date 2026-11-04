"""Поведенческие сценарии: доступ и приглашения (раздел 3.0, 3.13)."""

from sqlalchemy import func, select

from habit_bot.kernel.identity import User
from tests.conftest import OTHER_ID
from tests.scenarios.conftest import finish_guest_onboarding, invite_guest
from tests.scenarios.harness import Persona, World

NO_INVITE = "Бот доступен по приглашению. Если у вас есть ссылка — откройте её ещё раз"
THIRD_ID = 333333333


async def _users(world: World) -> int:
    async with world.app.ctx.uow() as uow:
        return int((await uow.session.execute(select(func.count()).select_from(User))).scalar_one())


async def test_s01_stranger_is_turned_away(world: World) -> None:
    """S-01. Незнакомец без ссылки пишет /start, текст, стикер, жмёт старую кнопку — всегда «по приглашению»,
    в базе ничего не появляется."""
    stranger = world.person(OTHER_ID, "Гость")
    assert await stranger.say("/start") == NO_INVITE
    assert await stranger.say("привет, пусти") == NO_INVITE
    assert await stranger.sticker() == NO_INVITE
    await stranger.press_data("u:1:0:settings:profile")
    assert stranger.last() == NO_INVITE
    assert await _users(world) == 0


async def test_s02_invited_relative_joins(world: World, owner: Persona) -> None:
    """S-02. Владелец приглашает близкого: ссылка из «Админ» → гость проходит анкету с «Заполнить позже» →
    у гостя меню без «Админ», у владельца приглашение исчезло из списка."""
    guest = await invite_guest(world, owner, OTHER_ID, "Аня")
    assert guest.last().startswith("Шаг 1/12.")
    await guest.tap("Аня")
    await guest.tap("Женский")
    await guest.say("10.01.1996")
    await guest.say("165")
    await guest.say("60")
    await guest.tap("Средняя")
    await guest.tap("Поддержание")
    await guest.tap("Пропустить")
    await guest.tap("Новичок")
    await guest.tap("Заполнить позже")
    assert "2 050 ккал · Б 110 · Ж 55 · У 280" in guest.replies()[0]
    await guest.tap("Позже")
    assert await guest.tap("☰ Ещё") == "Ещё:"
    assert not guest.sees("🛠 Админ")
    await owner.tap("☰ Ещё")
    await owner.tap("🛠 Админ")
    assert await owner.tap("🎟 Приглашения") == "🎟 Приглашения\nДействующих приглашений нет."


async def test_s03_one_time_link_cannot_be_reused(world: World, owner: Persona) -> None:
    """S-03. Одноразовую ссылку переслали дальше: второй человек получает «все места уже заняты»."""
    await invite_guest(world, owner, OTHER_ID, "Аня")
    link_text = [t for t in owner.texts() if "?start=" in t][-1]
    code = link_text.split("?start=")[1].split()[0]
    third = world.person(THIRD_ID, "Оля")
    assert "все места уже заняты" in await third.say(f"/start {code}")
    assert await _users(world) == 2


async def test_s04_revoked_link(world: World, owner: Persona) -> None:
    """S-04. Владелец передумал и отозвал ссылку до того, как ей воспользовались — вход закрыт."""
    await owner.tap("☰ Ещё")
    await owner.tap("🛠 Админ")
    await owner.tap("🎟 Приглашения")
    await owner.tap("➕ Новое приглашение")
    await owner.tap("3")
    text = await owner.tap("без срока")
    code = text.split("?start=")[1].split()[0]
    await owner.tap("✕ Отозвать 1")
    guest = world.person(OTHER_ID, "Аня")
    assert "(отозвана)" in await guest.say(f"/start {code}")


async def test_s05_link_expires(world: World, owner: Persona) -> None:
    """S-05. Ссылку на 1 день открыли через 2 дня — «истекла дд.мм»."""
    await owner.tap("☰ Ещё")
    await owner.tap("🛠 Админ")
    await owner.tap("🎟 Приглашения")
    await owner.tap("➕ Новое приглашение")
    await owner.tap("5")
    text = await owner.tap("1 день")
    code = text.split("?start=")[1].split()[0]
    await world.wait(days=2)
    guest = world.person(OTHER_ID, "Аня")
    assert "(истекла 04.11)" in await guest.say(f"/start {code}")


async def test_s06_owner_comes_back_after_deleting_guest(world: World, owner: Persona) -> None:
    """S-06. Гость удалил аккаунт, затем пишет снова — «по приглашению»; по новой ссылке начинает с чистого листа."""
    guest = await invite_guest(world, owner, OTHER_ID, "Аня")
    await finish_guest_onboarding(guest)
    await guest.tap("☰ Ещё")
    await guest.tap("⚙️ Настройки")
    await guest.tap("🗑 Удалить аккаунт")
    assert (await guest.tap("🗑 Да, удалить всё")).startswith("Аккаунт и все данные удалены.")
    assert await guest.say("привет") == NO_INVITE
    again = await invite_guest(world, owner, OTHER_ID, "Аня")
    assert again.last().startswith("Шаг 1/12.")
