"""Раздел 3.10: каждая из 30 фраз после «✅ Выполнить всё» выполняется без отказов, а «↩️ Отменить всё»
возвращает всё как было — для каждого вида действия есть своя отмена."""

from datetime import date
from typing import Any

import pytest
from sqlalchemy import select

from habit_bot.kernel.errors import AppError
from habit_bot.modules.days.models import DayStatus
from habit_bot.modules.food.models import FoodEntry, FoodItem
from habit_bot.modules.habits.models import Habit, HabitEntry
from habit_bot.modules.runs.models import RunEntry
from habit_bot.modules.users.models import Goal, Profile
from habit_bot.modules.warmup.models import WarmupGoal, WarmupItem, WarmupSession, WarmupTemplate
from habit_bot.modules.workouts.models import WorkoutSession
from tests.ai.golden import GOLDEN
from tests.ai.test_golden import golden_app  # noqa: F401 — общий стенд


async def _snapshot(app: Any) -> dict[str, Any]:
    """Всё, что могут поменять действия: записи еды (с днём и количеством), рецепты, зарядки, привычки, бег,
    тренировки, цели, вес."""
    async with app.ctx.uow() as uow:
        s = uow.session

        async def rows(query: Any) -> list[Any]:
            return sorted(tuple(map(str, r)) for r in (await s.execute(query)).all())

        return {
            "food": await rows(select(FoodEntry.name, FoodEntry.day, FoodEntry.quantity)
                               .where(FoodEntry.deleted_at.is_(None))),
            "items": await rows(select(FoodItem.name, FoodItem.kcal, FoodItem.price)
                                .where(FoodItem.user_id.is_not(None), FoodItem.active.is_(True))),
            "warmup": await rows(select(WarmupItem.name, WarmupItem.value).join(WarmupSession)
                                 .where(WarmupSession.deleted_at.is_(None))),
            "templates": await rows(select(WarmupTemplate.short, WarmupTemplate.step)
                                    .where(WarmupTemplate.active.is_(True))),
            "warmup_goals": await rows(select(WarmupGoal.target).where(WarmupGoal.active.is_(True))),
            "habits": await rows(select(Habit.name).where(Habit.status == "active")),
            "marks": await rows(select(HabitEntry.value).where(HabitEntry.deleted_at.is_(None))),
            "runs": await rows(select(RunEntry.day).where(RunEntry.deleted_at.is_(None))),
            "workouts": await rows(select(WorkoutSession.day).where(WorkoutSession.deleted_at.is_(None))),
            "goals": await rows(select(Goal.start_date, Goal.kcal)),
            "weight": await rows(select(Profile.weight_kg)),
            "days_off": await rows(select(DayStatus.day).where(DayStatus.deleted_at.is_(None))),
        }


async def test_every_phrase_executes_and_undoes(golden_app: Any) -> None:  # noqa: F811
    app, actor = golden_app
    commands = app.ctx.services["ai_commands"]
    problems = []
    for case in GOLDEN:
        before = await _snapshot(app)
        try:
            view = await commands.parse(actor, case["phrase"])
        except AppError:
            continue
        if not view.ops:
            continue
        executed = await commands.execute(actor, view.public_id)
        assert executed is not None
        if executed.done.failed:
            problems.append((case["phrase"], "отказ", executed.done.failed))
        if await _snapshot(app) == before:
            problems.append((case["phrase"], "ничего не изменилось", None))
        undone = await commands.undo_all(actor, view.public_id)
        if undone != len(executed.done.undo):
            problems.append((case["phrase"], "отменено не всё", undone))
        after = await _snapshot(app)
        if after != before:
            diff = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
            problems.append((case["phrase"], "после отмены не как было", diff))
        assert await commands.undo_all(actor, view.public_id) is None  # второй раз — уже отменено
    assert problems == []


async def test_object_gone_between_card_and_run(golden_app: Any) -> None:  # noqa: F811
    """Карточку показали, потом запись удалили кнопками: действие не выполняется, остальные — да; отмена
    удалённого молча пропускается."""
    app, actor = golden_app
    commands = app.ctx.services["ai_commands"]
    food = app.ctx.services["food"]
    view = await commands.parse(actor, "коктейль сегодня был двойной")
    entry_id = view.ops[0]["entry_id"]
    await food.delete_entry(actor, entry_id)
    executed = await commands.execute(actor, view.public_id)
    assert executed is not None and executed.done.lines == []
    assert executed.done.failed[0].startswith("✏️ 03.11 Еда: Коктейль (09:12) — 1 → 2 — ")

    view = await commands.parse(actor, "удали творог ужин")
    executed = await commands.execute(actor, view.public_id)
    assert executed is not None and executed.done.failed == []
    assert await commands.execute(actor, view.public_id) is None  # повторное нажатие
    await food.restore_entry(actor, view.ops[0]["entry_id"])
    assert await commands.undo_all(actor, view.public_id) == 1

    view = await commands.parse(actor, "перенеси творог ужин на вчера")
    await food.delete_entry(actor, view.ops[0]["entry_id"])
    executed = await commands.execute(actor, view.public_id)
    assert executed is not None and len(executed.done.failed) == 1

    view = await commands.parse(actor, "планку сегодня во 2-й зарядке делал 6:15, а не 6:00")
    sessions = await app.ctx.services["warmup"].sessions(actor, date(2026, 11, 3))
    await app.ctx.services["warmup"].delete_session(actor, sessions[1].public_id)
    executed = await commands.execute(actor, view.public_id)
    assert executed is not None and len(executed.done.failed) == 1


async def test_foreign_and_bad_ids(golden_app: Any) -> None:  # noqa: F811
    """Неверный или чужой номер команды — None, ничего не меняется."""
    app, actor = golden_app
    commands = app.ctx.services["ai_commands"]
    assert await commands.command(actor, "не-uuid") is None
    assert await commands.execute(actor, "0" * 32) is None
    assert await commands.drop(actor, "0" * 32, [1]) is None
    assert await commands.undo_all(actor, "0" * 32) is None
    view = await commands.parse(actor, "выпил витамины")
    dropped = await commands.drop(actor, view.public_id, [1])
    assert dropped is not None and dropped.status == "cancelled"
    assert await commands.execute(actor, view.public_id) is None
    await commands.cancel(actor, view.public_id)


async def test_without_client_and_dropping_cancelled(golden_app: Any) -> None:  # noqa: F811
    """Клиент модели убран (ключ отозван) — LLM-OFF; убрать пункт у отменённой карточки нельзя."""
    app, actor = golden_app
    commands = app.ctx.services["ai_commands"]
    view = await commands.parse(actor, "выпил витамины")
    await commands.cancel(actor, view.public_id)
    assert await commands.drop(actor, view.public_id, [1]) is None
    client, commands.client = commands.client, None
    try:
        with pytest.raises(AppError) as err:
            await commands.parse(actor, "выпил витамины")
    finally:
        commands.client = client
    assert err.value.code == "LLM-OFF"
