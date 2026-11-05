"""Поведенческие сценарии: «🛠 Админ» — пользователи, блокировка, удаление, расходы на ИИ, каталог, бэкапы
(раздел 3.13, часть 10)."""

import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from habit_bot.modules.admin.telegram.handlers import AdCb
from habit_bot.ops import backup_path
from habit_bot.ops import main as ops_main
from habit_bot.platform.backup.crypto import WrongPassword, decrypt
from tests.conftest import ADMIN_ID, OTHER_ID
from tests.fakes import FakeLlm
from tests.scenarios.conftest import finish_guest_onboarding, invite_guest, pass_onboarding
from tests.scenarios.harness import Persona, World

PASSWORD = "очень-длинный-пароль"
BLOCKED = "Доступ к боту закрыт. Обратитесь к администратору"


@pytest.fixture
async def admin_world(settings: Any, fake_session: Any, clock: Any, geocoder: Any) -> AsyncIterator[World]:
    llm = FakeLlm({"выпил витамины": {"actions": []}, "вчера съел торт": {"actions": []}})
    w = await World(settings, fake_session, clock, geocoder, llm=llm).start()
    yield w
    await w.stop()


@pytest.fixture
async def me(admin_world: World) -> Persona:
    user = admin_world.person(ADMIN_ID, "Егор")
    await pass_onboarding(user)
    return user


@pytest.fixture
async def guest(admin_world: World, me: Persona) -> Persona:
    user = await invite_guest(admin_world, me, OTHER_ID, "Аня")
    await finish_guest_onboarding(user)
    return user


async def open_admin(user: Persona, item: str) -> str:
    await user.tap("☰ Ещё")
    await user.tap("🛠 Админ")
    return await user.tap(item)


async def test_s114_users_list_and_block(admin_world: World, me: Persona, guest: Persona) -> None:
    """S-114. Раздел 9: админ видит пользователя без содержимого дневника и блокирует его; заблокированный
    получает «доступ закрыт», данные на месте; после разблокировки всё работает."""
    await guest.tap("🍽 Еда")
    await guest.tap("✍️ Другое")
    await guest.say("Торт 350 5 20 40")
    text = await open_admin(me, "👥 Пользователи")
    assert text.startswith("👥 Пользователи: 2\n1. Егор · админ · с ")
    assert "\n2. Аня · с " in text and "записей 1" in text and "Торт" not in text
    assert me.labels() == ["2. Аня"]  # администратора не заблокировать и не удалить — кнопки нет
    card = await me.tap("2. Аня")
    assert card.startswith("👤 Аня\nС ") and "Содержимое дневника администратору не показывается." in card
    await me.tap("🔒 Заблокировать")
    assert me.session.answers()[-1].text == "Заблокирован" and "Статус: 🔒 заблокирован" in me.last()
    assert await guest.say("/start") == BLOCKED
    assert await guest.tap("🍽 Еда") == BLOCKED
    await me.tap("🔓 Разблокировать")
    assert (await guest.tap("🍽 Еда")).startswith("🍽 Еда за 03.11.")


async def test_s115_delete_user_and_admin_is_protected(admin_world: World, me: Persona, guest: Persona) -> None:
    """S-115. Удаление пользователя стирает все его данные (как «Удалить аккаунт»); подменённая кнопка
    «заблокировать администратора» — отказ ACCESS-ADMIN-PROTECTED."""
    guest_id = (await admin_world.service("users.sign_in").execute(OTHER_ID, "")).user_id
    await open_admin(me, "👥 Пользователи")
    await me.tap("2. Аня")
    assert await me.tap("🗑 Удалить") == "Удалить «Аня» и все данные? Это нельзя отменить."
    assert (await me.tap("🗑 Да, удалить")).startswith("Пользователь удалён со всеми данными.\n\n👥 Пользователи: 1")
    assert await admin_world.service("users.profiles").count_user_rows(guest_id) == 0
    assert (await guest.say("/start")).startswith("Бот доступен по приглашению")
    owner_id = (await admin_world.service("users.sign_in").execute(ADMIN_ID, "")).user_id
    await me.press_data(AdCb(o=owner_id, t=0, a="block", v=str(owner_id)).pack())
    assert me.last() == "Администратора нельзя заблокировать или удалить через бота"
    await me.press_data(AdCb(o=owner_id, t=0, a="del_yes", v=str(owner_id)).pack())
    assert me.last() == "Администратора нельзя заблокировать или удалить через бота"


async def test_s116_ai_costs_without_texts(admin_world: World, me: Persona, guest: Persona) -> None:
    """S-116. «💰 Расходы на ИИ» — сумма за месяц и по пользователям, без текстов запросов; гость в «Админ» не
    попадает даже подменённой кнопкой."""
    await me.say("выпил витамины")
    await guest.say("вчера съел торт")
    await guest.say("вчера съел торт")
    text = await open_admin(me, "💰 Расходы на ИИ")
    assert text.startswith("💰 Расходы на ИИ за 11.2026: < 0,01 $ из 5 $\n• Аня — разборов 2 · < 0,01 $")
    assert "• Егор — разборов 1 · " in text and "торт" not in text and "витамины" not in text
    guest_id = (await admin_world.service("users.sign_in").execute(OTHER_ID, "")).user_id
    await guest.press_data(AdCb(o=guest_id, t=0, a="users").pack())
    assert guest.last() == "Эта кнопка не ваша — ничего не изменено. Вот главное меню 👇"


async def test_s117_catalog_add_hide_return(admin_world: World, me: Persona, guest: Persona) -> None:
    """S-117. «📚 Каталог»: добавить продукт строкой (ошибка не сбрасывает ввод), скрыть — пользователи больше не
    видят его в «📚 Каталог», но то, что уже добавлено к себе, остаётся; вернуть."""
    text = await open_admin(me, "📚 Каталог")
    assert text.startswith("📚 Общий каталог\nПродуктов: ") and "(скрыто 0) · упражнений: 125" in text
    assert await me.tap("➕ Продукт") == "➕ Название и КБЖУ на 1 порцию, например: Хлебец 35 1,2 0,4 6,9"
    assert (await me.say("Хлебец 35 1,2")).startswith("Не хватает:")
    assert (await me.say("Хлебец 35 1,2 0,4 6,9")).startswith(
        "✅ В каталоге: Хлебец — 35 ккал · Б 1,2 · Ж 0,4 · У 6,9 на порцию")
    actor = await admin_world.service("users.sign_in").execute(OTHER_ID, "")
    food = admin_world.service("food")
    bread = next(i for i in await food.catalog() if i.name == "Хлебец")
    await food.add_from_catalog(actor, bread.public_id)
    await me.tap("🍽 Продукты")
    names = [i.name for i in await food.catalog(include_hidden=True)]  # по алфавиту, по 10 на странице
    number = names.index("Хлебец") + 1
    for _ in range((number - 1) // 10):
        await me.tap("▶")
    await me.tap(f"🙈 {number}")
    assert f"{number}. Хлебец — 35 ккал · скрыт" in me.last()
    assert all(i.name != "Хлебец" for i in await food.catalog())
    assert any(i.name == "Хлебец" for i in await food.items(actor))  # копия у пользователя осталась
    await me.tap(f"👁 {number}")
    assert any(i.name == "Хлебец" for i in await food.catalog())


async def test_s118_backup_now_and_decrypt(admin_world: World, me: Persona, guest: Persona, tmp_path: Path,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    """S-118. Раздел 9: «Бэкап сейчас» присылает файл сразу; файл зашифрован паролем BACKUP_PASSWORD и
    расшифровывается командой ops; на сервере одна копия; гостю «Бэкап» недоступен."""
    text = await open_admin(me, "💾 Бэкап")
    assert text.startswith("💾 Бэкап базы\nПоследний: ещё не было.")
    await me.tap("💾 Бэкап сейчас")
    name, data = me.session.documents(ADMIN_ID)[-1]
    assert name.startswith("habit-bot-2026-11-03-") and name.endswith(".db.enc")
    assert b"SQLite format" not in data[:100]
    with pytest.raises(WrongPassword):
        decrypt(data, "не тот пароль")
    encrypted = tmp_path / name
    encrypted.write_bytes(data)
    restored = tmp_path / "bot.db"
    assert ops_main(["decrypt", str(encrypted), str(restored)], env={"BACKUP_PASSWORD": PASSWORD}) == 0
    assert "проверка: ok" in capsys.readouterr().out
    con = sqlite3.connect(restored)
    assert con.execute("SELECT count(*) FROM users").fetchone()[0] == 2
    con.close()
    assert ops_main(["decrypt", str(encrypted), str(restored)], env={"BACKUP_PASSWORD": "не тот"}) == 1
    assert ops_main(["decrypt", str(encrypted), str(restored)], env={}) == 2
    folder = backup_path(admin_world.settings.data_dir).parent
    assert [p.name for p in folder.iterdir()] == ["bot.db.bak"]  # одна копия, без временных файлов
    assert (await open_admin(me, "💾 Бэкап")).startswith("💾 Бэкап базы\nПоследний: 03.11 ")
    await guest.tap("☰ Ещё")
    assert not guest.sees("🛠 Админ")


async def test_s119_schedule_every_two_days_and_failure(admin_world: World, me: Persona,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """S-119. Раздел 9: бэкап приходит раз в 2 дня — считается от последнего удачного, а не от перезапуска; если
    новый бэкап не удался, прошлая копия остаётся на месте, администратор получает оповещение."""
    scheduled = admin_world.service("backup.scheduled")
    assert await scheduled() is True
    sent = len(me.session.documents(ADMIN_ID))
    admin_world.clock.advance(hours=47)
    await admin_world.restart()
    scheduled = admin_world.service("backup.scheduled")
    assert await scheduled() is False
    admin_world.clock.advance(hours=2)
    assert await scheduled() is True
    assert len(me.session.documents(ADMIN_ID)) == sent + 1
    copy = backup_path(admin_world.settings.data_dir)
    before = copy.read_bytes()

    def broken(*args: Any) -> str:
        raise sqlite3.DatabaseError("database disk image is malformed")

    monkeypatch.setattr("habit_bot.modules.backup.usecases.make_backup", broken)
    admin_world.clock.advance(hours=49)
    assert await scheduled() is False
    assert copy.read_bytes() == before
    assert any(t.startswith("💾 Бэкап не удался (DatabaseError: database disk image is malformed)")
               for t in me.texts())
    await open_admin(me, "💾 Бэкап")
    assert await me.tap("💾 Бэкап сейчас") == (
        "💾 Бэкап не удался — прошлая копия на сервере на месте. Подробности — в оповещении выше.")


async def test_s120_too_big_for_telegram(admin_world: World, me: Persona, monkeypatch: pytest.MonkeyPatch) -> None:
    """S-120. Бэкап больше 50 МБ Telegram не примет: копия остаётся на сервере, администратору — объяснение."""
    monkeypatch.setattr("habit_bot.modules.backup.usecases.TELEGRAM_LIMIT", 10)
    await open_admin(me, "💾 Бэкап")
    assert (await me.tap("💾 Бэкап сейчас")).startswith("💾 Бэкап 0")
    assert "больше 50 МБ, Telegram такой файл не примет" in me.last()
    assert any(t.startswith("💾 Бэкап ") and "Копия сохранена только на сервере" in t for t in me.texts())
