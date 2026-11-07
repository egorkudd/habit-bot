"""Поведенческие сценарии: команды текстом и заполнение через ИИ (раздел 3.10, 3.12, часть 9).

Модель — на записанных ответах (``FakeLlm``): ключа у владельца пока нет; живой прогон — ``tests/live``.
"""

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from habit_bot.channels.telegram.ui.callbacks import MenuCb
from habit_bot.modules.food.models import FoodEntry, FoodItem
from habit_bot.platform.ai.models import AiCommand
from tests.ai.golden import GOLDEN
from tests.ai.owner_data import fill
from tests.conftest import ADMIN_ID, OTHER_ID
from tests.fakes import FakeLlm
from tests.scenarios.conftest import finish_guest_onboarding, invite_guest, pass_onboarding
from tests.scenarios.harness import Persona, World

STALE = "Это меню устарело. Вот главное меню 👇"
PHRASE = GOLDEN[0]["phrase"]  # «вчера на обед было 2 бедра и пакет гречи, а коктейль сегодня удали»
CARD = ("Понял так:\n1. ➕ 02.11 Еда: Куриное бедро × 2 — 500 ккал\n"
        "2. ➕ 02.11 Еда: Гречка сухая (пакет 80 г) — 288,8 ккал\n3. 🗑 03.11 Еда: Коктейль (09:12)")


@pytest.fixture
async def ai_world(settings: Any, fake_session: Any, clock: Any, geocoder: Any) -> AsyncIterator[World]:
    llm = FakeLlm({case["phrase"]: case["reply"] for case in GOLDEN})
    w = await World(settings, fake_session, clock, geocoder, llm=llm).start()
    yield w
    await w.stop()


@pytest.fixture
async def me(ai_world: World) -> Persona:
    """Владелец прошёл анкету, его рецепты, привычки и зарядка уже внесены (раздел 6.2)."""
    user = ai_world.person(ADMIN_ID, "Егор")
    await pass_onboarding(user)
    actor = await ai_world.service("users.sign_in").execute(ADMIN_ID, "")
    await fill(ai_world.app, actor, ai_world.clock)
    return user


async def _entries(world: World) -> list[FoodEntry]:
    async with world.app.ctx.uow() as uow:
        return list((await uow.session.execute(select(FoodEntry).where(FoodEntry.deleted_at.is_(None))
                                               .order_by(FoodEntry.id))).scalars().all())


async def test_s92_confirm_drop_undo(ai_world: World, me: Persona) -> None:
    """S-92. Раздел 9: фраза → карточка с 3 действиями, данные не меняются до «Выполнить всё»; «Убрать 3» исключает
    удаление; после выполнения «↩️ Отменить всё» возвращает данные как было."""
    before = [(e.name, e.day) for e in await _entries(ai_world)]
    assert await me.say(PHRASE) == CARD
    assert me.labels() == ["✅ Выполнить всё", "✏️ Исправить", "Убрать 1", "Убрать 2", "Убрать 3", "✕ Отмена"]
    assert [(e.name, e.day) for e in await _entries(ai_world)] == before
    assert (await me.tap("Убрать 3")).endswith("Гречка сухая (пакет 80 г) — 288,8 ккал")
    result = await me.tap("✅ Выполнить всё")
    assert result.startswith("Готово:\n1. ➕ 02.11 Еда: Куриное бедро × 2 — 500 ккал\n2. ➕ 02.11 Еда: Гречка")
    assert "<pre>02.11, пн" in result  # карточка дня, куда записано
    after = [(e.name, e.day) for e in await _entries(ai_world)]
    assert ("Куриное бедро", date(2026, 11, 2)) in after and ("Коктейль", date(2026, 11, 3)) in after
    assert (await me.tap("↩️ Отменить всё")).startswith("↩️ Отменено, данные как было (действий: 2)")
    assert [(e.name, e.day) for e in await _entries(ai_world)] == before


async def test_s93_question_with_buttons(ai_world: World, me: Persona) -> None:
    """S-93. Раздел 9: неоднозначное «творог» → «Какой творог?» с кнопками рецептов; выбор — разбор заново."""
    ai_world.llm.replies["Ответ на вопрос «Какой творог?»: Творог ужин"] = {"actions": [
        {"type": "food.add", "day": "2026-11-03", "item": "Творог ужин"}]}
    assert await me.say("творог") == "Какой творог?"
    assert me.labels() == ["Творог ужин", "Творог 5%", "✕ Отмена"]
    assert await me.tap("Творог ужин") == "Понял так:\n1. ➕ 03.11 Еда: Творог ужин — 421 ккал"


async def test_s94_model_down_and_no_money(ai_world: World, me: Persona) -> None:
    """S-94. Раздел 9: API недоступен → «попробуйте кнопками», данные не меняются, администратору — LLM-DOWN;
    закончился баланс → разбор выключен, администратору — LLM-402."""
    before = len(await _entries(ai_world))
    ai_world.llm.fail = "LLM-DOWN"
    assert await me.say(PHRASE) == ("Разбор текстом сейчас не отвечает. Попробуйте через пару минут или кнопками. "
                                    "Ничего не изменено")
    assert any(t.startswith("🛑 Провайдер ИИ не отвечает") for t in me.texts())
    ai_world.llm.fail = "LLM-402"
    assert await me.say(PHRASE) == ("Разбор текстом временно выключен. Администратор уже знает. "
                                    "Кнопки работают как обычно")
    assert any(t.startswith("💸 На балансе провайдера ИИ 0 $") for t in me.texts())
    assert len(await _entries(ai_world)) == before
    ai_world.llm.fail = None
    ai_world.llm.invalid = 1  # не JSON — один повтор
    assert await me.say(PHRASE) == CARD
    ai_world.llm.invalid = 2
    assert (await me.say(PHRASE)).startswith("Разбор текстом сейчас не отвечает")


async def test_s95_limits(ai_world: World, me: Persona) -> None:
    """S-95. Ограничения: текст длиннее 1000 символов; 50 разборов в сутки; месячный бюджет — разбор выключен,
    администратору — LLM-BUDGET; 80% бюджета — предупреждение."""
    assert await me.say("а" * 1001) == "Текст длиннее 1000 символов. Разбейте на части"
    commands = ai_world.service("ai_commands")
    commands.budget.daily_limit = 2
    await me.say("как дела?")
    assert await me.say("как дела?") == "Не понял, что записать. Попробуйте так: „2 бедра на обед“ или „планка 6:15“"
    assert await me.say(PHRASE) == ("Сегодня использованы все 2 разборов текстом. Счётчик обнулится в 04:00, "
                                    "а пока — кнопками")
    commands.budget.daily_limit = 50
    ai_world.llm.tokens = (1_000_000, 0, 2_000_000)  # 0,3 $ + 2,4 $ = 2,7 $ за раз
    await me.say(PHRASE)
    await me.say(PHRASE)
    assert any(t.startswith("📊 Потрачено") for t in me.texts())
    assert (await me.say(PHRASE)).startswith("Разбор текстом временно выключен")
    assert any(t.startswith("Лимит 5 $ на ИИ в этом месяце исчерпан") for t in me.texts())


async def test_s96_foreign_and_missing_objects(ai_world: World, me: Persona) -> None:
    """S-96. Раздел 9: действия с несуществующими объектами отбрасываются с причиной; гость не видит рецептов
    владельца (его «Коктейль» — не найден) и не может нажать карточку владельца."""
    ai_world.llm.replies["удали шаурму сегодня и выпил витамины"] = {"actions": [
        {"type": "food.delete", "day": "2026-11-03", "item": "Шаурма"},
        {"type": "habit.mark", "day": "2026-11-03", "habit": "Витамины"},
        {"type": "nonsense", "day": "x"}]}
    text = await me.say("удали шаурму сегодня и выпил витамины")
    assert text == ("Понял так:\n1. ✅ 03.11 💊 Витамины ×1\n\nНе выполню:\n• Еда: «Шаурма» за 03.11 не найдено")
    owners_run = me.find_button("✅ Выполнить всё")
    guest = await invite_guest(ai_world, me, OTHER_ID, "Аня")
    await finish_guest_onboarding(guest)
    await guest.press_data(owners_run)
    assert guest.last() == "Эта кнопка не ваша — ничего не изменено. Вот главное меню 👇"
    ai_world.llm.replies["коктейль сегодня был двойной"] = GOLDEN[6]["reply"]
    assert await guest.say("коктейль сегодня был двойной") == "Не выполню:\n• Еда: «Коктейль» за 03.11 не найдено"


async def test_s97_fix_and_cancel(ai_world: World, me: Persona) -> None:
    """S-97. «✏️ Исправить» — уточнение, разбор повторяется с учётом прошлого понимания; «✕ Отмена» — ничего
    не записано, старая карточка устарела."""
    ai_world.llm.replies[PHRASE + "\nУточнение: бедро одно"] = {"actions": [
        {"type": "food.add", "day": "2026-11-02", "item": "Куриное бедро", "quantity": 1}]}
    await me.say(PHRASE)
    old_run = me.find_button("✅ Выполнить всё")
    assert await me.tap("✏️ Исправить") == "✏️ Напишите, что поправить, — разберу заново с учётом прошлого."
    assert await me.say("бедро одно") == "Понял так:\n1. ➕ 02.11 Еда: Куриное бедро — 250 ккал"
    request = ai_world.llm.requests[-1][-1]["content"]
    assert "Раньше понял так (исправь по сообщению): ➕ 02.11 Еда: Куриное бедро × 2" in request
    await me.press_data(old_run)
    assert me.last() == STALE
    before = len(await _entries(ai_world))
    assert await me.tap("✕ Отмена") == "Отменено, ничего не записано."
    assert len(await _entries(ai_world)) == before


async def test_s98_fill_mode_groups_pages_duplicates(ai_world: World, me: Persona) -> None:
    """S-98. Раздел 3.12: «✍️ Заполнить с помощью ИИ» — до 4000 символов; 12 действий — группы и страницы по 10;
    «Убрать «Цели»»; дубль рецепта — «Обновить» вместо второго, «Пропустить N»."""
    recipes = [{"type": "recipe.create", "name": f"Рецепт {i}", "kcal": 300 + i, "protein": 20, "fat": 10,
                "carbs": 30} for i in range(1, 11)]
    recipes.append({"type": "recipe.create", "name": "Коктейль", "kcal": 330, "protein": 27, "fat": 9, "carbs": 40})
    goal = {"type": "goal.set", "start_date": "2026-09-22", "kcal": 2410, "protein": 140, "fat": 70, "carbs": 305}
    text = "Мои рецепты: " + "; ".join(f"Рецепт {i} — {300 + i} ккал" for i in range(1, 11)) + " … " + "х" * 1200
    ai_world.llm.replies["Мои рецепты:"] = {"actions": [*recipes, goal]}
    await me.tap("☰ Ещё")
    await me.tap("⚙️ Настройки")
    assert (await me.tap("✍️ Заполнить с помощью ИИ")).startswith("✍️ Вставьте текстом")
    card = await me.say(text)
    assert card.startswith("Понял так:\nРецепты: 11 · Цели: 1\nСтраница 1 из 2\n1. 🍽 Рецепт «Рецепт 1»")
    assert "Дальше ▶" in me.labels() and "Убрать «Цели»" in me.labels()
    page = await me.tap("Дальше ▶")
    assert "11. ♻️ Рецепт «Коктейль» уже есть — обновлю: 330 ккал" in page and "Пропустить 11" in me.labels()
    await me.tap("Убрать «Цели»")
    result = await me.tap("✅ Выполнить всё")
    assert result.startswith("Готово:\n1. 🍽 Рецепт «Рецепт 1»")
    async with ai_world.app.ctx.uow() as uow:
        names = [i.name for i in (await uow.session.execute(select(FoodItem).where(
            FoodItem.user_id.is_not(None)))).scalars().all()]
    assert names.count("Коктейль") == 1 and "Рецепт 10" in names


async def test_s99_without_key(world: World, owner: Persona) -> None:
    """S-99. Ключа модели нет (как сейчас у владельца): «✍️ Текстом» — «пока не подключён», любой текст —
    подсказка с меню, кнопки работают."""
    await owner.tap("☰ Ещё")
    assert not owner.sees("✍️ Текстом")  # правки 1.0.2: кнопка убрана; старая работает
    actor = await world.service("users.sign_in").execute(owner.tg_id, "")
    await owner.press_data(MenuCb(o=actor.user_id, t=0, k="text").pack())
    assert owner.last() == "Разбор текстом пока не подключён. Кнопки работают как обычно"
    assert await owner.say("вчера съел 2 бедра") == "Не понял. Выберите раздел в меню 👇"
    assert (await owner.tap("🍽 Еда")).startswith("🍽 Еда за 03.11.")


async def test_s100_privacy_double_tap_and_late_undo(ai_world: World, me: Persona) -> None:
    """S-100. Раздел 7.2: в модель не уходят имя, Telegram-ID и профиль; двойное «Выполнить всё» — выполнено один
    раз; «Отменить всё» через 11 минут — поздно, данные остаются; токены и стоимость записаны."""
    await me.say(PHRASE)
    request = " ".join(m["content"] for m in ai_world.llm.requests[-1])
    for secret in ("Егор", str(ADMIN_ID), "178", "15.03.2003", "2003-03-15", "Москва", "75"):
        assert secret not in request
    assert "Коктейль" in request and '"today": "2026-11-03"' in request
    await me.tap_twice("✅ Выполнить всё")
    assert sum(e.name == "Куриное бедро" for e in await _entries(ai_world)) == 1
    ai_world.clock.advance(minutes=11)
    await me.tap("↩️ Отменить всё")
    assert me.session.answers()[-1].text == "Отменить можно только в течение 10 минут"
    assert sum(e.name == "Куриное бедро" for e in await _entries(ai_world)) == 1
    async with ai_world.app.ctx.uow() as uow:
        rows = (await uow.session.execute(select(AiCommand))).scalars().all()
    assert rows[-1].status == "done" and rows[-1].tokens_in == 3000 and rows[-1].cost_usd > 0


async def test_s101_approximate_dish_and_everything_else(ai_world: World, me: Persona) -> None:
    """S-101. Незнакомое блюдо — оценка «≈ приблизительно» и «💾 Сохранить как рецепт»; зарядка, привычки,
    тренировка, бег, выходной и вес одной командой записаны через те же сценарии, что и кнопки."""
    ai_world.llm.replies["всё сразу"] = {"actions": [
        *GOLDEN[15]["reply"]["actions"], *GOLDEN[9]["reply"]["actions"], *GOLDEN[2]["reply"]["actions"],
        *GOLDEN[10]["reply"]["actions"], *GOLDEN[3]["reply"]["actions"], *GOLDEN[7]["reply"]["actions"],
        *GOLDEN[8]["reply"]["actions"]]}
    await me.say("всё сразу")
    result = await me.tap("✅ Выполнить всё")
    assert "Шаурма ≈ 650 ккал" in result and "Присед со штангой: 110 кг 4×8" in result
    undo = me.find_button("↩️ Отменить всё")
    assert await me.tap("💾 «Шаурма» как рецепт") == "Рецепт «Шаурма» сохранён — он теперь в списке «🍽 Еда»."
    actor = await ai_world.service("users.sign_in").execute(ADMIN_ID, "")
    assert len(await ai_world.service("warmup").sessions(actor, date(2026, 11, 3))) == 3
    assert (await ai_world.service("habits").day(actor, date(2026, 11, 3)))[0].fact == 2
    assert await ai_world.service("days").is_day_off(actor, date(2026, 11, 2))
    assert (await ai_world.service("users.profiles").profile(actor)).weight_kg == Decimal("77.5")
    assert await ai_world.service("runs").count_between(actor, date(2026, 11, 3), date(2026, 11, 3)) == 1
    sessions = await ai_world.service("workouts").day_sessions(actor, date(2026, 11, 3))
    assert sessions[0].tonnage == 3520
    await me.press_data(undo)
    assert me.last().startswith("↩️ Отменено")
    assert not await ai_world.service("days").is_day_off(actor, date(2026, 11, 2))
    assert (await ai_world.service("users.profiles").profile(actor)).weight_kg == Decimal(75)
    assert await ai_world.service("workouts").day_sessions(actor, date(2026, 11, 3)) == []


async def test_s102_stale_card_buttons_and_failed_line(ai_world: World, me: Persona) -> None:
    """S-102. Старые кнопки отменённой карточки («Убрать», «Дальше», «Исправить», ответ на вопрос) — «меню
    устарело»; убрать единственный пункт — ничего не записано; запись удалили кнопками между карточкой и
    «Выполнить всё» — в итоге «Не получилось» с причиной, остальное выполнено."""
    await me.say("творог")
    option = me.find_button("Творог ужин")
    await me.tap("✕ Отмена")
    await me.press_data(option)
    assert me.last() == STALE
    await me.say(PHRASE)
    stale = [me.find_button(label) for label in ("Убрать 1", "✏️ Исправить")]
    await me.tap("✕ Отмена")
    for data in stale:
        await me.press_data(data)
        assert me.last() == STALE
    ai_world.llm.replies["две вещи"] = {"actions": [*GOLDEN[6]["reply"]["actions"], *GOLDEN[13]["reply"]["actions"]]}
    await me.say("две вещи")
    actor = await ai_world.service("users.sign_in").execute(ADMIN_ID, "")
    cocktail = next(e for e in await ai_world.service("food").entries(actor, date(2026, 11, 3)) if e.name == "Коктейль")
    await ai_world.service("food").delete_entry(actor, cocktail.public_id)
    result = await me.tap("✅ Выполнить всё")
    assert result.startswith("Готово:\n1. ✅ 03.11 💊 Витамины ×1\n\nНе получилось:\n• ✏️ 03.11 Еда: Коктейль")


async def test_s103_fill_page_after_cancel(ai_world: World, me: Persona) -> None:
    """S-103. Заполнение: «Дальше ▶» и «◀ Назад» листают ту же карточку; «Убрать «Рецепты»» убирает все пункты —
    ничего не записано, старая «Дальше ▶» — «меню устарело»."""
    ai_world.llm.replies["Рецепты списком"] = {"actions": [
        {"type": "recipe.create", "name": f"Блюдо {i}", "kcal": 100 + i, "protein": 1, "fat": 1, "carbs": 1}
        for i in range(1, 13)]}
    await me.tap("☰ Ещё")
    await me.tap("⚙️ Настройки")
    await me.tap("✍️ Заполнить с помощью ИИ")
    await me.say("Рецепты списком")
    nxt = me.find_button("Дальше ▶")
    assert "Страница 2 из 2" in await me.tap("Дальше ▶")
    assert "Страница 1 из 2" in await me.tap("◀ Назад")
    assert await me.tap("Убрать «Рецепты»") == "Все пункты убраны — ничего не записано."
    await me.press_data(nxt)
    assert me.last() == STALE
