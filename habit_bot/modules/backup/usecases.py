"""Бэкапы (раздел 3.13, 7): копия базы раз в 2 дня и по кнопке «Бэкап сейчас» — на сервере одна последняя копия,
администратору в Telegram — зашифрованный паролем BACKUP_PASSWORD файл. Если новая копия не удалась, прошлая
остаётся на месте. Без aiogram."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import Protocol

from sqlalchemy import select

from habit_bot.kernel.clock import Clock
from habit_bot.kernel.db import UowFactory
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.identity import Actor
from habit_bot.ops import make_backup
from habit_bot.platform.backup.crypto import encrypt
from habit_bot.platform.backup.models import BackupLog

log = logging.getLogger(__name__)
EVERY = timedelta(days=2)
TELEGRAM_LIMIT = 50 * 1024 * 1024
SCHEDULE, MANUAL = "schedule", "manual"


class Alerter(Protocol):
    async def alert(self, code: str, *, where: str, **params: object) -> None: ...


@dataclass(frozen=True, slots=True)
class BackupFile:
    filename: str
    data: bytes
    made_at: datetime

    @property
    def size_mb(self) -> float:
        return round(len(self.data) / 1024 / 1024, 1)


@dataclass(frozen=True, slots=True)
class LastBackup:
    at: datetime
    size_kb: int


class Backups:
    WHERE = "Бэкап"

    def __init__(self, *, uow: UowFactory, clock: Clock, tz: tzinfo, db_path: Path, target: Path, password: str,
                 alerter: Alerter | None = None) -> None:
        self._uow = uow
        self._clock = clock
        self._tz = tz
        self._db_path = db_path
        self._target = target
        self._password = password
        self._alerter = alerter

    async def last(self) -> LastBackup | None:
        async with self._uow() as uow:
            row = (await uow.session.execute(select(BackupLog).where(BackupLog.ok.is_(True))
                                             .order_by(BackupLog.created_at.desc()).limit(1))).scalar_one_or_none()
            return LastBackup(row.created_at, row.size_kb) if row else None

    async def due(self, now: datetime | None = None) -> bool:
        """Пора ли бэкапу по расписанию: последний удачный был 2 дня назад или раньше (или не было)."""
        last = await self.last()
        return last is None or (now or self._clock.now()) - last.at >= EVERY

    async def _log(self, now: datetime, reason: str, *, size_kb: int = 0, error: str = "") -> None:
        async with self._uow() as uow:
            uow.session.add(BackupLog(created_at=now, ok=not error, reason=reason, size_kb=size_kb,
                                      error=error[:255]))

    async def make(self, reason: str = MANUAL) -> BackupFile:
        """Свежая копия базы (проверка целостности, замена старой только после неё) и зашифрованный файл."""
        now = self._clock.now()
        try:
            await asyncio.to_thread(make_backup, self._db_path, self._target)
            data = await asyncio.to_thread(encrypt, self._target.read_bytes(), self._password)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"[:200]
            log.exception("Бэкап не удался", extra={"code": "BKP-BOT"})
            await self._log(now, reason, error=detail)
            if self._alerter is not None:
                await self._alerter.alert("BKP-BOT", where=self.WHERE, detail=detail)
            raise AppError("BKP-BOT", detail=detail) from exc
        await self._log(now, reason, size_kb=max(1, len(data) // 1024))
        name = f"habit-bot-{now.astimezone(self._tz):%Y-%m-%d-%H%M}.db.enc"
        made = BackupFile(name, data, now)
        if len(data) > TELEGRAM_LIMIT and self._alerter is not None:
            await self._alerter.alert("BKP-BIG", where=self.WHERE, size=made.size_mb)
        return made

    @staticmethod
    def require_admin(actor: Actor) -> None:
        if not actor.is_admin:
            raise AppError("ACCESS-FOREIGN")

    def fits_telegram(self, made: BackupFile) -> bool:
        return len(made.data) <= TELEGRAM_LIMIT
