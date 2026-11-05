"""Поведенческие сценарии: свои привычки (раздел 3.6, 4.6, часть 7)."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from habit_bot.modules.habits.domain.habits import Measure
from habit_bot.modules.habits.models import HabitEntry
from habit_bot.modules.habits.telegram.handlers import home_key
from tests.conftest import ADMIN_ID, OTHER_ID
from tests.fakes import message_update
from tests.scenarios.conftest import finish_guest_onboarding, invite_guest, pass_onboarding
from tests.scenarios.harness import Persona, World

STALE = "Это меню устарело. Вот главное меню 👇"
TODAY = date(2026, 11, 3)  # вторник


async def _actor(world: World, tg_id: int = ADMIN_ID) -> Any:
    return await world.service("users.sign_in").execute(tg_id, "")


async def _habit(world: World, key: str, *, home: bool = False, tg_id: int = ADMIN_ID) -> Any:
    actor = await _actor(world, tg_id)
    habit = await world.service("habits").from_template(actor, key)
    if home:
        await world.app.telegram.screens.set_on_home(actor, home_key(habit), True)
        user = next(p for p in world.people if p.tg_id == tg_id)
        await user.say("/start")  # новая клавиатура приходит со следующим сообщением бота
    return habit


async def _entries(world: World) -> list[HabitEntry]:
    async with world.app.ctx.uow() as uow:
        return list((await uow.session.execute(
            select(HabitEntry).where(HabitEntry.deleted_at.is_(None)).order_by(HabitEntry.id))).scalars().all())


def _rows(user: Persona) -> list[list[str]]:
    for m in reversed(user._mine()):
        rows = getattr(m.reply_markup, "inline_keyboard", None)
        if rows:
            return [[b.text for b in row] for row in rows]
    raise AssertionError("кнопок нет")


async def test_s62_eyes_from_template_one_tap(world: World, owner: Persona) -> None:
    """S-62. Раздел 9: шаблон «Зарядка для глаз» с «На главном экране» добавляет кнопку «👁 Глаза»; одно нажатие →
    «👁 Зарядка для глаз — 1/3» с «Отменить», «+ ещё», «Другое значение», «📅 На вчера»; «Отменить» удаляет."""
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("✅ Свои привычки")
    await owner.tap("➕ Новая")
    assert (await owner.tap("👁 Зарядка для глаз")).startswith("Добавлено: 👁 Зарядка для глаз — отметка, цель 3")
    assert await owner.tap("🏠 Да") == "Готово: «👁 Глаза» на главном экране 👇"
    assert any("👁 Глаза" in row for row in owner.keyboard())
    text = await owner.tap("👁 Глаза")
    assert text.startswith("👁 Зарядка для глаз — 1/3\n<pre>03.11, вт")
    assert "👁 1/3" in text  # строка привычек в карточке дня
    assert [b for row in _rows(owner) for b in row] == ["Отменить", "+ ещё", "Другое значение", "📅 На вчера"]
    assert (await owner.tap("Отменить")).startswith("Отметка отменена: 👁 Зарядка для глаз — 0/3")
    assert await _entries(world) == []


async def test_s63_goal_done_and_streak(world: World, owner: Persona) -> None:
    """S-63. Раздел 9: цель 3/3 → «✅ Глаза 3/3 · серия …»; при выполненной цели два прошлых дня серия сегодня —
    3 дня; «+ ещё» под ответом прибавляет шаг."""
    habit = await _habit(world, "eyes", home=True)
    actor = await _actor(world)
    habits = world.service("habits")
    for day in (TODAY - timedelta(days=2), TODAY - timedelta(days=1)):
        for _ in range(3):
            await habits.mark(actor, habit.public_id, day=day)
    await owner.tap("👁 Глаза")
    assert (await owner.tap("+ ещё")).startswith("👁 Зарядка для глаз — 2/3")
    assert (await owner.tap("+ ещё")).startswith("✅ Глаза 3/3 · серия 3 дня")
    assert (await owner.tap("+ ещё")).startswith("👁 Зарядка для глаз — 4/3")  # сверх цели — без повторного «✅»


async def test_s64_water_other_value(world: World, owner: Persona) -> None:
    """S-64. Раздел 9: «Вода»: нажатие +1, «Другое значение» → «полтора» — подсказка, «1.5» — 1,5 вместо 1;
    быстрые значения — кнопками."""
    await _habit(world, "water", home=True)
    assert (await owner.tap("💧 Вода")).startswith("💧 Вода — 1/8 стак.")
    assert (await owner.tap("Другое значение")).startswith("💧 Вода: сколько? Числом (стак.)")
    assert await owner.say("полтора") == "Не понял число „полтора“. Напишите, например, 4,5 или 4.5"
    assert (await owner.say("1.5")).startswith("💧 Вода — 1,5/8 стак.")
    assert [e.value for e in await _entries(world)] == [1.5]
    actor = await _actor(world)
    water = (await world.service("habits").habits(actor))[0]
    await world.service("habits").update(actor, water.public_id, quick=[Decimal("0.5"), Decimal(2)])
    await owner.tap("Другое значение")
    assert (await owner.tap("2 стак.")).startswith("💧 Вода — 2/8 стак.")


async def test_s65_mark_many(world: World, owner: Persona) -> None:
    """S-65. Раздел 9: «Отметить несколько» ничего не пишет до «Записать»; в «Другом дне» пишет в выбранную дату;
    «✕ Отмена» — ничего не записано."""
    for key in ("eyes", "vitamins", "no_sugar"):
        await _habit(world, key)
    await owner.tap("✅ Привычки")
    await owner.tap("☑️ Отметить несколько")
    await owner.tap("☐ 👁 Глаза")
    await owner.tap("☐ 💊 Витамины")
    assert owner.sees("💾 Записать (2)") and await _entries(world) == []
    await owner.tap("☑️ 💊 Витамины")  # передумал
    await owner.tap("✕ Отмена")
    assert await _entries(world) == []

    await owner.tap("☰ Ещё")
    await owner.tap("📅 Другой день")
    await owner.tap("Вчера (02.11)")
    await owner.tap("✅ Привычки")
    await owner.tap("☑️ Отметить несколько")
    await owner.tap("☐ 👁 Глаза")
    await owner.tap("☐ 🍬 Без сладкого")
    text = await owner.tap("💾 Записать (2)")
    assert text.startswith("Записано за 02.11: 👁 Глаза 1/3 · ✅ Без сладкого 1/1")
    assert {e.day for e in await _entries(world)} == {TODAY - timedelta(days=1)}


async def test_s66_streak_skips_day_off_and_rest_days(world: World, owner: Persona) -> None:
    """S-66. Раздел 4.6: серия не прерывается «Выходным» и днями не по расписанию; невыполненный сегодня день
    серию не обрывает, а пропуск по расписанию — обрывает."""
    actor = await _actor(world)
    habits = world.service("habits")
    habit = await _habit(world, "vitamins")
    await habits.update(actor, habit.public_id, weekdays=[0, 1, 2, 3, 4])  # по будням
    for day in (date(2026, 10, 27), date(2026, 10, 28), date(2026, 10, 30), date(2026, 11, 2)):
        await habits.mark(actor, habit.public_id, day=day)
    await world.service("days").toggle_day_off(actor, date(2026, 10, 29))  # чт — выходной
    assert await habits.streak_of(actor, habit.public_id, TODAY) == 4  # 27, 28, 30.10 и 02.11; выходные пропущены
    await habits.clear_day(actor, habit.public_id, date(2026, 10, 30))
    assert await habits.streak_of(actor, habit.public_id, TODAY) == 1  # пятница без отметки — серия с понедельника
    text = await owner.tap("✅ Привычки")
    assert "💊 Витамины 0/1" in [b for row in _rows(owner) for b in row]
    assert text.startswith("✅ Привычки за 03.11")


async def test_s67_list_sorted_and_updated_in_place(world: World, owner: Persona) -> None:
    """S-67. Раздел 3.6: список «Привычки» — встроенные «🍽 Еда» и «🤸 Зарядка» и свои; невыполненные сверху,
    выполненные ниже с ✅; нажатие обновляет то же сообщение (нового не приходит); привычки не по расписанию
    свёрнуты в строку и раскрываются; «🍽 Еда» открывает еду."""
    actor = await _actor(world)
    habits = world.service("habits")
    await _habit(world, "eyes")
    await _habit(world, "vitamins")
    sauna = await habits.create(actor, name="Сауна", emoji="🧖", measure=Measure.CHECK, weekdays=[5])
    await owner.tap("✅ Привычки")
    labels = [b for row in _rows(owner) for b in row]
    assert labels[:5] == ["🍽 Еда 0/2 800", "🤸 Зарядка 0/2", "🏋️ Тренировки за неделю 0/3", "👁 Глаза 0/3",
                          "💊 Витамины 0/1"]
    assert "💤 Не сегодня: Сауна" in labels and "🧖 Сауна 0" not in labels
    sent = len(owner.texts())
    await owner.tap("💊 Витамины 0/1")
    assert len(owner.texts()) == sent  # обновлено то же сообщение
    assert owner.session.answers()[-1].text.startswith("✅ Витамины 1/1 · серия 1 день")
    labels = [b for row in _rows(owner) for b in row]
    assert labels.index("✅ 💊 Витамины 1/1") > labels.index("👁 Глаза 0/3")
    await owner.tap("💤 Не сегодня: Сауна")
    assert "🧖 Сауна 0" in [b for row in _rows(owner) for b in row]
    await owner.tap("🧖 Сауна 0")
    assert any(e.habit_id for e in await _entries(world)) and sauna.weekdays == (5,)
    assert (await owner.tap("🍽 Еда 0/2 800")).startswith("🍽 Еда за 03.11.")


async def test_s68_once_habit_offers_unmark(world: World, owner: Persona) -> None:
    """S-68. Однократная привычка уже выполнена — нажатие в списке предлагает «Снять отметку»; «Оставить» ничего
    не меняет, «Снять отметку» удаляет записи дня."""
    await _habit(world, "vitamins")
    await owner.tap("✅ Привычки")
    await owner.tap("💊 Витамины 0/1")
    assert await owner.tap("✅ 💊 Витамины 1/1") == "💊 Витамины уже отмечено за 03.11."
    await owner.tap("Оставить")
    assert len(await _entries(world)) == 1
    await owner.tap("✅ Привычки")
    await owner.tap("✅ 💊 Витамины 1/1")
    assert (await owner.tap("Снять отметку")).startswith("Отметка снята: 💊 Витамины — 0/1")
    assert await _entries(world) == []


async def test_s69_own_habit_by_buttons(world: World, owner: Persona) -> None:
    """S-69. Своя привычка кнопками: «🧘 Медитация» → «Длительность» → цель «15» → «🏠 Да» — кнопка на главном;
    ошибки ввода — подсказка без сброса; дубль названия — отказ; «отмена» посреди — ничего не создано."""
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("✅ Свои привычки")
    await owner.tap("➕ Новая")
    await owner.tap("✍️ Своя")
    await owner.say("🧘 Медитация")
    await owner.tap("Длительность")
    assert await owner.say("пятнадцать") == "Не понял число „пятнадцать“. Напишите, например, 4,5 или 4.5"
    assert (await owner.say("15")).startswith("Добавлено: 🧘 Медитация — длительность, цель 15 мин в день, шаг 10")
    await owner.tap("🏠 Да")
    assert (await owner.tap("🧘 Медитация")).startswith("🧘 Медитация — 10/15 мин")

    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("✅ Свои привычки")
    await owner.tap("➕ Новая")
    await owner.tap("✍️ Своя")
    assert await owner.say("🧘 Медитация") == "Привычка „Медитация“ уже есть. Напишите другое название"
    await owner.say("📚 Страницы")
    await owner.tap("Количество")
    await owner.say("отмена")
    assert len(await world.service("habits").habits(await _actor(world))) == 1


async def test_s70_steps_ask_number_and_restart(world: World, owner: Persona) -> None:
    """S-70. «🚶 Шаги» без шага: нажатие спрашивает число; бот перезапустился, через 5 минут «8500» — записано
    8 500/10 000; двойная доставка нажатия на главном — одна запись."""
    await _habit(world, "steps", home=True)
    assert (await owner.tap("🚶 Шаги")).startswith("🚶 Шаги: сколько? Числом (шагов)")
    await world.restart()
    await world.wait(minutes=5)
    assert (await owner.say("8500")).startswith("🚶 Шаги — 8 500/10 000 шагов")
    await _habit(world, "eyes", home=True)
    raw = message_update(owner._next_id(), ADMIN_ID, "👁 Глаза")
    raw["message"]["date"] = int(world.clock.now().timestamp())
    for _ in range(2):
        await world.app.telegram.dispatcher.feed_raw_update(world.app.telegram.bot, dict(raw))
    assert len(await _entries(world)) == 2  # шаги и одна отметка глаз


async def test_s71_archive_restore_delete(world: World, owner: Persona) -> None:
    """S-71. Архив убирает привычку с главного экрана и из списка, история остаётся; «↩» возвращает; удаление —
    с подтверждением и вместе с историей."""
    await _habit(world, "eyes", home=True)
    await owner.tap("👁 Глаза")
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("✅ Свои привычки")
    await owner.tap("👁 Глаза")
    assert (await owner.tap("🗄 В архив")).startswith("👁 Глаза — в архиве")
    assert not any("👁 Глаза" in row for row in owner.keyboard())
    assert await owner.say("👁 Глаза") == "Не понял. Выберите раздел в меню 👇"
    assert len(await _entries(world)) == 1
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("✅ Свои привычки")
    await owner.tap("🗄 Архив (1)")
    await owner.tap("↩ 👁 Глаза")
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("✅ Свои привычки")
    await owner.tap("👁 Глаза")
    await owner.tap("🗑 Удалить")
    assert (await owner.tap("🗑 Да, удалить")) == "«Зарядка для глаз» удалена вместе с историей."
    assert await _entries(world) == []


async def test_s72_isolation_and_foreign_buttons(world: World, owner: Persona) -> None:
    """S-72. Раздел 9 «Изоляция»: у гостя свои привычки; «👁 Глаза» гостя не отмечает глаза владельца; чужая кнопка
    «Отменить» — отказ, запись владельца на месте."""
    await _habit(world, "eyes", home=True)
    await owner.tap("👁 Глаза")
    owners_undo = owner.find_button("Отменить")
    guest = await invite_guest(world, owner, OTHER_ID, "Аня")
    await finish_guest_onboarding(guest)
    assert await guest.say("👁 Глаза") == "Не понял. Выберите раздел в меню 👇"
    await guest.press_data(owners_undo)
    assert guest.last() == "Эта кнопка не ваша — ничего не изменено. Вот главное меню 👇"
    assert (await guest.tap("✅ Привычки")).startswith("✅ Привычки за 03.11\nСвоих привычек пока нет")
    assert len(await _entries(world)) == 1


async def test_s73_starter_kit_puts_eyes_on_home(world: World) -> None:
    """S-73. Раздел 6.2: «Примеры привычек» в анкете — после неё на главном экране «👁 Глаза», в списке — вода
    и витамины."""
    user = world.person(ADMIN_ID, "Егор")

    async def with_kit() -> None:
        await user.tap("☐ Примеры привычек")

    original = user.tap

    async def tap(label: str) -> str:
        if label == "Готово" and user.sees("☐ Примеры привычек"):
            await with_kit()
        return await original(label)

    user.tap = tap  # type: ignore[method-assign]
    await pass_onboarding(user)
    assert any("👁 Глаза" in row for row in user.keyboard())
    await user.tap("✅ Привычки")
    labels = [b for row in _rows(user) for b in row]
    assert {"👁 Глаза 0/3", "💧 Вода 0/8 стак.", "💊 Витамины 0/1"} <= set(labels)


async def test_s74_edit_goal_days_and_stale(world: World, owner: Persona) -> None:
    """S-74. Правка: цель «5», дни «Пн, Ср» — сегодня (вт) привычка свёрнута в «Не сегодня»; старая кнопка «Цель»
    после 15 минут — «меню устарело»."""
    await _habit(world, "eyes", home=True)
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("✅ Свои привычки")
    await owner.tap("👁 Глаза")
    await owner.tap("🎯 Цель")
    assert (await owner.say("5")).startswith("Сохранено ✅\n👁 Зарядка для глаз — отметка, цель 5 в день")
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("✅ Свои привычки")
    await owner.tap("👁 Глаза")
    await owner.tap("📅 Дни")
    for day in ("✅ Вт", "✅ Чт", "✅ Пт", "✅ Сб", "✅ Вс"):
        await owner.tap(day)
    assert (await owner.tap("💾 Сохранить")).endswith("Пн, Ср")
    await owner.tap("✅ Привычки")
    assert "💤 Не сегодня: Глаза" in [b for row in _rows(owner) for b in row]
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("✅ Свои привычки")
    await owner.tap("👁 Глаза")
    await owner.tap("🎯 Цель")
    stale = owner.find_button("Без цели")
    await world.wait(minutes=16)
    await owner.press_data(stale)
    assert owner.last() == STALE


async def _habit_menu(owner: Persona, label: str) -> None:
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("✅ Свои привычки")
    await owner.tap(label)


async def test_s75_settings_all_fields(world: World, owner: Persona) -> None:
    """S-75. Настройки привычки: шаг, быстрые значения, название с эмодзи, «Без цели», «Каждый день», порядок,
    «На главный» / «Убрать с главного»; своя «Количество» со своей единицей и без цели; главный экран полон."""
    await _habit(world, "water")
    await _habit_menu(owner, "💧 Вода")
    await owner.tap("➕ Шаг")
    assert await owner.say("ноль") == "Не понял число „ноль“. Напишите, например, 4,5 или 4.5"
    assert "шаг 0,5 стак." in await owner.say("0,5")
    await _habit_menu(owner, "💧 Вода")
    await owner.tap("⚡ Быстрые")
    assert (await owner.say("0,5 1 2")).startswith("Сохранено ✅")
    await _habit_menu(owner, "💧 Вода")
    assert "Быстрые значения: 0,5 стак., 1 стак., 2 стак." in owner.last()
    await owner.tap("⚡ Быстрые")
    await owner.tap("Очистить")
    await _habit_menu(owner, "💧 Вода")
    await owner.tap("🎯 Цель")
    assert "без цели" in await owner.tap("Без цели")
    await _habit_menu(owner, "💧 Вода")
    await owner.tap("➕ Шаг")
    assert "число при нажатии" in await owner.tap("Без шага")
    await _habit_menu(owner, "💧 Вода")
    await owner.tap("✏️ Название")
    assert (await owner.say("🥤 Вода с лимоном")).startswith("Сохранено ✅\n🥤 Вода с лимоном")
    await _habit_menu(owner, "🥤 Вода с лимоном")
    await owner.tap("📅 Дни")
    await owner.tap("Каждый день")
    assert (await owner.tap("💾 Сохранить")).endswith("каждый день")
    await _habit_menu(owner, "🥤 Вода с лимоном")
    await owner.tap("🏠 На главный")
    assert any("🥤 Вода с лимоном" in row for row in owner.keyboard())
    await _habit_menu(owner, "🥤 Вода с лимоном")
    assert await owner.tap("🏠 Убрать с главного") == "🥤 Вода с лимоном убрана с главного экрана 👇"

    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("✅ Свои привычки")
    await owner.tap("➕ Новая")
    await owner.tap("✍️ Своя")
    await owner.say("Страницы")
    await owner.tap("Количество")
    assert (await owner.say("x" * 17)).startswith("Единица")
    assert "например 8 (стр.)" in await owner.say("стр.")
    assert (await owner.tap("Без цели")).startswith("Добавлено: ⭐ Страницы — количество, без цели, шаг 1 стр.")
    await owner.tap("Нет")
    await _habit_menu(owner, "⭐ Страницы")
    assert "⭐ Страницы" in (await owner.tap("⬆ Выше")).split("\n")[2]

    actor = await _actor(world)
    for key in ("vitamins", "sleep", "reading"):
        await _habit(world, key, home=True)  # клавиатура: 5 разделов + 3 привычки = 8 > 7
    await _habit_menu(owner, "⭐ Страницы")
    await owner.tap("🏠 На главный")
    assert owner.session.answers()[-1].text.startswith("Главный экран полон")
    assert len(await world.app.telegram.screens.layout(actor) or []) == 7


async def test_s76_stale_and_wrong_presses(world: World, owner: Persona) -> None:
    """S-76. Старые и лишние нажатия: «Отменить» через сутки — «устарело»; кнопка удалённой привычки — «устарело»;
    «Записать (0)» — подсказка; «Без цели» после удаления привычки — «устарело»; «Сон» из списка спрашивает число."""
    sleep = await _habit(world, "sleep")
    await _habit(world, "eyes", home=True)
    await owner.tap("👁 Глаза")
    old_undo = owner.find_button("Отменить")
    world.clock.advance(hours=25)
    await owner.press_data(old_undo)
    assert owner.last() == STALE
    await owner.tap("✅ Привычки")
    assert (await owner.tap("😴 Сон 0/8 ч")).startswith("😴 Сон: сколько?")
    assert (await owner.say("7,5")).startswith("😴 Сон — 7,5/8 ч")
    await owner.tap("✅ Привычки")
    await owner.tap("☑️ Отметить несколько")
    assert "😴" not in " ".join(b for row in _rows(owner) for b in row)  # «Сон» — только числом
    await owner.tap("💾 Записать (0)")
    assert owner.session.answers()[-1].text == "Ничего не отмечено"
    await owner.tap("✅ Привычки")
    sleep_tap = owner.find_button("✅ 😴 Сон 7,5/8 ч") if owner.sees("✅ 😴 Сон 7,5/8 ч") else owner.find_button(
        "😴 Сон 7,5/8 ч")
    await _habit_menu(owner, "😴 Сон")
    await owner.tap("🎯 Цель")
    clear = owner.find_button("Без цели")
    actor = await _actor(world)
    await world.service("habits").delete(actor, sleep.public_id)
    await owner.press_data(clear)
    assert owner.last() == STALE
    await owner.press_data(sleep_tap)
    assert owner.last() == STALE
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("✅ Свои привычки")
    open_eyes = owner.find_button("👁 Глаза")
    await owner.tap("👁 Глаза")
    await owner.tap("🗑 Удалить")
    await owner.tap("🗑 Да, удалить")
    await owner.press_data(open_eyes)
    assert owner.last() == STALE
    assert not any("👁 Глаза" in row for row in owner.keyboard())


async def test_s77_from_more_and_archive_delete(world: World, owner: Persona) -> None:
    """S-77. «✅ Привычки» убрана с главного экрана — открывается из «Ещё»; удаление из архива — с подтверждением;
    повторное «Да, удалить» — «уже удалена»."""
    await _habit(world, "eyes")
    actor = await _actor(world)
    await world.app.telegram.screens.set_on_home(actor, "habits", False)
    await owner.say("/start")
    await owner.tap("☰ Ещё")
    assert (await owner.tap("✅ Привычки")).startswith("✅ Привычки за 03.11")
    await _habit_menu(owner, "👁 Глаза")
    await owner.tap("🗄 В архив")
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("✅ Свои привычки")
    await owner.tap("🗄 Архив (1)")
    await owner.tap("🗑")
    yes = owner.find_button("🗑 Да, удалить")
    await owner.tap("🗑 Да, удалить")
    await owner.press_data(yes)
    assert owner.last() == "Привычка уже удалена."
