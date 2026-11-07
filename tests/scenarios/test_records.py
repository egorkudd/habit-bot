"""Поведенческие сценарии: «📋 Записи» — все записи дня и их удаление, в том числе за прошлые дни (правки 1.0.2).

Нужно, потому что «🏠 Домой» и ночная чистка убирают из чата карточки с «Отменить»."""

from datetime import date
from decimal import Decimal
from typing import Any

from habit_bot.modules.food.domain.nutrition import Nutrients
from habit_bot.modules.food.domain.other_line import OtherLine
from habit_bot.modules.workouts.domain.training import Kind, SetValue
from tests.conftest import ADMIN_ID, OTHER_ID
from tests.scenarios.conftest import finish_guest_onboarding, invite_guest
from tests.scenarios.harness import Persona, World

TODAY, YESTERDAY = date(2026, 11, 3), date(2026, 11, 2)
FOREIGN = "Эта кнопка не ваша — ничего не изменено. Вот главное меню 👇"


async def _actor(world: World) -> Any:
    return await world.service("users.sign_in").execute(ADMIN_ID, "")


async def _fill(world: World) -> None:
    """Сегодня: еда, зарядка, тренировка, бег, отметка привычки; вчера — отметка привычки и еда."""
    actor = await _actor(world)
    await world.service("food").log_other(actor, OtherLine("Каша", Nutrients.of(400, 15, 10, 60), None), day=TODAY)
    await world.service("food").log_other(actor, OtherLine("Суп", Nutrients.of(250, 10, 8, 30), None), day=YESTERDAY)
    warmup = world.service("warmup")
    exercises = await warmup.use_default_set(actor)
    await warmup.record(actor, {exercises[0].public_id: 50}, day=TODAY)
    workouts = world.service("workouts")
    squat = next(e for e in await workouts.exercises(actor, await workouts.filters(actor, Kind.GYM))
                 if e.name == "Присед со штангой")
    session = await workouts.start(actor, Kind.GYM, day=TODAY)
    await workouts.add_sets(actor, session.public_id, squat.public_id, [SetValue(reps=8, weight=Decimal(100))] * 3)
    await workouts.finish(actor, session.public_id, 60)
    await world.service("runs").record(actor, distance_km=Decimal("5.2"), seconds=1720, day=TODAY)
    eyes = await world.service("habits").from_template(actor, "eyes")
    await world.service("habits").mark(actor, eyes.public_id, day=TODAY)
    await world.service("habits").mark(actor, eyes.public_id, day=YESTERDAY)


async def _open(owner: Persona) -> str:
    await owner.tap("☰ Ещё")
    return await owner.tap("📋 Записи")


async def test_s139_records_delete_any_entry_today(world: World, owner: Persona) -> None:
    """S-139. «☰ Ещё» → «📋 Записи»: еда, зарядка, тренировка, бег и отметки привычек за сегодня; нажал тренировку —
    подробности, «🗑 Удалить» — её нет ни в списке, ни в итогах недели; «◀ Назад» возвращает список; повторное
    удаление старой кнопкой — «Этой записи уже нет», ничего не ломается; «▶» на сегодня нет."""
    await _fill(world)
    assert (await _open(owner)).startswith("📋 Записи · 03.11 (вт)\nНажмите запись")
    labels = owner.labels()
    assert labels[0] == "🍽 Каша · 400 ккал" and labels[-1] == "◀ 02.11"
    assert "🤸 Зарядка №1" in labels and "🏋️ Зал · 60 мин" in labels
    assert any(b.startswith("🏃 5,2 км · 28:40 · ") for b in labels)
    assert any(b.startswith("👁 Глаза +1") for b in labels)
    detail = await owner.tap("🏋️ Зал · 60 мин")
    assert detail.startswith("🏋️ Зал · 60 мин · 2 400 кг\nПрисед со штангой")
    stale = owner.find_button("🗑 Удалить")
    await owner.tap("◀ Назад")
    await owner.tap("🏋️ Зал · 60 мин")
    assert (await owner.tap("🗑 Удалить")).startswith("📋 Записи · 03.11")
    assert "🏋️ Зал · 60 мин" not in owner.labels()
    assert owner.session.answers()[-1].text == "🗑 Удалено"
    assert await world.service("workouts").day_sessions(await _actor(world), TODAY) == []
    await owner.press_data(stale, message_id=owner.message_id_of(owner._mine()[-1]) or 500)
    assert owner.session.answers()[-1].text == "Этой записи уже нет"
    assert "🏋️ Зал · 60 мин" not in owner.labels()


async def test_s140_records_past_day_after_home_and_restart(world: World, owner: Persona) -> None:
    """S-140. После «🏠 Домой» (карточек с «Отменить» в чате нет) и перезапуска бота вчерашнюю отметку привычки
    и еду можно удалить: «📋 Записи» → «◀ 02.11» → отметка → «🗑 Удалить»; выполнение привычки за вчера — 0.
    В режиме «📅 Другой день» «📋 Записи» сразу открываются на выбранном дне; пустой день — «Записей нет»."""
    await _fill(world)
    await owner.tap("🏠 Домой")
    await world.restart()
    await _open(owner)
    assert (await owner.tap("◀ 02.11")).startswith("📋 Записи · 02.11 (пн)")
    assert owner.labels()[-1] == "04.11 ▶" or owner.labels()[-2:] == ["◀ 01.11", "03.11 ▶"]
    mark = next(b for b in owner.labels() if b.startswith("👁 Глаза"))
    await owner.tap(mark)
    await owner.tap("🗑 Удалить")
    eyes = next(h for h in await world.service("habits").day(await _actor(world), YESTERDAY))
    assert eyes.fact == 0
    assert (await owner.tap("◀ 01.11")).startswith("📋 Записи · 01.11 (вс)\nЗаписей нет.")
    await owner.tap("☰ Ещё")
    await owner.tap("📅 Другой день")
    await owner.tap("Вчера (02.11)")
    assert (await _open(owner)).startswith("📋 Записи · 02.11 (пн)")
    assert owner.labels()[0] == "🍽 Суп · 250 ккал"


async def test_s141_records_foreign_button(world: World, owner: Persona) -> None:
    """S-141. Гость нажимает кнопку «🗑 Удалить» из списка владельца — отказ, запись владельца на месте."""
    await _fill(world)
    await _open(owner)
    await owner.tap("🍽 Каша · 400 ккал")
    delete = owner.find_button("🗑 Удалить")
    guest = await invite_guest(world, owner, OTHER_ID, "Аня")
    await finish_guest_onboarding(guest)
    await guest.press_data(delete)
    assert guest.last() == FOREIGN
    assert [e.name for e in await world.service("food").entries(await _actor(world), TODAY)] == ["Каша"]


async def test_s146_records_broken_and_future_buttons(world: World, owner: Persona) -> None:
    """S-146. Кнопка «📋 Записи» с испорченной или будущей датой — «меню устарело», ничего не удаляется."""
    from habit_bot.modules.days.telegram.handlers import RecCb

    await _fill(world)
    actor = await _actor(world)
    for d in ("zzzzzz", "261231"):
        await owner.press_data(RecCb(o=actor.user_id, t=0, a="list", d=d).pack())
        assert owner.last() == "Это меню устарело. Вот главное меню 👇"
    assert len(await world.service("days").entries(actor, TODAY)) == 5  # еда, зарядка, тренировка, бег, отметка
