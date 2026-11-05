"""Сценарии модуля habits без Telegram: тот же результат, что и через кнопки (раздел 9 «Архитектура»)."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from habit_bot.kernel.errors import AppError
from habit_bot.modules.habits.domain.habits import Measure
from habit_bot.modules.habits.usecases import HABITS_LIMIT
from tests.conftest import OTHER_ID, register_active

DAY = date(2026, 11, 3)


async def _two(app: Any) -> tuple[Any, Any, Any]:
    a = await register_active(app)
    invite = await app.ctx.services["users.invites"].create(a, max_uses=1, days=1)
    b = await register_active(app, OTHER_ID, invite_code=invite.code, name="Аня")
    return app.ctx.services["habits"], a, b


async def test_isolation_marks_and_move(app: Any) -> None:
    """Раздел 9 «Изоляция»: B не видит и не меняет привычек и записей A; повтор запроса — одна запись; перенос."""
    habits, a, b = await _two(app)
    eyes = await habits.from_template(a, "eyes")
    first = await habits.mark(a, eyes.public_id, day=DAY, request_id="tg:1")
    again = await habits.mark(a, eyes.public_id, day=DAY, request_id="tg:1")
    assert first.entry_id == again.entry_id and first.fact == 1 and not first.done
    assert await habits.habits(b) == [] and await habits.habit(b, eyes.public_id) is None
    with pytest.raises(AppError):
        await habits.mark(b, eyes.public_id, day=DAY)
    assert await habits.undo(b, first.entry_id) is None
    assert await habits.entry_result(b, first.entry_id) is None
    assert await habits.clear_day(b, eyes.public_id, DAY) == 0
    assert await habits.delete(b, eyes.public_id) is None
    assert await habits.streak_of(b, eyes.public_id, DAY) == 0
    await habits.move(a, first.entry_id, DAY - timedelta(days=1))
    assert await habits.day_of(a, first.entry_id) == DAY - timedelta(days=1)
    assert await habits.day_of(a, "не-uuid") is None
    assert await habits.habit(a, "не-uuid") is None


async def test_goal_streak_undo_and_many(app: Any) -> None:
    """3/3 — выполнено, «just_done» один раз; «Отменить» возвращает 2/3; «Отметить несколько» — по шагу каждой."""
    habits, a, _ = await _two(app)
    eyes = await habits.from_template(a, "eyes")
    vitamins = await habits.from_template(a, "vitamins")
    results = [await habits.mark(a, eyes.public_id, day=DAY) for _ in range(4)]
    assert [(r.fact, r.just_done) for r in results] == [(1, False), (2, False), (3, True), (4, False)]
    assert results[2].streak == 1
    left = await habits.undo(a, results[3].entry_id)
    assert left is not None and left.fact == 3 and left.done
    many = await habits.mark_many(a, [vitamins.public_id, vitamins.public_id], day=DAY, request_id="tg:9")
    assert [(r.habit.short, r.fact, r.done) for r in many] == [("Витамины", 1, True)]
    assert await habits.mark_many(a, [vitamins.public_id], day=DAY) and (await habits.day(a, DAY))[1].fact == 2
    assert await habits.clear_day(a, vitamins.public_id, DAY) == 2
    water = await habits.from_template(a, "water")
    custom = await habits.mark(a, water.public_id, day=DAY, value=Decimal("1.5"))
    assert custom.fact == Decimal("1.5")
    steps = await habits.from_template(a, "steps")
    default = await habits.mark(a, steps.public_id, day=DAY)  # шага нет — по умолчанию 1
    assert default.value == 1


async def test_create_update_archive_delete(app: Any) -> None:
    """Своя привычка: проверки названия, правка полей, порядок, архив сохраняет историю, удаление — вместе с ней."""
    habits, a, _ = await _two(app)
    medit = await habits.create(a, name="  Медитация  ", emoji="🧘", measure=Measure.DURATION, goal=Decimal(15),
                                step=Decimal(10), weekdays=[0, 2, 0])
    assert (medit.name, medit.label, medit.weekdays, medit.once) == ("Медитация", "🧘 Медитация", (0, 2), False)
    for bad in ("", "x" * 65):
        with pytest.raises(AppError) as err:
            await habits.create(a, name=bad, emoji="", measure=Measure.CHECK)
        assert err.value.code == "INPUT-TEXT"
    with pytest.raises(AppError) as err:
        await habits.create(a, name="медитация", emoji="", measure=Measure.CHECK)
    assert err.value.code == "INPUT-HABIT-DUPLICATE"
    reading = await habits.from_template(a, "reading")
    updated = await habits.update(a, reading.public_id, name="Книги", emoji="📚", goal=None, step=Decimal(5),
                                  quick=[Decimal(10), Decimal(30)], weekdays=list(range(7)))
    assert (updated.label, updated.goal, updated.step, updated.quick_values, updated.weekdays) == (
        "📚 Книги", None, 5, (10, 30), None)
    for bad_name in ("", "Медитация"):
        with pytest.raises(AppError):
            await habits.update(a, reading.public_id, name=bad_name)
    with pytest.raises(AppError):
        await habits.update(a, "не-uuid", goal=None)
    await habits.move_up(a, reading.public_id)
    await habits.move_up(a, reading.public_id)  # уже первая — ничего
    assert [h.short for h in await habits.habits(a)] == ["Книги", "Медитация"]
    assert (await habits.by_label(a, " 📚  Книги ")).public_id == reading.public_id
    await habits.mark(a, medit.public_id, day=DAY)
    archived = await habits.set_archived(a, medit.public_id, True)
    assert archived.archived and [h.short for h in await habits.habits(a)] == ["Книги"]
    with pytest.raises(AppError):
        await habits.mark(a, medit.public_id, day=DAY)
    restored = await habits.set_archived(a, medit.public_id, False)
    assert restored.position > (await habits.habit(a, reading.public_id)).position
    assert (await habits.day(a, DAY))[1].fact == 10  # история осталась
    with pytest.raises(AppError):
        await habits.set_archived(a, "не-uuid", True)
    assert (await habits.delete(a, medit.public_id)).name == "Медитация"
    assert await habits.habit(a, medit.public_id) is None


async def test_limit_and_starter(app: Any, monkeypatch: Any) -> None:
    """Не больше HABITS_LIMIT привычек; «Примеры привычек» из анкеты добавляются один раз."""
    habits, a, _ = await _two(app)
    async with app.ctx.uow() as uow:
        from sqlalchemy import select

        from habit_bot.modules.users.models import Profile
        profile = (await uow.session.execute(select(Profile).where(Profile.user_id == a.user_id))).scalar_one()
        profile.starter_kit = ["habits"]
    created = await habits.apply_starter(a)
    assert [h.short for h in created] == ["Глаза", "Вода", "Витамины"]
    assert await habits.apply_starter(a) == []
    monkeypatch.setattr("habit_bot.modules.habits.usecases.HABITS_LIMIT", 3)
    with pytest.raises(AppError) as err:
        await habits.create(a, name="Ещё одна", emoji="", measure=Measure.CHECK)
    assert err.value.code == "INPUT-RANGE" and HABITS_LIMIT == 30
