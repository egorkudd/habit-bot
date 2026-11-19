"""Поведенческие сценарии: еда (раздел 3.2, часть 5)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from habit_bot.modules.food.domain.nutrition import Nutrients, Unit
from habit_bot.modules.food.models import FoodEntry
from habit_bot.modules.users.domain.kbju import Targets
from tests.conftest import ADMIN_ID, OTHER_ID
from tests.scenarios.conftest import finish_guest_onboarding, invite_guest
from tests.scenarios.harness import Persona, World

STALE = "Это меню устарело. Вот главное меню 👇"
COCKTAIL = "🍽 Коктейль — 1 порция: 322 ккал · Б 26 · Ж 9 · У 39 · 140 ₽"


async def _actor(world: World, tg_id: int = ADMIN_ID) -> Any:
    return await world.service("users.sign_in").execute(tg_id, "")


async def _cocktail(world: World) -> None:
    """Владелец заранее внёс свой рецепт (как после «Заполнить с помощью ИИ»)."""
    await world.service("food").create_item(
        await _actor(world), name="Коктейль", kind="recipe", unit=Unit.PORTION,
        nutrients=Nutrients.of(322, 26, 9, 39), price=Decimal(140), composition="Молоко 200 мл, банан, протеин 23 г")


async def _entries(world: World) -> list[FoodEntry]:
    async with world.app.ctx.uow() as uow:
        return list((await uow.session.execute(select(FoodEntry).where(FoodEntry.deleted_at.is_(None))))
                    .scalars().all())


async def test_s29_cocktail_in_two_taps(world: World, owner: Persona) -> None:
    """S-29. «🍽 Еда» → «Коктейль»: 322 ккал / Б 26 / Ж 9 / У 39 и 140 ₽ за 2 нажатия; карточка дня с остатком;
    «×2» удваивает, «Отменить» убирает запись из итогов."""
    await _cocktail(world)
    assert (await owner.tap("🍽 Еда")).startswith("🍽 Еда за 03.11.")
    card = await owner.tap("Коктейль")
    assert card.startswith(COCKTAIL)
    # правки 1.0.2: цель / факт / остаток — табличкой
    assert ("          Ккал    Б    Ж    У\nЦель      2800  160   80  360\nФакт       322   26    9   39\n"
            "Остаток   2478  134   71  321\n") in card
    assert "Расход: 140 ₽" in card
    assert all(owner.sees(b) for b in ("×0,5", "×2", "Отменить", "📅 На вчера"))
    assert "Факт       644" in await owner.tap("×2")
    assert (await owner.tap("Отменить")).startswith("Запись «Коктейль» удалена.")
    assert "Записей пока нет" in owner.last()
    assert await _entries(world) == []


async def test_s30_thighs_and_grams(world: World, owner: Persona) -> None:
    """S-30. Из каталога «Банан» к себе → «2 шт»: 210 / 2,6 / 0,8 / 54; «Картофель» числом 250 г;
    ошибка «2,5,1» — подсказка, вопрос остаётся. Каталог — новый базовый набор (правки 1.0.2)."""
    await owner.tap("🍽 Еда")
    await owner.tap("📚 Каталог")
    assert set(owner.labels()) >= {"Банан", "Картофель", "Куриное филе", "Творог 5%", "Гречка сухая (пакет 80 г)",
                                   "Рис сухой (пакет 80 г)"}
    assert "Пельмени" not in owner.labels()
    assert (await owner.tap("Банан")).startswith("Банан — на 1 шт: 105 ккал · Б 1,3 · Ж 0,4 · У 27")
    assert await owner.tap("➕ Добавить к себе") == "«Банан» добавлен в ваш список."
    assert (await owner.tap("Записать сейчас")).startswith("Банан: сколько?")
    card = await owner.tap("2 шт")
    assert card.startswith("🍽 Банан — 2 шт: 210 ккал · Б 2,6 · Ж 0,8 · У 54 · без цены")
    assert "1 без цены" in card
    await owner.tap("🍽 Еда")
    await owner.tap("📚 Каталог")
    await owner.tap("Картофель")
    await owner.tap("➕ Добавить к себе")
    await owner.tap("Записать сейчас")
    assert await owner.say("2,5,1") == "Не понял число „2,5,1“. Напишите, например, 4,5 или 4.5"
    assert (await owner.say("250")).startswith("🍽 Картофель — 250 г: 192,5 ккал · Б 5 · Ж 1 · У 40,75")


async def test_s31_other_line(world: World, owner: Persona) -> None:
    """S-31. «✍️ Другое»: «Маффин 320 4,5 15» → «Не хватает: углеводы», ввод не сброшен; «Маффин 320 4.5 15 41» —
    запись; «Сохранить как рецепт» → рецепт в списке; повторное сохранение — «уже есть» с «Обновить»."""
    await owner.tap("🍽 Еда")
    await owner.tap("✍️ Другое")
    assert (await owner.say("Маффин 320 4,5 15")).startswith("Не хватает: углеводы.")
    card = await owner.say("Маффин 320 4.5 15 41")
    assert card.startswith("🍽 Маффин — 1 порция: 320 ккал · Б 4,5 · Ж 15 · У 41 · без цены")
    assert await owner.tap("💾 Сохранить как рецепт") == "Рецепт «Маффин» сохранён — он теперь в списке «🍽 Еда»."
    await owner.tap("🍽 Еда")
    await owner.tap("✍️ Другое")
    await owner.say("Маффин 300 4,5 14 40 90")
    assert await owner.tap("💾 Сохранить как рецепт") == "Рецепт „Маффин“ уже есть."
    assert (await owner.tap("Обновить")).startswith("Рецепт «Маффин» обновлён: 300 ккал")
    await owner.tap("🍽 Еда")
    assert "Маффин" in owner.labels()


async def test_s32_recipe_edit_keeps_history(world: World, owner: Persona) -> None:
    """S-32. Раздел 9: правка рецепта не меняет прошлые записи — они хранят копию КБЖУ и цены."""
    await _cocktail(world)
    await owner.tap("🍽 Еда")
    await owner.tap("Коктейль")
    await owner.tap("🍽 Еда")
    await owner.tap("⚙️ Мои")
    await owner.tap("Коктейль")
    await owner.tap("✏️ КБЖУ и цена")
    assert await owner.say("400 30 10 50 160") == "⚙️ Мои рецепты и продукты:"  # правки 1.0.5: остаёмся в «Моих»
    assert owner.replies()[-2].endswith("Прошлые записи не изменились.")
    (entry,) = await _entries(world)
    assert (entry.kcal, entry.price) == (322, 140)
    await owner.tap("🍽 Еда")
    assert (await owner.tap("Коктейль")).startswith("🍽 Коктейль — 1 порция: 400 ккал")


async def test_s33_yesterday_edit_abandoned(world: World, owner: Persona) -> None:
    """S-33. Раздел 9: «Другой день» → «Вчера» → «Записи дня» → «Изменить количество», 15 минут без действий:
    количество не изменено, режим выключен, бот ничего не прислал; старая кнопка — «Это меню устарело»."""
    await _cocktail(world)
    await owner.tap("☰ Ещё")
    await owner.tap("📅 Другой день")
    await owner.tap("Вчера (02.11)")
    await owner.tap("🍽 Еда")
    assert (await owner.tap("Коктейль")).startswith(COCKTAIL)
    assert "02.11, пн" in owner.last()
    await owner.tap("🍽 Еда")
    await owner.tap("📋 Записи дня")
    await owner.tap("Коктейль · 322 ккал")
    await owner.tap("✏️ Изменить количество")
    sent = len(owner.texts())
    await world.wait(minutes=15)
    assert len(owner.texts()) == sent
    assert await owner.tap("×2") == STALE
    (entry,) = await _entries(world)
    assert (entry.quantity, entry.day) == (1, date(2026, 11, 2))
    assert owner.keyboard()[0] == ["🍽 Еда", "🤸 Зарядка"]


async def test_s34_move_to_yesterday_and_to_date(world: World, owner: Persona) -> None:
    """S-34. Раздел 9: «📅 На вчера» через час переносит запись, итоги обоих дней; «Перенести на дату» — на 01.11."""
    await _cocktail(world)
    await owner.tap("🍽 Еда")
    await owner.tap("Коктейль")
    await world.wait(hours=1)
    await owner.tap("📅 На вчера")
    assert owner.replies()[0].startswith("Итоги 02.11:") and "Факт       322" in owner.replies()[0]
    assert owner.replies()[1].startswith("Итоги 03.11:") and "Записей пока нет" in owner.replies()[1]
    await owner.tap("☰ Ещё")
    await owner.tap("📅 Другой день")
    await owner.tap("Вчера (02.11)")
    await owner.tap("🍽 Еда")
    await owner.tap("📋 Записи дня")
    await owner.tap("Коктейль · 322 ккал")
    await owner.tap("📅 Перенести на дату")
    assert await owner.say("05.11") == "Нельзя записать на 05.11 — это будущее. Сегодня 03.11"
    await owner.say("01.11")
    (entry,) = await _entries(world)
    assert entry.day == date(2026, 11, 1)


async def test_s35_forgotten_other_day(world: World, owner: Persona) -> None:
    """S-35. Раздел 9: в режиме 02.11 через 15 минут бездействия следующая запись — в сегодня, с «📅 Нет, за 02.11»."""
    await _cocktail(world)
    await owner.tap("☰ Ещё")
    await owner.tap("📅 Другой день")
    await owner.tap("Вчера (02.11)")
    await world.wait(minutes=16)
    await owner.tap("🍽 Еда")
    card = await owner.tap("Коктейль")
    assert card.startswith("Записываю за сегодня.\n🍽 Коктейль")
    assert "03.11, вт" in card
    assert (await owner.tap("📅 Нет, за 02.11")).startswith("«Коктейль» — за 02.11.")
    (entry,) = await _entries(world)
    assert entry.day == date(2026, 11, 2)
    await owner.tap("🍽 Еда")
    assert not (await owner.tap("Коктейль")).startswith("Записываю за сегодня.")


async def test_s36_double_delivery(world: World, owner: Persona) -> None:
    """S-36. Раздел 9: повторно доставленный апдейт (тот же update_id) не создаёт вторую запись."""
    await _cocktail(world)
    await owner.tap("🍽 Еда")
    await owner.tap_twice("Коктейль")
    assert len(await _entries(world)) == 1


async def test_s37_own_product_and_hiding(world: World, owner: Persona) -> None:
    """S-37. Свой продукт в настройках: «⚙️ Настройки» → «🍽 Рецепты и продукты» → новый «Творог» на 100 г;
    дубль названия — подсказка; скрытый продукт пропадает из списка «Еда»."""
    await owner.tap("✅ Привычки")
    await owner.tap("⚙️ Настроить")
    await owner.tap("🍽 Еда")
    await owner.tap("🍽 Рецепты и продукты")
    await owner.tap("➕ Новый рецепт или продукт")
    await owner.say("Творог 5%")
    await owner.tap("На 100 г")
    assert await owner.say("121 17 5 1,8 30") == "⚙️ Мои рецепты и продукты:"
    assert owner.replies()[-2].startswith("Добавлено: Творог 5% — на 100 г: 121 ккал")
    assert "Творог 5%" in owner.labels()
    await owner.tap("🍽 Еда")
    await owner.tap("⚙️ Мои")
    await owner.tap("➕ Новый рецепт или продукт")
    assert await owner.say("творог 5%") == "Рецепт „творог 5%“ уже есть."
    await owner.tap("✕ Отмена")
    await owner.tap("🍽 Еда")
    await owner.tap("⚙️ Мои")
    await owner.tap("Творог 5%")
    await owner.tap("🙈 Скрыть")
    await owner.tap("🍽 Еда")
    assert "Творог 5%" not in owner.labels()


async def test_s38_foreign_entry_button(world: World, owner: Persona) -> None:
    """S-38. Гость нажимает кнопку записи владельца (подмена) — отказ, запись владельца на месте."""
    await _cocktail(world)
    await owner.tap("🍽 Еда")
    await owner.tap("Коктейль")
    owners_undo = owner.find_button("Отменить")
    guest = await invite_guest(world, owner, OTHER_ID, "Аня")
    await finish_guest_onboarding(guest)
    await guest.press_data(owners_undo)
    assert guest.last() == "Эта кнопка не ваша — ничего не изменено. Вот главное меню 👇"
    assert len(await _entries(world)) == 1


async def test_s39_restart_mid_amount(world: World, owner: Persona) -> None:
    """S-39. Выбрал «Творог 5%», бот перезапустился, через 5 минут ввёл 200 — записано 200 г."""
    await owner.tap("🍽 Еда")
    await owner.tap("📚 Каталог")
    await owner.tap("Творог 5%")
    await owner.tap("➕ Добавить к себе")
    await owner.tap("Записать сейчас")
    await world.restart()
    await world.wait(minutes=5)
    assert (await owner.say("200")).startswith("🍽 Творог 5% — 200 г: 242 ккал")


async def test_s40_goal_by_date(world: World, owner: Persona) -> None:
    """S-40. Раздел 9: остаток считается по цели, действовавшей в дату: 01.10 — от 2410, 22.10 — от 2800."""
    profiles = world.service("users.profiles")
    actor = await _actor(world)
    await profiles.add_goal(actor, Targets(2410, 140, 70, 305), start_date=date(2026, 9, 22), source="manual")
    await profiles.add_goal(actor, Targets(2800, 160, 80, 360), start_date=date(2026, 10, 9), source="manual")
    await _cocktail(world)
    for day, left in (("01.10", "Остаток   2088"), ("22.10", "Остаток   2478")):
        await owner.tap("☰ Ещё")
        await owner.tap("📅 Другой день")
        await owner.say(day)
        if owner.sees("Да"):
            await owner.tap("Да")
        await owner.tap("🍽 Еда")
        assert left in await owner.tap("Коктейль")
        await owner.tap(f"📅 {day} ✕ Вернуться к сегодня")


async def test_s41_deleted_entry_purged_after_30_days(world: World, owner: Persona) -> None:
    """S-41. Раздел 9: удалённая запись не видна в итогах, а через 30 дней стирается совсем."""
    await _cocktail(world)
    await owner.tap("🍽 Еда")
    await owner.tap("Коктейль")
    await owner.tap("Отменить")
    async with world.app.ctx.uow() as uow:
        assert len((await uow.session.execute(select(FoodEntry))).scalars().all()) == 1
    world.set_time(datetime(2026, 11, 3, 12, 0, tzinfo=UTC) + timedelta(days=31))
    await world.restart()  # задача окончательного удаления запускается и при старте
    async with world.app.ctx.uow() as uow:
        assert (await uow.session.execute(select(FoodEntry))).scalars().all() == []


async def _three(world: World) -> None:
    """Коктейль (порция), курица (на 100 г) и банан (штуки) в своём списке."""
    await _cocktail(world)
    food, actor = world.service("food"), await _actor(world)
    await food.create_item(actor, name="Курица", kind="product", unit=Unit.GRAMS,
                           nutrients=Nutrients.of(113, 23.6, 1.9, 0.4), price=None)
    await food.create_item(actor, name="Банан", kind="product", unit=Unit.PIECE,
                           nutrients=Nutrients.of(105, 1.3, 0.4, 27), price=None)


async def test_s156_multi_select_with_quantities(world: World, owner: Persona) -> None:
    """S-156. Правки 1.0.5: «☑️ Выбрать несколько» → отметить коктейль, курицу и банан (повторное нажатие снимает
    отметку) → «➡️ Дальше (3)» → количество каждого в том же сообщении: «×2» коктейлю, курице числом 150, ▶ сам
    переходит к следующему, банану «2 шт»; 6000 г — подсказка о пределе, ввод остаётся; «✅ Записать (3)» — три
    записи с этими количествами и карточка дня; второе нажатие — «устарело», записей по-прежнему три."""
    await _three(world)
    await owner.tap("🍽 Еда")
    _, screen = owner.find_button_at("☑️ Выбрать несколько")
    assert (await owner.tap("☑️ Выбрать несколько")).startswith("☑️ Еда за 03.11. Отметьте блюда")
    for label in ("Коктейль", "Курица", "Банан", "✅ Банан", "Банан"):
        await owner.tap(label)
    assert {"✅ Коктейль", "✅ Курица", "✅ Банан", "➡️ Дальше (3)"} <= set(owner.labels())
    text = await owner.tap("➡️ Дальше (3)")
    assert text.startswith("🍽 Записать за 03.11:\n▶ Коктейль — 1 порция — 322 ккал\n• Курица — 100 г — 113 ккал\n"
                           "• Банан — 1 шт — 105 ккал\nВсего: 540 ккал")
    assert {"×0,5", "×1", "×1,5", "×2"} <= set(owner.labels())
    assert "▶ Курица — 100 г" in await owner.tap("×2")
    assert {"100 г", "150 г", "200 г", "300 г"} <= set(owner.labels())
    assert await owner.say("6000") == "Вес — от 1 до 5 000 г. Вы ввели 6 000"
    assert owner.sees("150 г")  # сообщение с количеством на месте, ввод остаётся
    text = await owner.say("150")
    assert "• Курица — 150 г — 169,5 ккал\n▶ Банан — 1 шт" in text
    text = await owner.tap("2 шт")
    assert "▶ Банан — 2 шт — 210 ккал" in text and "Всего: 1 023,5 ккал" in text
    edits = len(world.session.edits())
    await owner.tap("▶ Банан · 2 шт")  # то же содержимое — Telegram «не изменено», сообщение остаётся
    assert owner.latest_text() == text and len(world.session.edits()) == edits + 1
    data, message = owner.find_button_at("✅ Записать (3)")
    assert message == screen  # выбор и количество — в одном сообщении
    result = await owner.tap("✅ Записать (3)")
    assert result.startswith("🍽 Записано 3:\n• Коктейль — ×2: 644 ккал")
    assert "• Курица — 150 г: 169,5 ккал" in result and "• Банан — 2 шт: 210 ккал" in result
    assert "Факт      1024" in result or "Факт      1023" in result
    await owner.press_data(data, message)
    assert owner.latest_text() == STALE
    assert sorted((e.name, e.quantity) for e in await _entries(world)) == [
        ("Банан", 2), ("Коктейль", 2), ("Курица", 150)]


async def test_s157_multi_select_back_cancel_restart_other_day(world: World, owner: Persona) -> None:
    """S-157. «➡️ Дальше (0)» без отметок — подсказка, экран тот же; «← Выбор» возвращает отметки; блюдо скрыли
    посреди выбора — «устарело»; «✕ Отмена» —
    ничего не записано; уход посреди ввода в «🏠 Домой» — старая кнопка «устарела»; перезапуск бота посреди
    количества — ввод продолжается и записывается (сообщение удалили — бот присылает новое);
    «📅 Другой день» → «Вчера» — записи за 02.11."""
    await _three(world)
    await owner.tap("🍽 Еда")
    await owner.tap("☑️ Выбрать несколько")
    await owner.tap("➡️ Дальше (0)")
    assert owner.latest_text().startswith("☑️ Еда за 03.11.")
    await owner.tap("Курица")
    await owner.tap("➡️ Дальше (1)")
    await owner.tap("← Выбор")
    assert "✅ Курица" in owner.labels()
    await owner.tap("➡️ Дальше (1)")
    food, actor = world.service("food"), await _actor(world)
    chicken = next(i for i in await food.items(actor) if i.name == "Курица")
    await food.update_item(actor, chicken.public_id, active=False)  # скрыли в другом окне
    assert await owner.tap("✅ Записать (1)") == STALE
    await food.update_item(actor, chicken.public_id, active=True)
    await owner.tap("🍽 Еда")
    await owner.tap("☑️ Выбрать несколько")
    await food.update_item(actor, chicken.public_id, active=False)
    assert await owner.tap("Курица") == STALE
    await food.update_item(actor, chicken.public_id, active=True)
    await owner.tap("🍽 Еда")
    await owner.tap("☑️ Выбрать несколько")
    await owner.tap("✕ Отмена")
    await owner.tap("🍽 Еда")
    await owner.tap("☑️ Выбрать несколько")
    old = owner.find_button("Банан")
    await owner.tap("🏠 Домой")
    await owner.press_data(old)
    assert owner.latest_text() == STALE
    assert await _entries(world) == []
    await owner.tap("☰ Ещё")
    await owner.tap("📅 Другой день")
    await owner.tap("Вчера (02.11)")
    await owner.tap("🍽 Еда")
    await owner.tap("☑️ Выбрать несколько")
    await owner.tap("Банан")
    await owner.tap("Коктейль")
    assert (await owner.tap("➡️ Дальше (2)")).startswith("🍽 Записать за 02.11:\n▶ Банан")
    await world.restart()
    _, screen = owner.find_button_at("✅ Записать (2)")
    world.session.deleted.add((ADMIN_ID, screen))  # сообщение удалили — количество придёт новым сообщением
    assert (await owner.say("3")).startswith("🍽 Записать за 02.11:\n• Банан — 3 шт")
    await owner.tap("✅ Записать (2)")
    assert sorted((e.name, e.quantity, e.day) for e in await _entries(world)) == [
        ("Банан", 3, date(2026, 11, 2)), ("Коктейль", 1, date(2026, 11, 2))]


async def test_s158_my_recipes_stay_open(world: World, owner: Persona) -> None:
    """S-158. Правки 1.0.5: после нового рецепта, правки КБЖУ, названия и «Скрыть» бот остаётся в «⚙️ Мои
    рецепты и продукты» — список сразу под ответом, следующий рецепт можно вносить без «🍽 Еда» → «⚙️ Мои»."""
    await owner.tap("🍽 Еда")
    await owner.tap("⚙️ Мои")
    await owner.tap("➕ Новый рецепт или продукт")
    await owner.say("Омлет")
    await owner.tap("Порция")
    assert await owner.say("250 15 18 2") == "⚙️ Мои рецепты и продукты:"
    await owner.tap("➕ Новый рецепт или продукт")
    await owner.say("Сырники")
    await owner.tap("Порция")
    await owner.say("320 20 14 28 150")
    assert {"Омлет", "Сырники"} <= set(owner.labels())
    await owner.tap("Омлет")
    await owner.tap("✏️ Название")
    assert await owner.say("Омлет из 3 яиц") == "⚙️ Мои рецепты и продукты:"
    await owner.tap("Сырники")
    assert await owner.tap("🙈 Скрыть") == "⚙️ Мои рецепты и продукты:"
    assert "🙈 Сырники" in owner.labels() and "Омлет из 3 яиц" in owner.labels()
