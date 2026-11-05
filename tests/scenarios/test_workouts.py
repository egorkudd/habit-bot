"""Поведенческие сценарии: тренировки и бег (раздел 3.4.0, 3.5, часть 8)."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from habit_bot.modules.runs.models import RunEntry
from habit_bot.modules.workouts.domain.training import Kind, SetValue
from habit_bot.modules.workouts.models import WorkoutSession, WorkoutSet
from tests.conftest import ADMIN_ID, OTHER_ID
from tests.scenarios.conftest import finish_guest_onboarding, invite_guest
from tests.scenarios.harness import Persona, World

STALE = "Это меню устарело. Вот главное меню 👇"
TODAY = date(2026, 11, 3)


async def _actor(world: World, tg_id: int = ADMIN_ID) -> Any:
    return await world.service("users.sign_in").execute(tg_id, "")


async def _by_name(world: World, name: str) -> Any:
    actor = await _actor(world)
    workouts = world.service("workouts")
    found = [e for e in await workouts.exercises(actor, await workouts.filters(actor, Kind.FREE)) if e.name == name]
    return found[0]


async def _history(world: World, name: str = "Присед со штангой", weight: str = "110", reps: int = 8,
                   sets: int = 4, day: date = date(2026, 11, 1)) -> None:
    """Прошлая тренировка в зале: 110 кг 4×8."""
    actor = await _actor(world)
    workouts = world.service("workouts")
    session = await workouts.start(actor, Kind.GYM, day=day)
    exercise = await _by_name(world, name)
    await workouts.add_sets(actor, session.public_id, exercise.public_id,
                            [SetValue(reps=reps, weight=Decimal(weight))] * sets)
    await workouts.finish(actor, session.public_id, 60)


async def _sessions(world: World) -> list[WorkoutSession]:
    async with world.app.ctx.uow() as uow:
        return list((await uow.session.execute(select(WorkoutSession).where(
            WorkoutSession.deleted_at.is_(None)).order_by(WorkoutSession.id))).scalars().all())


async def _sets(world: World) -> list[WorkoutSet]:
    async with world.app.ctx.uow() as uow:
        return list((await uow.session.execute(select(WorkoutSet).where(
            WorkoutSet.deleted_at.is_(None)).order_by(WorkoutSet.id))).scalars().all())


def _labels(user: Persona) -> list[str]:
    return user.labels()


async def _group(user: Persona, name: str) -> str:
    """Нажать группу «Ноги (14)» — число упражнений зависит от пола и фильтров."""
    label = next(b for b in user.labels() if b.startswith(f"{name} ("))
    return await user.tap(label)


async def test_s78_gym_by_groups_and_tonnage(world: World, owner: Persona) -> None:
    """S-78. Раздел 9: «Тренировка» → «Зал» → «Все по группам» → «Ноги» → «Присед со штангой» → вес 110 →
    «4×8» → «Завершить» → «70 мин»: 4 подхода, тоннаж 110 × 8 × 4 = 3 520 кг; неделя 1/3."""
    assert (await owner.tap("🏋️ Тренировка")).startswith("🏋️ Какая тренировка? За неделю: 0/3.")
    screen = await owner.tap("🏋️ Зал")
    assert screen.startswith("🏋️ Зал · 03.11 · идёт с 15:00\nУпражнений пока нет")
    await owner.tap("➕ Упражнение")
    await owner.tap("📚 Все по группам")
    assert not any(g.startswith("Турник") for g in _labels(owner))  # в зале — без площадки
    await _group(owner, "Ноги")
    text = await owner.tap("Присед со штангой")
    assert "Вес: не задан — напишите, например 60" in text
    assert "Вес: 110 кг" in await owner.say("110")
    assert _labels(owner)[:3] == ["−2,5", "110 кг", "+2,5"]
    saved = await owner.say("4×8")
    assert saved.startswith("✅ Присед со штангой: 110 кг 4×8 · 3 520 кг")
    await owner.tap("🏁 Завершить")
    result = await owner.tap("70 мин")
    assert result.startswith("🏋️ Зал 03.11 — 70 мин\n1. Присед со штангой — 110 кг 4×8 · 3 520 кг\n"
                             "Тоннаж: 3 520 кг\nТренировок за неделю: 1/3")
    assert "🏋️ Зал 70 мин · 3 520 кг" in result  # строка карточки дня
    (session,) = await _sessions(world)
    assert (session.status, session.duration_min, session.tonnage, len(await _sets(world))) == ("done", 70, 3520, 4)


async def test_s79_same_as_last_time_and_steps(world: World, owner: Persona) -> None:
    """S-79. Раздел 9: после 110 кг 4×8 упражнение — в «недавних»; «✅ Как в прошлый раз (110 кг 4×8)» — одно
    нажатие; «+2,5» и «3×8» — 112,5 кг; итог — оба упражнения и тоннаж."""
    await _history(world)
    await owner.tap("🏋️ Тренировка")
    await owner.tap("🏋️ Зал")
    await owner.tap("➕ Упражнение")
    text = await owner.tap("Присед со штангой")
    assert "Прошлый раз 01.11: 110 кг 4×8" in text
    assert (await owner.tap("✅ Как в прошлый раз (110 кг 4×8)")).startswith("✅ Присед со штангой: 110 кг 4×8")
    await owner.tap("➕ Следующее упражнение")
    await owner.tap("Присед со штангой")
    assert "Вес: 112,5 кг" in await owner.tap("+2,5")
    assert (await owner.tap("3×6")).startswith("✅ Присед со штангой: 112,5 кг 3×6 · 2 025 кг")
    await owner.tap("🏁 Завершить")
    result = await owner.tap("60 мин")
    assert "Тоннаж: 5 545 кг" in result


async def test_s80_dumbbells_count_twice(world: World, owner: Persona) -> None:
    """S-80. Раздел 9: «вес каждой гантели» — тоннаж ×2: жим гантелей 20 кг 3×10 = 1 200 кг; по подходам
    «10 8 6» — разные повторы."""
    await owner.tap("🏋️ Тренировка")
    await owner.tap("🏋️ Зал")
    await owner.tap("➕ Упражнение")
    await owner.tap("📚 Все по группам")
    await _group(owner, "Грудь, жимы")
    assert "(вес каждой гантели)" in await owner.tap("Жим гантелей лёжа")
    await owner.say("20")
    assert (await owner.say("3x10")).startswith("✅ Жим гантелей лёжа: 2×20 кг 3×10 · 1 200 кг")
    await owner.tap("➕ Следующее упражнение")
    await owner.tap("Жим гантелей лёжа")
    assert (await owner.say("10 8 6")).startswith("✅ Жим гантелей лёжа: 2×20 кг 10, 8, 6 · 960 кг")


async def test_s81_input_errors_keep_workout(world: World, owner: Persona) -> None:
    """S-81. Ошибки ввода — подсказка, тренировка и упражнение не теряются: подходы без веса, «4×», «сто»,
    вес 600, 13 подходов, длительность 0."""
    await owner.tap("🏋️ Тренировка")
    await owner.tap("🏋️ Зал")
    await owner.tap("➕ Упражнение")
    await owner.tap("📚 Все по группам")
    await _group(owner, "Ноги")
    await owner.tap("Жим ногами")
    assert await owner.say("4×10") == "Сначала вес — напишите число, например 60. Потом подходы: 4×8"
    assert await owner.say("сто") == "Не понял число „сто“. Напишите, например, 4,5 или 4.5"
    assert (await owner.say("600")).startswith("Вес — от 0,5 до 500 кг. Вы ввели 600")
    await owner.say("120")
    hint = "Не понял подходы „{}“. Пишите 4×8 — четыре подхода по 8, или по подходам: 8 8 7 6"
    assert await owner.say("4×") == hint.format("4×")
    assert await owner.say("13×8") == hint.format("13×8")
    assert await owner.say("4×300") == hint.format("4×300")
    await owner.say("4×10")
    await owner.tap("🏁 Завершить")
    assert (await owner.say("0")).startswith("Длительность — от 1 до 600 мин")
    assert (await owner.say("45")).startswith("🏋️ Зал 03.11 — 45 мин")


async def test_s82_pause_20_minutes_and_auto_finish(world: World, owner: Persona) -> None:
    """S-82. Раздел 9: пауза 20 минут — тренировка не сброшена, кнопки работают; потом 3 часа без действий —
    тренировка завершена сама с записанными подходами, бот ничего не пишет, старые кнопки устарели."""
    await _history(world)
    await owner.tap("🏋️ Тренировка")
    await owner.tap("🏋️ Зал")
    await owner.tap("➕ Упражнение")
    await owner.tap("Присед со штангой")
    await world.wait(minutes=20)
    assert (await owner.tap("✅ Как в прошлый раз (110 кг 4×8)")).startswith("✅ Присед со штангой")
    old_add = owner.find_button("➕ Следующее упражнение")
    sent = len(owner.texts())
    await world.wait(hours=3, minutes=1)
    assert await world.service("workouts").auto_finish(world.clock.now()) == 1
    assert len(owner.texts()) == sent
    await owner.press_data(old_add)
    assert owner.last() == STALE
    session = (await _sessions(world))[-1]
    assert (session.status, session.auto_finished, session.duration_min) == ("done", True, 20)
    # 01.11 — воскресенье прошлой недели, поэтому за эту неделю — одна (завершённая сама)
    assert (await owner.tap("🏋️ Тренировка")).startswith("🏋️ Какая тренировка? За неделю: 1/3.")


async def test_s83_outdoor_filters(world: World, owner: Persona) -> None:
    """S-83. Раздел 3.4.1: площадка, «Резинка: нет», «❌ Брусья» — нет групп «С резинкой» и «Брусья», нет
    упражнений «лёжа на земле» (планка) и с отягощением; прошлый ответ про резинку запоминается."""
    await owner.tap("🏋️ Тренировка")
    assert (await owner.tap("🌳 Площадка")).startswith("🌳 Площадка. Резинка с собой?")
    await owner.tap("Резинка: нет")
    await owner.tap("✅ Брусья")
    assert "Нет: Брусья" in owner.last()
    await owner.tap("▶ Начать")
    await owner.tap("➕ Упражнение")
    await owner.tap("📚 Все по группам")
    groups = _labels(owner)
    assert not any(g.startswith(("С резинкой", "Брусья", "Кор")) for g in groups)
    await owner.tap(next(g for g in groups if g.startswith("Турник")))
    labels = _labels(owner)
    assert "Подтягивания широким хватом" in labels and "Подтягивания с отягощением" not in labels
    await owner.tap("Подтягивания широким хватом")
    assert (await owner.say("8 7 6")).startswith("✅ Подтягивания широким хватом: 8, 7, 6")
    await owner.tap("🏁 Завершить")
    await owner.tap("60 мин")
    await owner.tap("🏋️ Тренировка")
    await owner.tap("🌳 Площадка")
    assert "✅ Резинка: нет" in _labels(owner)


async def test_s84_free_with_new_exercise(world: World, owner: Persona) -> None:
    """S-84. «Свободная» → «✍️ Новое» → «Скакалка» → «Время» → «3×1:00»; длительность «по часам»."""
    await owner.tap("🏋️ Тренировка")
    await owner.tap("🧩 Свободная")
    await owner.tap("➕ Упражнение")
    await owner.tap("✍️ Новое")
    await owner.say("Скакалка")
    await owner.tap("Время")
    assert (await owner.say("3×1:00")).startswith("✅ Скакалка: 3×1:00")
    world.clock.advance(minutes=25)
    await owner.tap("🏁 Завершить")
    assert (await owner.tap("⏱ 25 мин (по часам)")).startswith("🧩 Свободная 03.11 — 25 мин\n1. Скакалка")


async def test_s85_restart_double_tap_undo_empty(world: World, owner: Persona) -> None:
    """S-85. Перезапуск посреди тренировки — «🏋️ Тренировка» продолжает её; двойная доставка «Как в прошлый
    раз» — одна запись; «↩ Убрать последнее»; «Завершить» без подходов — тренировка не сохранена."""
    await _history(world)
    await owner.tap("🏋️ Тренировка")
    await owner.tap("🏋️ Зал")
    await world.restart()
    assert (await owner.tap("🏋️ Тренировка")).startswith("Тренировка идёт:")
    await owner.tap("➕ Упражнение")
    await owner.tap("Присед со штангой")
    await owner.tap_twice("✅ Как в прошлый раз (110 кг 4×8)")
    assert len(await _sets(world)) == 8  # 4 прошлых + 4 сегодня
    assert (await owner.tap("↩ Убрать последнее")).startswith("Последнее упражнение убрано.")
    assert len(await _sets(world)) == 4
    assert await owner.tap("🏁 Завершить") == "Тренировка без подходов не сохранена."
    assert len(await _sessions(world)) == 1


async def test_s86_foreign_buttons_and_undo(world: World, owner: Persona) -> None:
    """S-86. Гость нажимает кнопку тренировки владельца — отказ, тренировка на месте; «Отменить» под итогом
    удаляет тренировку."""
    await owner.tap("🏋️ Тренировка")
    await owner.tap("🏋️ Зал")
    owners_add = owner.find_button("➕ Упражнение")
    guest = await invite_guest(world, owner, OTHER_ID, "Аня")
    await finish_guest_onboarding(guest)
    await guest.press_data(owners_add)
    assert guest.last() == "Эта кнопка не ваша — ничего не изменено. Вот главное меню 👇"
    assert (await guest.tap("🏋️ Тренировка")).startswith("🏋️ Какая тренировка?")
    assert (await owner.tap("🏋️ Тренировка")).startswith("Тренировка идёт:")
    await owner.tap("➕ Упражнение")
    await owner.tap("📚 Все по группам")
    await _group(owner, "Кор")
    await owner.tap("Планка")
    assert (await owner.say("3×45")).startswith("✅ Планка: 3×0:45")
    await owner.tap("🏁 Завершить")
    await owner.tap("60 мин")
    assert await owner.tap("Отменить") == "Тренировка 03.11 удалена."
    assert await _sessions(world) == []


async def test_s87_run_card_comparison_records(world: World, owner: Persona) -> None:
    """S-87. Раздел 9: бег 5,2 км за «28.40» (= 28:40) → темп 5:31, 10,88 км/ч; второй забег 5 км за 27:00 —
    «▲ быстрее прошлого» и рекорд темпа; «Как в прошлый раз (5,0 км)»; бег засчитан в неделю."""
    await owner.tap("🏋️ Тренировка")
    await owner.tap("🏃 Бег")
    assert (await owner.say("5,2")).startswith("🏃 5,2 км. Время:")
    card = await owner.say("28.40")
    assert card.startswith("🏃 5,2 км · 28:40 · темп 5:31 · 10,88 км/ч · первый забег в группе «5–10 км»\n"
                           "Тренировок за неделю: 1/3")
    await owner.tap("🏋️ Тренировка")
    await owner.tap("🏃 Бег")
    assert "Как в прошлый раз (5,2 км)" in _labels(owner)
    await owner.tap("5 км")
    card = await owner.say("27")
    assert card.startswith("🏃 5,0 км · 27:00 · темп 5:24 · 11,11 км/ч · ▲ на 0:07 быстрее прошлого\n"
                           "🏆 Лучший темп 5–10 км: 5:24\nТренировок за неделю: 2/3")
    await owner.tap("🏋️ Тренировка")
    await owner.tap("🏃 Бег")
    await owner.say("12")
    assert "🏆 Самая длинная дистанция: 12,0 км" in await owner.say("1:05:10")


async def test_s88_run_errors_and_unreal_pace(world: World, owner: Persona) -> None:
    """S-88. Раздел 3.5: ошибки ввода — подсказка; темп 2:00 — «всё верно?»; «Нет» — ввод заново, «Да» —
    запись; «отмена» — ничего не записано."""
    await owner.tap("🏋️ Тренировка")
    await owner.tap("🏃 Бег")
    assert await owner.say("пять") == "Не понял число „пять“. Напишите, например, 4,5 или 4.5"
    await owner.say("5")
    assert (await owner.say("28:75")).startswith("Время пишите как")
    assert await owner.say("10") == "Темп 2:00 мин/км (5,0 км за 10:00) — всё верно?"
    assert (await owner.tap("Нет, ввести заново")).startswith("🏃 Дистанция ещё раз?")
    await owner.say("3")
    assert await owner.say("5") == "Темп 1:40 мин/км (3,0 км за 5:00) — всё верно?"
    assert (await owner.tap("Да, записать")).startswith("🏃 3,0 км · 5:00 · темп 1:40")
    await owner.tap("🏋️ Тренировка")
    await owner.tap("🏃 Бег")
    await owner.say("отмена")
    async with world.app.ctx.uow() as uow:
        assert len((await uow.session.execute(select(RunEntry))).scalars().all()) == 1


async def test_s89_run_other_day_move_undo(world: World, owner: Persona) -> None:
    """S-89. «Другой день» → вчера: забег записан вчерашним днём; «📅 На вчера» под новым забегом переносит его;
    «Отменить» удаляет."""
    await owner.tap("☰ Ещё")
    await owner.tap("📅 Другой день")
    await owner.tap("Вчера (02.11)")
    await owner.tap("🏋️ Тренировка")
    await owner.tap("🏃 Бег")
    await owner.tap("5 км")
    assert "<pre>02.11, пн" in await owner.say("30")
    await owner.tap("📅 02.11 ✕ Вернуться к сегодня")
    await owner.tap("🏋️ Тренировка")
    await owner.tap("🏃 Бег")
    await owner.tap("3 км")
    await owner.say("18")
    await owner.tap("📅 На вчера")
    async with world.app.ctx.uow() as uow:
        days = sorted(r.day for r in (await uow.session.execute(select(RunEntry))).scalars().all())
    assert days == [TODAY - timedelta(days=1)] * 2
    await owner.tap("🏋️ Тренировка")
    await owner.tap("🏃 Бег")
    await owner.tap("3 км")
    await owner.say("18")
    assert (await owner.tap("Отменить")).startswith("Забег 3,0 км за 03.11 удалён.")


async def test_s90_weekly_goal_in_habits_and_settings(world: World, owner: Persona) -> None:
    """S-90. Цель «тренировок в неделю»: в «✅ Привычки» — «🏋️ Тренировки за неделю 1/3»; в настройках — 4;
    резинки и «Показывать все упражнения» сохраняются."""
    await _history(world, day=TODAY)
    await owner.tap("✅ Привычки")
    assert "🏋️ Тренировки за неделю 1/3" in _labels(owner)
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    assert (await owner.tap("🏋️ Тренировки")).startswith("🏋️ Тренировки\nТренировок в неделю: 3")
    await owner.tap("4")
    await owner.tap("лёгкая")
    text = await owner.tap("Все упражнения: нет")
    assert "Тренировок в неделю: 4\nРезинки: лёгкая\nПоказывать все упражнения: да" in text
    await owner.tap("✅ лёгкая")
    await owner.tap("✅ Привычки")
    assert "🏋️ Тренировки за неделю 1/4" in _labels(owner)
