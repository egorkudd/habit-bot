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
    assert (await owner.say("400 30 10 50 160")).endswith("Прошлые записи не изменились.")
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
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("🍽 Рецепты и продукты")
    await owner.tap("➕ Новый рецепт или продукт")
    await owner.say("Творог 5%")
    await owner.tap("На 100 г")
    assert (await owner.say("121 17 5 1,8 30")).startswith("Добавлено: Творог 5% — на 100 г: 121 ккал")
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
