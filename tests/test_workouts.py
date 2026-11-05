"""Сценарии модулей workouts и runs без Telegram: тот же результат, что и через кнопки; изоляция; автозавершение."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from habit_bot.kernel.errors import AppError
from habit_bot.modules.workouts.domain.training import Band, Kind, Measure, SetValue
from habit_bot.modules.workouts.usecases import AUTO_FINISH_AFTER
from tests.conftest import OTHER_ID, register_active

DAY = date(2026, 11, 3)


async def _two(app: Any) -> tuple[Any, Any, Any, Any]:
    a = await register_active(app)
    invite = await app.ctx.services["users.invites"].create(a, max_uses=1, days=1)
    b = await register_active(app, OTHER_ID, invite_code=invite.code, name="Аня")
    return app.ctx.services["workouts"], app.ctx.services["runs"], a, b


async def _squat(workouts: Any, actor: Any) -> Any:
    found = await workouts.exercises(actor, await workouts.filters(actor, Kind.GYM))
    return next(e for e in found if e.spec.key == "back_squat")


async def test_seed_is_idempotent(app: Any) -> None:
    workouts = app.ctx.services["workouts"]
    assert await workouts.seed_catalog() == 0  # уже загружено при старте


async def test_session_flow_isolation_and_auto_finish(app: Any, clock: Any) -> None:
    """Подходы сохраняются сразу; B не видит и не меняет тренировки A; через 3 часа — автозавершение,
    пустая тренировка удаляется."""
    workouts, _, a, b = await _two(app)
    squat = await _squat(workouts, a)
    session = await workouts.start(a, Kind.GYM, day=DAY)
    assert (await workouts.start(a, Kind.OUTDOOR, day=DAY)).public_id == session.public_id  # одна идущая
    sets = [SetValue(reps=8, weight=Decimal(110))] * 4
    view = await workouts.add_sets(a, session.public_id, squat.public_id, sets, request_id="tg:1")
    await workouts.add_sets(a, session.public_id, squat.public_id, sets, request_id="tg:1")
    assert (view.tonnage, view.sets_count) == (3520, 4)
    assert await workouts.session(b, session.public_id) is None and await workouts.open_session(b) is None
    with pytest.raises(AppError):
        await workouts.add_sets(b, session.public_id, squat.public_id, sets)
    with pytest.raises(AppError):
        await workouts.add_sets(a, session.public_id, squat.public_id, [])
    assert await workouts.finish(b, session.public_id, 60) is None
    assert await workouts.delete_session(b, session.public_id) is None
    assert await workouts.last_sets(b, "не-uuid") is None
    empty = await workouts.start(b, Kind.FREE, day=DAY)
    clock.advance(seconds=AUTO_FINISH_AFTER.total_seconds() + 60)
    assert await workouts.auto_finish(clock.now()) == 2
    done = await workouts.session(a, session.public_id)
    assert (done.open, done.auto_finished, done.duration_min) == (False, True, 1)
    assert await workouts.session(b, empty.public_id) is None  # без подходов — не сохранена
    assert await workouts.auto_finish(clock.now()) == 0
    assert await workouts.undo_last(a, session.public_id) is None  # завершена
    assert await workouts.finish(a, session.public_id, 60) is None
    last = await workouts.last_sets(a, squat.public_id)
    assert last is not None and last[0] == DAY and len(last[1]) == 4
    assert await workouts.count_between(a, DAY, DAY) == 1 and await workouts.count_between(b, DAY, DAY) == 0
    await workouts.move(a, session.public_id, DAY - timedelta(days=1))
    assert await workouts.day_of(a, session.public_id) == DAY - timedelta(days=1)
    assert await workouts.day_of(a, "не-uuid") is None
    assert await workouts.exercise(a, "не-uuid") is None


async def test_undo_last_own_exercise_and_settings(app: Any) -> None:
    workouts, _, a, b = await _two(app)
    session = await workouts.start(a, Kind.FREE, day=DAY)
    assert (await workouts.undo_last(a, session.public_id)).blocks == ()
    rope = await workouts.create_exercise(a, name=" Скакалка ", measure=Measure.TIME, kind=Kind.FREE)
    assert rope.own and rope.name == "Скакалка"
    for bad in ("", "x" * 65):
        with pytest.raises(AppError):
            await workouts.create_exercise(a, name=bad, measure=Measure.REPS, kind=Kind.GYM)
    with pytest.raises(AppError) as err:
        await workouts.create_exercise(a, name="скакалка", measure=Measure.REPS, kind=Kind.GYM)
    assert err.value.code == "INPUT-EXERCISE-DUPLICATE"
    assert await workouts.exercise(b, rope.public_id) is None  # своё упражнение видно только автору
    gym_own = await workouts.create_exercise(a, name="Свой жим", measure=Measure.WEIGHT_REPS, kind=Kind.GYM)
    assert gym_own.spec.weight_step == Decimal("2.5")
    await workouts.add_sets(a, session.public_id, rope.public_id, [SetValue(seconds=60)] * 3)
    after = await workouts.undo_last(a, session.public_id)
    assert after is not None and after.blocks == ()
    recent = await workouts.recent(a, await workouts.filters(a, Kind.FREE))
    assert recent == []  # убранное упражнение не попадает в недавние
    settings = await workouts.update_settings(a, weekly_goal=4, bands=[Band.HEAVY, Band.LIGHT], show_all=True,
                                              band_last=False)
    assert (settings.weekly_goal, settings.bands, settings.show_all, settings.band_last) == (
        4, (Band.LIGHT, Band.HEAVY), True, False)
    assert (await workouts.settings(b)).weekly_goal == 3
    groups = dict(await workouts.groups(a, await workouts.filters(a, Kind.OUTDOOR, band=False)))
    assert all(g.value != "band" for g in groups)


async def test_runs_isolation_and_move(app: Any) -> None:
    _, runs, a, b = await _two(app)
    first = await runs.record(a, distance_km=Decimal("5.2"), seconds=1720, day=DAY, request_id="tg:5")
    again = await runs.record(a, distance_km=Decimal("5.2"), seconds=1720, day=DAY, request_id="tg:5")
    assert first.public_id == again.public_id and first.value.pace == 331
    assert await runs.last(b) is None and await runs.run(b, first.public_id) is None
    assert await runs.delete(b, first.public_id) is None
    assert await runs.count_between(a, DAY, DAY) == 1 and await runs.count_between(b, DAY, DAY) == 0
    await runs.move(a, first.public_id, DAY - timedelta(days=1))
    assert await runs.day_of(a, first.public_id) == DAY - timedelta(days=1)
    assert await runs.day_of(a, "не-uuid") is None
    assert (await runs.delete(a, first.public_id)).value.distance_km == Decimal("5.2")
    assert await runs.day_runs(a, DAY - timedelta(days=1)) == []
