"""Поведенческие сценарии: чистый чат, «🏠 Домой», «Ещё» и кнопки, которые помещаются (правки после части 6)."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from aiogram.types import BufferedInputFile, InputMediaDocument
from sqlalchemy import select

from habit_bot.channels.telegram.dialogs.policy import DIALOG, OTHER_DAY
from habit_bot.channels.telegram.ui.chat_log import ChatMessage
from habit_bot.channels.telegram.ui.routes import HOME_TEXT
from habit_bot.modules.food.domain.nutrition import Nutrients, Unit
from habit_bot.modules.food.models import FoodEntry
from habit_bot.modules.warmup.domain.warmup import Measure
from habit_bot.modules.warmup.models import WarmupSession
from tests.conftest import ADMIN_ID
from tests.scenarios.harness import Persona, World

STALE = "Это меню устарело. Вот главное меню 👇"


async def _actor(world: World) -> Any:
    return await world.service("users.sign_in").execute(ADMIN_ID, "")


async def _recipe(world: World, name: str = "Коктейль") -> None:
    await world.service("food").create_item(
        await _actor(world), name=name, kind="recipe", unit=Unit.PORTION,
        nutrients=Nutrients.of(322, 26, 9, 39), price=Decimal(140))


async def _count(world: World, model: Any) -> int:
    async with world.app.ctx.uow() as uow:
        rows = (await uow.session.execute(select(model).where(model.deleted_at.is_(None)))).scalars().all()
        return len(rows)


def _rows(user: Persona) -> list[list[str]]:
    for m in reversed(user._mine()):
        rows = getattr(m.reply_markup, "inline_keyboard", None)
        if rows:
            return [[b.text for b in row] for row in rows]
    raise AssertionError("кнопок нет")


async def test_s54_onboarding_leaves_only_result(world: World, owner: Persona) -> None:
    """S-54. После анкеты в чате нет её 12 вопросов и ответов — только итог «Готово, Егор! Норма…»; клавиатура
    внизу на месте."""
    screen = owner.on_screen()
    assert not any(text.startswith("Шаг ") for text in screen)
    assert any(text.startswith("Готово, Егор! Норма с сегодняшнего дня") for text in screen)
    assert owner.typed_on_screen() == []
    assert owner.keyboard()[-1][-2:] == ["🏠 Домой", "☰ Ещё"]


async def test_s55_food_other_keeps_only_card(world: World, owner: Persona) -> None:
    """S-55. «🍽 Еда» → «✍️ Другое» → строка с ошибкой → исправленная строка: меню, вопрос, подсказка и обе строки
    пользователя исчезают, в чате остаётся карточка записи; итог прошлого ввода тоже остаётся."""
    await _recipe(world)
    await owner.tap("🍽 Еда")
    first = await owner.tap("Коктейль")
    await owner.tap("🍽 Еда")
    await owner.tap("✍️ Другое")
    assert (await owner.say("Маффин 320 4,5 15")).startswith("Не хватает: углеводы")
    card = await owner.say("Маффин 320 4.5 15 41")
    screen = owner.on_screen()
    assert screen[-1] == card and card.startswith("🍽 Маффин — 1 порция: 320 ккал")
    assert first in screen  # прошлая запись — тоже итог, её не трогаем
    assert not any(t.startswith(("🍽 Еда за", "Одной строкой", "Не хватает")) for t in screen)
    assert owner.typed_on_screen() == []
    assert owner.keyboard()  # клавиатура не пропала


async def test_s56_food_card_buttons_fit_and_replace(world: World, owner: Persona) -> None:
    """S-56. Кнопки под карточкой еды — по две в ряд, подписи целиком; «×2» заменяет карточку (старая удалена,
    в чате одна карточка), «Отменить» — карточка сменяется сообщением «удалена»."""
    await _recipe(world)
    await owner.tap("🍽 Еда")
    await owner.tap("Коктейль")
    assert _rows(owner) == [["×0,5", "×2"], ["Отменить", "📅 На вчера"]]
    await owner.tap("×2")
    cards = [t for t in owner.on_screen() if t.startswith("🍽 Коктейль")]
    assert len(cards) == 1 and cards[0].startswith("🍽 Коктейль — ×2: 644 ккал")
    await owner.tap("Отменить")
    assert not any(t.startswith("🍽 Коктейль") for t in owner.on_screen())
    assert owner.on_screen()[-1].startswith("Запись «Коктейль» удалена.")


async def test_s57_home_button_mid_warmup(world: World, owner: Persona) -> None:
    """S-57. Посреди зарядки «🏠 Домой»: черновик и сообщение «🏠» исчезают, в чате остаётся одно «🏠 Главное
    меню», зарядка не записана, старая «💾 Записать» устарела; в режиме «Другой день» «🏠» его не выключает."""
    await world.service("warmup").use_default_set(await _actor(world))
    await owner.tap("🤸 Зарядка")
    await owner.say("50 50 5:45 25")
    save = owner.find_button("💾 Записать")
    await owner.tap("🏠 Домой")
    assert owner.on_screen() == [HOME_TEXT]
    assert not any(t.startswith("🤸 Зарядка ·") for t in owner.on_screen())
    assert owner.typed_on_screen() == [] and not owner.sees("💾 Записать")
    assert await world.app.telegram.dialogs.get((await _actor(world)).user_id, DIALOG) is None
    await owner.press_data(save)  # нажатие, которое ушло раньше, чем исчезло сообщение
    assert owner.last() == STALE
    assert await _count(world, WarmupSession) == 0

    await owner.tap("☰ Ещё")
    await owner.tap("📅 Другой день")
    await owner.tap("Вчера (02.11)")
    await owner.tap("🍽 Еда")
    await owner.tap("🏠 Домой")
    assert owner.keyboard()[0] == ["📅 02.11 ✕ Вернуться к сегодня"]
    assert await world.app.telegram.dialogs.day((await _actor(world)).user_id, OTHER_DAY) == date(2026, 11, 2)


async def test_s58_hidden_sections_in_more(world: World, owner: Persona) -> None:
    """S-58. Раздел 3.1 (правки 1.0.2): «🍽 Еда» и «🤸 Зарядка» убраны с главного экрана — их нет ни внизу, ни в
    «☰ Ещё»: это привычки, они открываются из «✅ Привычки» так же, как с клавиатуры. Убранные «📊 Итоги» — в «Ещё»."""
    await _recipe(world)
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("🏠 Главный экран")
    await owner.tap("☑ 🍽 Еда")
    await owner.tap("☑ 🤸 Зарядка")
    await owner.tap("☑ 🏋️ Тренировка")
    await owner.tap("☑ 📊 Итоги")
    await owner.tap("✅ Готово")
    assert not any("🍽 Еда" in row or "🤸 Зарядка" in row for row in owner.keyboard())
    await owner.tap("☰ Ещё")
    assert owner.labels()[0] == "📊 Итоги"
    assert not any(b.startswith(("🍽", "🤸", "🏋️")) for b in owner.labels())
    await owner.tap("✅ Привычки")
    food = next(b for b in owner.labels() if b.startswith("🍽 Еда"))
    assert any(b.startswith("🏋️") for b in owner.labels())
    assert (await owner.tap(food)).startswith("🍽 Еда за 03.11.")
    assert (await owner.tap("Коктейль")).startswith("🍽 Коктейль — 1 порция")
    await owner.tap("✅ Привычки")
    assert (await owner.tap(next(b for b in owner.labels() if "Зарядка" in b))).startswith("Набор зарядки пуст.")


async def test_s59_restart_mid_input_still_cleans(world: World, owner: Persona) -> None:
    """S-59. «✍️ Другое», бот перезапустился, через 5 минут строка — запись есть, вопросы до перезапуска тоже
    убраны (след хранится в базе)."""
    await owner.tap("🍽 Еда")
    await owner.tap("✍️ Другое")
    await world.restart()
    await world.wait(minutes=5)
    await owner.say("Маффин 320 4.5 15 41")
    assert not any(t.startswith(("🍽 Еда за", "Одной строкой")) for t in owner.on_screen())
    assert await _count(world, FoodEntry) == 1


async def test_s60_cancel_and_abandon(world: World, owner: Persona) -> None:
    """S-60. «✕ Отмена» убирает вопросы ввода и оставляет «Отменено…»; брошенный на 15 минут ввод бот молча
    сбрасывает, а его сообщения уберёт следующий итог."""
    await owner.tap("🍽 Еда")
    await owner.tap("✍️ Другое")
    assert await owner.tap("✕ Отмена") == "Отменено, ничего не записано."
    assert not any(t.startswith(("🍽 Еда за", "Одной строкой")) for t in owner.on_screen())
    assert owner.on_screen()[-1] == "Отменено, ничего не записано."

    await _recipe(world)
    await owner.tap("🍽 Еда")
    await owner.tap("✍️ Другое")
    shown = len(owner.texts())
    await world.wait(minutes=16)
    assert len(owner.texts()) == shown
    await owner.tap("🍽 Еда")
    await owner.tap("Коктейль")
    assert not any(t.startswith(("🍽 Еда за", "Одной строкой")) for t in owner.on_screen())


async def test_s61_long_names_get_own_row(world: World, owner: Persona) -> None:
    """S-61. Раскладка по ширине подписи: короткие рецепты — по два в ряд, длинное название — один в ряду;
    в зарядке длинное своё упражнение — «+» в отдельном ряду, ничего не обрезается."""
    for name in ("Овсянка", "Омлет", "Салат с тунцом и авокадо", "Чай"):
        await _recipe(world, name)
    await owner.tap("🍽 Еда")
    assert _rows(owner)[:3] == [["Овсянка", "Омлет"], ["Салат с тунцом и авокадо"], ["Чай"]]
    warmup = world.service("warmup")
    actor = await _actor(world)
    await warmup.use_default_set(actor)
    await warmup.add_exercise(actor, name="Подъёмы на носки стоя", measure=Measure.REPS)
    await owner.tap("🤸 Зарядка")  # первая зарядка — сразу «−» и «+»
    rows = _rows(owner)
    assert rows[0] == ["Отжимания −5", "Отжимания +5"]
    assert ["Подъёмы на носки стоя −5"] in rows and ["Подъёмы на носки стоя +5"] in rows
    await owner.say("50 50 5:45 25 30")
    assert ["Подъёмы на носки стоя +5"] in _rows(owner) and ["Отжимания +5", "Мостик +5"] in _rows(owner)


async def test_s134_home_wipes_whole_chat_but_files(world: World, owner: Persona) -> None:
    """S-134. Правки 1.0.2: «🏠 Домой» очищает всю переписку — итоги записей, ответы бота, свои сообщения
    пользователя и сообщения фоновых задач; файлы (бэкап, экспорт) остаются; в чате одно «🏠 Главное меню» с
    клавиатурой. Повторное «🏠 Домой» — снова одно сообщение."""
    await _recipe(world)
    await owner.tap("🍽 Еда")
    assert (await owner.tap("Коктейль")).startswith("🍽 Коктейль — 1 порция")
    await owner.say("что-то непонятное")
    bot = world.app.telegram.bot
    reminder = await bot.send_message(ADMIN_ID, "💧 Напоминание")  # как фоновая задача: вне ответа пользователю
    backup = await bot.send_document(ADMIN_ID, BufferedInputFile(b"secret", filename="habit-bot.db.enc"))
    group = await bot.send_media_group(ADMIN_ID, [InputMediaDocument(media=BufferedInputFile(b"1", filename="a.csv")),
                                                  InputMediaDocument(media=BufferedInputFile(b"2", filename="b.csv"))])
    await owner.tap("🏠 Домой")
    assert owner.on_screen() == [HOME_TEXT]
    assert owner.typed_on_screen() == []
    assert owner.session.is_deleted(ADMIN_ID, reminder.message_id)
    assert not any(owner.session.is_deleted(ADMIN_ID, m.message_id) for m in (backup, *group))
    assert owner.keyboard()[-1][-2:] == ["🏠 Домой", "☰ Ещё"]
    await owner.tap("🏠 Домой")
    assert owner.on_screen() == [HOME_TEXT]


async def test_s135_home_after_restart_skips_old(world: World, owner: Persona) -> None:
    """S-135. Журнал чата переживает перезапуск бота; сообщения старше 47 часов «🏠 Домой» не трогает (Telegram
    их удалить не даст), а их строки в журнале стираются."""
    await owner.say("старое")
    old = owner.typed[-1]
    world.clock.advance(hours=48)
    await world.restart()
    await owner.say("новое")
    fresh = owner.typed[-1]
    await owner.tap("🏠 Домой")
    assert owner.session.is_deleted(ADMIN_ID, fresh) and not owner.session.is_deleted(ADMIN_ID, old)
    async with world.app.ctx.uow() as uow:
        stamps = (await uow.session.execute(select(ChatMessage.sent_at))).scalars().all()
    assert stamps and all(world.clock.now() - s < timedelta(hours=47) for s in stamps)
