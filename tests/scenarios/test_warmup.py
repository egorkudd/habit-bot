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
    """S-42. Первая зарядка: набора нет — «Взять набор по умолчанию»; прошлых значений нет — бот просит ввести
    стартовые, «Как в прошлый раз» скрыта; «+» и ввод числа → «Записать» → 1-я за день."""
    assert (await owner.tap("🤸 Зарядка")).startswith("Набор зарядки пуст.")
    screen = await owner.tap("Взять набор по умолчанию")
    assert screen.startswith("🤸 Зарядка · 03.11 · 1-я за день\nОтжимания 0 · Мостик 0 · Планка 0:00 · Спина 0")
    assert "Первая зарядка — введите результаты" in screen
    assert not owner.sees("✅ Как в прошлый раз")
    await owner.tap("Отжимания 0")
    assert await owner.say("сорок") == "Не понял число „сорок“. Напишите, например, 4,5 или 4.5"
    await owner.say("40")
    await owner.tap("Планка 0:00")
    assert await owner.say("5:75") == "Время пишите как 5:45, 5.45 или в секундах: 345"
    await owner.say("5.30")
    for _ in range(2):
        await owner.press_data(_nth(owner, "+", 1))  # «+» у мостика
    text = await owner.tap("💾 Записать")
    assert text.startswith("🤸 Зарядка 1-я за 03.11: Отжимания 40 · Мостик 10 · Планка 5:30 · Спина 0")
    assert "🤸 Зарядка 1/2" in text


async def test_s43_same_as_last_time(world: World, owner: Persona) -> None:
    """S-43. Раздел 9: после зарядки 50 / 50 / 5:45 / 25 «Как в прошлый раз» одним нажатием записывает те же
    значения; вторая зарядка за день — номер 2; в карточке «🤸 Зарядка 2/2»."""
    await _history(world, date(2026, 11, 3))
    screen = await owner.tap("🤸 Зарядка")
    assert screen == f"🤸 Зарядка · 03.11 · 2-я за день\n{LAST}"
    assert owner.labels()[:5] == ["✅ Как в прошлый раз", "Отжимания +5", "Мостик +5", "Планка +15 сек", "Спина +5"]
    text = await owner.tap("✅ Как в прошлый раз")
    assert text.startswith(f"🤸 Зарядка 2-я за 03.11: {LAST}")
    assert "🤸 Зарядка 2/2" in text


async def test_s44_plus_steps(world: World, owner: Persona) -> None:
    """S-44. Раздел 9: «Планка +15 сек» → «Записать» записывает 50 / 50 / 6:00 / 25; «Отжимания +5» дважды → 60."""
    await _history(world)
    await owner.tap("🤸 Зарядка")
    assert "Планка 6:00" in await owner.tap("Планка +15 сек")
    await owner.tap("Отжимания +5")
    assert "Отжимания 60" in await owner.tap("Отжимания +5")
    text = await owner.tap("💾 Записать")
    assert text.startswith("🤸 Зарядка 1-я за 03.11: Отжимания 60 · Мостик 50 · Планка 6:00 · Спина 25")


async def test_s45_custom_step(world: World, owner: Persona) -> None:
    """S-45. Раздел 9: шаг отжиманий изменён на 10 → кнопка «Отжимания +10»; шаг «0» — подсказка."""
    await _history(world)
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("🤸 Зарядка: набор и цели")
    await owner.tap("📋 Набор и шаги")
    await owner.tap("Отжимания +5")
    assert await owner.say("0") == "Шаг — от 1 до 10 000. Вы ввели 0"
    assert (await owner.say("10")).startswith("📋 Набор зарядки")
    await owner.tap("🤸 Зарядка")
    assert "Отжимания +10" in owner.labels()


async def test_s46_edit_minus_plus_exact(world: World, owner: Persona) -> None:
    """S-46. Раздел 9: «Изменить» показывает «−» и «+» для каждого упражнения; «−» у планки, точное «6:15»."""
    await _history(world)
    await owner.tap("🤸 Зарядка")
    await owner.tap("✏️ Изменить")
    labels = owner.labels()
    assert labels.count("−") == 4 and labels.count("+") == 4
    await owner.press_data(owner.find_button("−"))  # «−» у первого — отжимания 45
    await owner.tap("Планка 5:45")
    await owner.say("6:15")
    await owner.tap("← Готово")
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
    assert (await owner.tap("🤸 Зарядка")).endswith(LAST)


async def test_s48_other_day_uses_earlier_warmup(world: World, owner: Persona) -> None:
    """S-48. Раздел 3.7: в режиме «Другой день» 01.11 «Как в прошлый раз» берёт зарядку до этой даты (31.10),
    а не более позднюю (02.11); номер — следующий в том дне."""
    await _history(world, date(2026, 10, 31), (40, 40, 300, 20))
    await _history(world, date(2026, 11, 2))
    await owner.tap("☰ Ещё")
    await owner.tap("📅 Другой день")
    await owner.say("01.11")
    assert (await owner.tap("🤸 Зарядка")).startswith("🤸 Зарядка · 01.11 · 1-я за день\nОтжимания 40")
    text = await owner.tap("✅ Как в прошлый раз")
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
    """S-50. Набор меняется: добавить «Приседания», убрать «Спина», поднять «Приседания» — экран зарядки по-новому;
    прошлые зарядки не изменились."""
    await _history(world)
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("🤸 Зарядка: набор и цели")
    await owner.tap("📋 Набор и шаги")
    await owner.tap("➕ Добавить упражнение")
    await owner.say("Приседания")
    await owner.tap("Повторы")
    assert owner.replies()[0] == "«Приседания» добавлено в набор, шаг +5."
    rows = [b for b in owner.labels() if b not in ("⬆", "✕")]
    assert rows[:5] == ["Отжимания +5", "Мостик +5", "Планка +15 сек", "Спина +5", "Приседания +5"]
    await owner.press_data(_nth(owner, "✕", 3))  # убрать «Спина»
    await owner.press_data(_nth(owner, "⬆", 3))  # поднять «Приседания» на место выше «Планки»
    await owner.tap("🤸 Зарядка")
    assert owner.last().endswith("Отжимания 50 · Мостик 50 · Приседания 0 · Планка 5:45")
    (session,) = await _sessions(world)
    assert session.number == 1


def _nth(user: Persona, label: str, index: int) -> str:
    """callback_data n-й кнопки с одинаковой подписью («+», «⬆», «✕») под последним сообщением."""
    for m in reversed(user._mine()):
        rows = getattr(m.reply_markup, "inline_keyboard", None)
        if rows:
            buttons = [b for row in rows for b in row if b.text == label]
            return str(buttons[index].callback_data)
    raise AssertionError(label)


async def test_s51_double_save_and_undo(world: World, owner: Persona) -> None:
    """S-51. Двойная доставка «Как в прошлый раз» — одна зарядка; «Отменить» удаляет; «📅 На вчера» переносит."""
    await _history(world)
    await owner.tap("🤸 Зарядка")
    await owner.tap_twice("✅ Как в прошлый раз")
    assert len(await _sessions(world)) == 2
    assert (await owner.tap("Отменить")).startswith("Зарядка 1-я за 03.11 удалена.")
    await owner.tap("🤸 Зарядка")
    await owner.tap("✅ Как в прошлый раз")
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
    assert "Планка 6:00" in await owner.tap("💾 Записать")


async def test_s53_foreign_warmup_button(world: World, owner: Persona) -> None:
    """S-53. Гость нажимает «Отменить» под зарядкой владельца — отказ, зарядка на месте; у гостя свой пустой набор."""
    await _history(world)
    await owner.tap("🤸 Зарядка")
    await owner.tap("✅ Как в прошлый раз")
    owners_undo = owner.find_button("Отменить")
    guest = await invite_guest(world, owner, OTHER_ID, "Аня")
    await finish_guest_onboarding(guest)
    await guest.press_data(owners_undo)
    assert guest.last() == "Эта кнопка не ваша — ничего не изменено. Вот главное меню 👇"
    assert len(await _sessions(world)) == 2
    assert (await guest.tap("🤸 Зарядка")).startswith("Набор зарядки пуст.")
