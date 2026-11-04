"""Сборка приложения: настройки → ядро → каналы → модули. Её же используют тесты."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from aiogram.client.session.base import BaseSession
from sqlalchemy.ext.asyncio import AsyncEngine

from habit_bot.channels.telegram.channel import TelegramChannel
from habit_bot.kernel.channels import ChannelRegistry
from habit_bot.kernel.clock import Clock, SystemClock
from habit_bot.kernel.config import Settings
from habit_bot.kernel.db import UnitOfWork, make_engine, make_sessionmaker
from habit_bot.kernel.events import EventBus
from habit_bot.kernel.idempotency import IdempotencyStore
from habit_bot.kernel.jobs import JobSpec, run_forever, run_safely
from habit_bot.kernel.modules import ModuleContext, ModuleRegistry
from habit_bot.kernel.purge import purge
from habit_bot.modules import KNOWN_MODULES
from habit_bot.platform.alerts.alerter import AdminAlerter

log = logging.getLogger(__name__)
HEARTBEAT_EVERY_SECONDS = 30
EXPIRE_EVERY = timedelta(minutes=1)
PURGE_EVERY = timedelta(hours=6)


def heartbeat_path(data_dir: Path) -> Path:
    return data_dir / "tmp" / "heartbeat"


def write_heartbeat(data_dir: Path, now: datetime) -> None:
    """Отметка «бот жив» для проверки здоровья контейнера."""
    path = heartbeat_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(now.isoformat(), encoding="utf-8")


@dataclass
class App:
    settings: Settings
    engine: AsyncEngine
    ctx: ModuleContext
    telegram: TelegramChannel
    alerter: AdminAlerter
    registry: ModuleRegistry

    async def startup(self) -> None:
        for hook in self.ctx.startup_hooks:
            await hook()
        for job in self.ctx.jobs:
            if job.run_at_start:
                await run_safely(job)
        self.telegram.finalize()

    async def heartbeat_forever(self) -> None:
        while True:
            write_heartbeat(self.settings.data_dir, self.ctx.clock.now())
            await asyncio.sleep(HEARTBEAT_EVERY_SECONDS)

    def start_background(self) -> list[asyncio.Task[None]]:
        """Фоновые задачи бота: отметка «жив» и задачи модулей по расписанию (сброс ввода раз в минуту и т. п.)."""
        tasks = [asyncio.create_task(self.heartbeat_forever())]
        tasks += [asyncio.create_task(run_forever(job)) for job in self.ctx.jobs]
        return tasks

    @staticmethod
    async def stop_background(tasks: list[asyncio.Task[None]]) -> None:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def run(self) -> None:  # pragma: no cover — проверяется пробным запуском контейнера в CI
        await self.startup()
        tasks = self.start_background()
        try:
            await self.telegram.start()
        finally:
            await self.stop_background(tasks)
            await self.close()

    async def close(self) -> None:
        await self.telegram.stop()
        await self.engine.dispose()


def build_app(
    settings: Settings, *, telegram_session: BaseSession | None = None, clock: Clock | None = None,
    geocoder: object | None = None,
) -> App:
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    events = EventBus()
    clock = clock or SystemClock()

    def uow() -> UnitOfWork:
        return UnitOfWork(sessionmaker, events)

    channels = ChannelRegistry()
    telegram = TelegramChannel(settings, uow=uow, clock=clock, session=telegram_session)
    channels.add(telegram)
    alerter = AdminAlerter(uow=uow, clock=clock, notifier=telegram.notifier, admin_chat_ids=settings.admin_tg_ids)
    telegram.set_alerter(alerter)

    ctx = ModuleContext(
        settings=settings, clock=clock, uow=uow, events=events, idempotency=IdempotencyStore(),
        channels=channels, services={"alerter": alerter, **({"geocoder": geocoder} if geocoder else {})},
    )
    ctx.add_job(JobSpec("dialogs.expire", EXPIRE_EVERY, telegram.expire_idle))

    async def purge_deleted() -> int:
        return await purge(uow, clock.now(), ctx.idempotency)

    ctx.add_job(JobSpec("kernel.purge", PURGE_EVERY, purge_deleted))
    registry = ModuleRegistry(KNOWN_MODULES)
    registry.load(settings.enabled_modules)
    registry.register_all(ctx)
    return App(settings=settings, engine=engine, ctx=ctx, telegram=telegram, alerter=alerter, registry=registry)
