"""Поведенческие сценарии: зарядка (раздел 3.3, часть 6)."""

from datetime import date
from typing import Any

from sqlalchemy import select

from habit_bot.modules.warmup.models import WarmupSession
from tests.conftest import ADMIN_ID, OTHER_ID
from tests.scenarios.conftest import finish_guest_onboarding, invite_guest
from tests.scenarios.harness import Persona, World

STALE = "Это меню устарело. Вот главное меню 👇"
LAST = "Отжимания 50 · Мостик 50 · Планка 5:45 · Спина 25"
LAST_LINES = "Отжимания — 50\nМостик — 50\nПланка — 5:45\nСпина — 25"


async def _actor(world: World) -> Any:
    return await world.service("users.sign_in").execute(ADMIN_ID, "")


async def _sessions(world: World) -> list[WarmupSession]:
    async with world.app.ctx.uow() as uow:
        return list((await uow.session.execute(
            select(WarmupSession).where(WarmupSession.deleted_at.is_(None)).order_by(WarmupSession.id)
        )).scalars().all())


async def _history(world: World, day: date = date(2026, 11, 2), values: tuple[int, ...] = (50, 50, 345, 25)) -> None:
    """Прошлая зарядка владельца 50 / 50 / 5:45 / 25."""
    warmup = world.service("warmup")
    actor = await _actor(world)
    exercises = await warmup.use_default_set(actor)
    await warmup.record(actor, {e.public_id: v for e, v in zip(exercises, values, strict=True)}, day=day)


async def test_s42_first_warmup(world: World, owner: Persona) -> None:
    """S-42. Первая зарядка: набора нет — «Взять набор по умолчанию»; прошлых значений нет — бот просит прислать
    результаты строкой по порядку (упражнения — столбиком), кнопки «Отжимания −5» / «Отжимания +5» по две в ряд;
    ошибки в строке — подсказка; «+» → «Записать» → 1-я за день."""
    assert (await owner.tap("🤸 Зарядка")).startswith("Набор зарядки пуст.")
    screen = await owner.tap("Взять набор по умолчанию")
    assert screen.startswith("🤸 Зарядка · 03.11 · 1-я за день\nОтжимания — 0\nМостик — 0\nПланка — 0:00\nСпина — 0\n")
    assert "Первая зарядка — пришлите результаты одной строкой по порядку, например: 20 20 1:00 20" in screen
    assert owner.labels()[:2] == ["Отжимания −5", "Отжимания +5"]
    assert await owner.say("сорок 0 5:30 0") == "Не понял число „сорок“. Напишите, например, 4,5 или 4.5"
    assert await owner.say("40 0") == (
        "Не хватает: Планка, Спина. Нужно значений: 4, по порядку набора. Например: 20 20 1:00 20")
    assert await owner.say("40 0 5:75 0") == "Время пишите как 5:45, 5.45 или в секундах: 345"
    assert (await owner.say("40 0 5.30 0 7")).startswith("Лишнее значение: 7.")
    assert "Планка — 5:30" in await owner.say("40 0 5.30 0")
    for _ in range(2):
        await owner.tap("Мостик +5")
    text = await owner.tap("💾 Записать")
    assert text.startswith("🤸 Зарядка 1-я за 03.11: Отжимания 40 · Мостик 10 · Планка 5:30 · Спина 0")
    assert "🤸 Зарядка 1/2" in text


async def test_s43_same_as_last_time(world: World, owner: Persona) -> None:
    """S-43. Раздел 9: после зарядки 50 / 50 / 5:45 / 25 экран сразу показывает те же значения — «Записать» одним
    нажатием записывает их; отдельной кнопки «Как в прошлый раз» нет; вторая за день — номер 2, «🤸 Зарядка 2/2»."""
    await _history(world, date(2026, 11, 3))
    screen = await owner.tap("🤸 Зарядка")
    assert screen == (f"🤸 Зарядка · 03.11 · 2-я за день\n{LAST_LINES}\n\n"
                      "«+» прибавит шаг. Или пришлите все значения по порядку: 50 50 5:45 25")
    assert owner.labels() == ["Отжимания +5", "Мостик +5", "Планка +15 сек", "Спина +5", "✏️ Изменить", "💾 Записать"]
    text = await owner.tap("💾 Записать")
    assert text.startswith(f"🤸 Зарядка 2-я за 03.11: {LAST}")
    assert "🤸 Зарядка 2/2" in text


async def test_s44_plus_steps(world: World, owner: Persona) -> None:
    """S-44. Раздел 9: «Планка +15 сек» → «Записать» записывает 50 / 50 / 6:00 / 25; «Отжимания +5» дважды → 60."""
    await _history(world)
    await owner.tap("🤸 Зарядка")
    assert "Планка — 6:00" in await owner.tap("Планка +15 сек")
    await owner.tap("Отжимания +5")
    assert "Отжимания — 60" in await owner.tap("Отжимания +5")
    text = await owner.tap("💾 Записать")
    assert text.startswith("🤸 Зарядка 1-я за 03.11: Отжимания 60 · Мостик 50 · Планка 6:00 · Спина 25")


async def test_s45_custom_step(world: World, owner: Persona) -> None:
    """S-45. Раздел 9: шаг отжиманий изменён на 10 → кнопка «Отжимания +10»; шаг «0» — подсказка."""
    await _history(world)
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("🤸 Зарядка: набор и цели")
    assert "Отжимания — шаг +5" in await owner.tap("📋 Набор и шаги")
    await owner.tap("Отжимания")
    await owner.tap("✏️ Шаг")
    assert await owner.say("0") == "Шаг — от 1 до 10 000. Вы ввели 0"
    assert (await owner.say("10")).startswith("📋 Набор зарядки")
    await owner.tap("🤸 Зарядка")
    assert "Отжимания +10" in owner.labels()


async def test_s46_edit_minus_plus_exact(world: World, owner: Persona) -> None:
    """S-46. Раздел 9: «Изменить» показывает «−» и «+» с названием для каждого упражнения по два в ряд;
    «Отжимания −5», точное «6:15» у планки — строкой всех значений; «← Готово» возвращает «+»."""
    await _history(world)
    await owner.tap("🤸 Зарядка")
    await owner.tap("✏️ Изменить")
    assert [row for row in _rows(owner)][:4] == [["Отжимания −5", "Отжимания +5"], ["Мостик −5", "Мостик +5"],
                                                  ["Планка −15 сек", "Планка +15 сек"], ["Спина −5", "Спина +5"]]
    assert "Отжимания — 45" in await owner.tap("Отжимания −5")
    assert "Планка — 6:15" in await owner.say("45 50 6:15 25")
    await owner.tap("✏️ Изменить")
    await owner.tap("← Готово")
    assert owner.sees("Планка +15 сек") and not owner.sees("Планка −15 сек")
    text = await owner.tap("💾 Записать")
    assert "Отжимания 45 · Мостик 50 · Планка 6:15 · Спина 25" in text


async def test_s47_abandoned_draft(world: World, owner: Persona) -> None:
    """S-47. Раздел 9: черновик «Планка +15 сек» без «Записать», 15 минут — зарядка не записана; старая кнопка
    «устарела»; следующий экран снова начинается со значений прошлой зарядки."""
    await _history(world)
    await owner.tap("🤸 Зарядка")
    await owner.tap("Планка +15 сек")
    sent = len(owner.texts())
    await world.wait(minutes=15)
    assert len(owner.texts()) == sent
    assert await owner.tap("💾 Записать") == STALE
    assert len(await _sessions(world)) == 1
    assert LAST_LINES in await owner.tap("🤸 Зарядка")


async def test_s48_other_day_uses_earlier_warmup(world: World, owner: Persona) -> None:
    """S-48. Раздел 3.7: в режиме «Другой день» 01.11 черновик берёт зарядку до этой даты (31.10), а не более
    позднюю (02.11); «Записать» записывает её; номер — следующий в том дне."""
    await _history(world, date(2026, 10, 31), (40, 40, 300, 20))
    await _history(world, date(2026, 11, 2))
    await owner.tap("☰ Ещё")
    await owner.tap("📅 Другой день")
    await owner.say("01.11")
    assert (await owner.tap("🤸 Зарядка")).startswith("🤸 Зарядка · 01.11 · 1-я за день\nОтжимания — 40")
    text = await owner.tap("💾 Записать")
    assert text.startswith("🤸 Зарядка 1-я за 01.11: Отжимания 40 · Мостик 40 · Планка 5:00 · Спина 20")


async def test_s49_personal_goal(world: World, owner: Persona) -> None:
    """S-49. Личная цель «Планка 11:00 к 03.12.2026»: после записи — строка прогресса с нужным темпом."""
    await _history(world)
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("🤸 Зарядка: набор и цели")
    await owner.tap("🎯 Личные цели")
    await owner.tap("➕ Новая цель")
    await owner.tap("Планка")
    assert await owner.say("11:00 03.12.2025") == "Дату пишите как 20.10 или 20.10.2026"
    assert (await owner.say("11:00 03.12.2026")).startswith("Цель сохранена.\n🎯 Планка: лучший 5:45 · цель 11:00")
    await owner.tap("🤸 Зарядка")
    await owner.tap("Планка +15 сек")
    text = await owner.tap("💾 Записать")
    assert "🎯 Планка: лучший 6:00 · цель 11:00 к 03.12 · осталось 5:00 · нужно +10 сек/день" in text


async def test_s50_edit_set(world: World, owner: Persona) -> None:
    """S-50. Набор меняется: добавить «Приседания», убрать «Спина», поднять «Приседания» — у каждого упражнения своё
    меню «✏️ Шаг» / «⬆ Выше» / «✕ Убрать»; экран зарядки по-новому; прошлые зарядки не изменились."""
    await _history(world)
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("🤸 Зарядка: набор и цели")
    await owner.tap("📋 Набор и шаги")
    await owner.tap("➕ Добавить упражнение")
    await owner.say("Приседания")
    await owner.tap("Повторы")
    assert owner.replies()[0] == "«Приседания» добавлено в набор, шаг +5."
    assert owner.labels()[:5] == ["Отжимания", "Мостик", "Планка", "Спина", "Приседания"]
    back = owner.find_button("Спина")
    await owner.tap("Спина")
    assert owner.labels() == ["✏️ Шаг", "⬆ Выше", "✕ Убрать", "← Набор"]
    await owner.tap("✕ Убрать")
    await owner.press_data(back)  # старая кнопка убранного упражнения — снова список набора
    assert owner.last().startswith("📋 Набор зарядки")
    await owner.tap("Приседания")
    assert "2. Мостик — шаг +5\n3. Приседания — шаг +5\n4. Планка" in await owner.tap("⬆ Выше")
    await owner.tap("🤸 Зарядка")
    assert "Отжимания — 50\nМостик — 50\nПриседания — 0\nПланка — 5:45\n\n" in owner.last()
    (session,) = await _sessions(world)
    assert session.number == 1


def _rows(user: Persona) -> list[list[str]]:
    """Ряды кнопок под последним сообщением с кнопками — как их видит пользователь."""
    for m in reversed(user._mine()):
        rows = getattr(m.reply_markup, "inline_keyboard", None)
        if rows:
            return [[b.text for b in row] for row in rows]
    raise AssertionError("кнопок нет")


async def test_s51_double_save_and_undo(world: World, owner: Persona) -> None:
    """S-51. Двойная доставка «Записать» — одна зарядка; «Отменить» удаляет; «📅 На вчера» переносит."""
    await _history(world)
    await owner.tap("🤸 Зарядка")
    await owner.tap_twice("💾 Записать")
    assert len(await _sessions(world)) == 2
    assert (await owner.tap("Отменить")).startswith("Зарядка 1-я за 03.11 удалена.")
    await owner.tap("🤸 Зарядка")
    await owner.tap("💾 Записать")
    await owner.tap("📅 На вчера")
    sessions = await _sessions(world)
    assert [(s.day, s.number) for s in sessions] == [(date(2026, 11, 2), 1), (date(2026, 11, 2), 2)]


async def test_s52_restart_mid_draft(world: World, owner: Persona) -> None:
    """S-52. Черновик «+15 сек», бот перезапустился, через 5 минут «Записать» — записана планка 6:00."""
    await _history(world)
    await owner.tap("🤸 Зарядка")
    await owner.tap("Планка +15 сек")
    await world.restart()
    await world.wait(minutes=5)
    assert "Планка 6:00" in await owner.tap("💾 Записать")  # в итоге — строкой через « · »


async def test_s53_foreign_warmup_button(world: World, owner: Persona) -> None:
    """S-53. Гость нажимает «Отменить» под зарядкой владельца — отказ, зарядка на месте; у гостя свой пустой набор."""
    await _history(world)
    await owner.tap("🤸 Зарядка")
    await owner.tap("💾 Записать")
    owners_undo = owner.find_button("Отменить")
    guest = await invite_guest(world, owner, OTHER_ID, "Аня")
    await finish_guest_onboarding(guest)
    await guest.press_data(owners_undo)
    assert guest.last() == "Эта кнопка не ваша — ничего не изменено. Вот главное меню 👇"
    assert len(await _sessions(world)) == 2
    assert (await guest.tap("🤸 Зарядка")).startswith("Набор зарядки пуст.")


async def test_s123_press_that_changes_nothing(world: World, owner: Persona) -> None:
    """S-123. Нажатие, после которого экран не меняется («Отжимания −5» при 0, двойное «✏️ Изменить», «← Готово»
    дважды): Telegram отвечает «message is not modified» — бот молчит, без ⚠️ E-xxxx и без оповещения
    администратору; черновик продолжает работать."""
    await owner.tap("🤸 Зарядка")
    await owner.tap("Взять набор по умолчанию")
    sent = len(owner.texts())
    await owner.tap("Отжимания −5")  # уже 0 — ниже не уходит, экран тот же
    await owner.tap("Мостик +5")
    edit = owner.find_button("Мостик −5")
    await owner.press_data(edit, owner.find_button_at("Мостик −5")[1])
    await owner.press_data(edit, owner.find_button_at("Мостик −5")[1])  # второй раз — уже 0
    assert len(owner.texts()) == sent  # ни ⚠️ пользователю, ни оповещения администратору (тот же чат)
    assert "Мостик — 0" in owner.last()
    assert (await owner.tap("💾 Записать")).startswith("🤸 Зарядка 1-я за 03.11")
