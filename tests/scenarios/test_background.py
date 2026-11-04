"""Поведенческие сценарии: настоящие фоновые задачи бота с реальным ожиданием (около минуты).

Здесь не вызывается сброс вручную: запускаются те же циклы, что на сервере, и тест ждёт, пока они сработают.
"""

import asyncio
import time

from sqlalchemy import select

from habit_bot.app import heartbeat_path
from habit_bot.channels.telegram.dialogs.models import DialogState
from habit_bot.kernel.jobs import JobSpec
from tests.scenarios.harness import Persona, World

REAL_WAIT_SECONDS = 75  # задача сброса запускается раз в минуту


async def _states(world: World) -> list[DialogState]:
    async with world.app.ctx.uow() as uow:
        return list((await uow.session.execute(select(DialogState))).scalars().all())


async def test_s27_background_reset_really_runs(world: World, owner: Persona) -> None:
    """S-27. Пользователь начал ввод и ушёл; на сервере работают настоящие фоновые задачи — в течение минуты
    ввод сброшен сам, без действий пользователя и без сообщений ему; отметка «бот жив» пишется."""
    await owner.say("/check")
    assert len(await _states(world)) == 1
    sent = len(owner.texts())
    world.clock.advance(minutes=16)  # бездействие дольше 15 минут
    tasks = world.app.start_background()
    try:
        assert heartbeat_path(world.settings.data_dir).exists() or await _wait(
            lambda: heartbeat_path(world.settings.data_dir).exists(), 5)
        started = time.monotonic()
        assert await _wait_async(lambda: _states(world), REAL_WAIT_SECONDS), "сброс за минуту не сработал"
        waited = time.monotonic() - started
    finally:
        await world.app.stop_background(tasks)
    assert 50 <= waited <= REAL_WAIT_SECONDS
    assert len(owner.texts()) == sent
    assert await owner.tap("✕ Отмена") == "Это меню устарело. Вот главное меню 👇"


async def test_s28_broken_job_does_not_stop_others(world: World, owner: Persona) -> None:
    """S-28. Одна фоновая задача падает каждую минуту — остальные продолжают работать, бот отвечает."""
    calls: list[str] = []

    async def broken() -> None:
        calls.append("сломанная")
        raise RuntimeError("сбой задачи")

    world.app.ctx.jobs.insert(0, JobSpec("сломанная", world.app.ctx.jobs[0].every, broken))
    await owner.say("/check")
    world.clock.advance(minutes=16)
    tasks = world.app.start_background()
    try:
        assert await _wait_async(lambda: _states(world), REAL_WAIT_SECONDS)
    finally:
        await world.app.stop_background(tasks)
    assert calls == ["сломанная"]
    assert (await owner.tap("🍽 Еда")).startswith("🍽 Еда — скоро")


async def _wait(condition: object, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():  # type: ignore[operator]
            return True
        await asyncio.sleep(0.5)
    return False


async def _wait_async(rows: object, seconds: float) -> bool:
    """Ждёт, пока незаконченного ввода не останется."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not await rows():  # type: ignore[operator]
            return True
        await asyncio.sleep(1)
    return False
