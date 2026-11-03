"""Сборка приложения: настройки → ядро → каналы → модули. Её же используют тесты."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime
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
from habit_bot.kernel.modules import ModuleContext, ModuleRegistry
from habit_bot.modules import KNOWN_MODULES
from habit_bot.platform.alerts.alerter import AdminAlerter

log = logging.getLogger(__name__)
HEARTBEAT_EVERY_SECONDS = 30


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
        self.telegram.finalize()

    async def heartbeat_forever(self) -> None:  # pragma: no cover — бесконечный цикл; одна итерация — write_heartbeat
        while True:
            write_heartbeat(self.settings.data_dir, self.ctx.clock.now())
            await asyncio.sleep(HEARTBEAT_EVERY_SECONDS)

    async def run(self) -> None:  # pragma: no cover — проверяется пробным запуском контейнера в CI
        await self.startup()
        heartbeat = asyncio.create_task(self.heartbeat_forever())
        try:
            await self.telegram.start()
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
            await self.close()

    async def close(self) -> None:
        await self.telegram.stop()
        await self.engine.dispose()


def build_app(settings: Settings, *, telegram_session: BaseSession | None = None, clock: Clock | None = None) -> App:
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    events = EventBus()
    clock = clock or SystemClock()

    def uow() -> UnitOfWork:
        return UnitOfWork(sessionmaker, events)

    channels = ChannelRegistry()
    telegram = TelegramChannel(settings, session=telegram_session)
    channels.add(telegram)
    alerter = AdminAlerter(uow=uow, clock=clock, notifier=telegram.notifier, admin_chat_ids=settings.admin_tg_ids)
    telegram.set_alerter(alerter)

    ctx = ModuleContext(
        settings=settings, clock=clock, uow=uow, events=events, idempotency=IdempotencyStore(),
        channels=channels, services={"alerter": alerter},
    )
    registry = ModuleRegistry(KNOWN_MODULES)
    registry.load(settings.enabled_modules)
    registry.register_all(ctx)
    return App(settings=settings, engine=engine, ctx=ctx, telegram=telegram, alerter=alerter, registry=registry)
