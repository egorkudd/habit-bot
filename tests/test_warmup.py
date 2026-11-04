"""Сценарии модуля warmup без Telegram: изоляция, перенос с номером, набор, цели, стартовый набор."""

from datetime import date
from typing import Any

import pytest

from habit_bot.kernel.errors import AppError
from habit_bot.modules.warmup.domain.warmup import Measure
from tests.conftest import OTHER_ID, register_active

DAY = date(2026, 11, 3)


async def test_isolation_and_move(app: Any) -> None:
    """Раздел 9 «Изоляция»: B не видит зарядок и набора A; перенос ставит следующий номер в новом дне."""
    a = await register_active(app)
    invite = await app.ctx.services["users.invites"].create(a, max_uses=1, days=1)
    b = await register_active(app, OTHER_ID, invite_code=invite.code, name="Аня")
    warmup = app.ctx.services["warmup"]
    exercises = await warmup.use_default_set(a)
    values = {e.public_id: 10 for e in exercises}
    first = await warmup.record(a, values, day=date(2026, 11, 2))
    second = await warmup.record(a, values, day=DAY)
    assert await warmup.templates(b) == []
    assert await warmup.session(b, first.public_id) is None
    assert await warmup.delete_session(b, first.public_id) is None
    with pytest.raises(AppError):
        await warmup.record(b, values, day=DAY)
    with pytest.raises(AppError):
        await warmup.set_step(b, exercises[0].public_id, 10)
    await warmup.move(a, second.public_id, date(2026, 11, 2))
    moved = await warmup.session(a, second.public_id)
    assert (moved.day, moved.number) == (date(2026, 11, 2), 2)
    assert await warmup.day_of(a, "не-uuid") is None


async def test_set_editing_and_goals(app: Any) -> None:
    """Дубль упражнения — подсказка; убранное возвращается тем же названием; цель в прошлом — ошибка даты."""
    actor = await register_active(app)
    warmup = app.ctx.services["warmup"]
    await warmup.use_default_set(actor)
    with pytest.raises(AppError) as err:
        await warmup.add_exercise(actor, name="планка", measure=Measure.SECONDS)
    assert err.value.code == "INPUT-DUPLICATE"
    with pytest.raises(AppError):
        await warmup.add_exercise(actor, name=" ", measure=Measure.REPS)
    plank = next(e for e in await warmup.templates(actor) if e.short == "Планка")
    await warmup.remove_exercise(actor, plank.public_id)
    assert [e.short for e in await warmup.templates(actor)] == ["Отжимания", "Мостик", "Спина"]
    back = await warmup.add_exercise(actor, name="Планка", measure=Measure.SECONDS)
    assert back.public_id == plank.public_id
    await warmup.move_up(actor, (await warmup.templates(actor))[0].public_id)  # первое выше некуда
    with pytest.raises(AppError):
        await warmup.move_up(actor, "0" * 32)
    with pytest.raises(AppError):
        await warmup.set_goal(actor, plank.public_id, target=660, target_date=date(2026, 11, 1))
    goal = await warmup.set_goal(actor, plank.public_id, target=660, target_date=date(2026, 12, 3))
    await warmup.set_goal(actor, plank.public_id, target=600, target_date=date(2026, 12, 3))
    assert [g.target for g in await warmup.goals(actor)] == [600]
    with pytest.raises(AppError):
        await warmup.remove_goal(actor, goal.public_id + "x")
    await warmup.remove_goal(actor, (await warmup.goals(actor))[0].public_id)
    assert await warmup.goals(actor) == []
    await warmup.set_daily_goal(actor, 3)
    await warmup.set_daily_goal(actor, 1)
    assert await warmup.daily_goal(actor) == 1


async def test_starter_kit(app: Any) -> None:
    """«Зарядка по умолчанию» из анкеты — набор при первом открытии; без неё — пустой набор."""
    actor = await register_active(app)
    warmup = app.ctx.services["warmup"]
    assert await warmup.ensure_set(actor) is False
    async with app.ctx.uow() as uow:
        from sqlalchemy import select

        from habit_bot.modules.users.models import Profile

        (await uow.session.execute(select(Profile))).scalar_one().starter_kit = ["warmup"]
    assert await warmup.ensure_set(actor) is True
    assert len(await warmup.templates(actor)) == 4
    assert await warmup.ensure_set(actor) is True
