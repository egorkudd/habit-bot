"""Фоновые задачи по расписанию (архитектура, раздел 6: ``JobSpec``)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class JobSpec:
    name: str
    every: timedelta
    run: Callable[[], Awaitable[Any]]
    run_at_start: bool = True  # например, сброс просроченного ввода сразу после перезапуска


async def run_safely(job: JobSpec) -> bool:
    """Один запуск: ошибка задачи пишется в лог и не останавливает бота."""
    try:
        await job.run()
    except Exception:
        log.exception("Фоновая задача %s упала", job.name, extra={"code": "INTERNAL", "handler": job.name})
        return False
    return True


async def run_forever(job: JobSpec) -> None:
    while True:
        await asyncio.sleep(job.every.total_seconds())
        await run_safely(job)
