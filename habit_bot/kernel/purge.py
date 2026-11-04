"""Окончательное удаление (раздел 5): удалённые записи хранятся 30 дней как отметка для синхронизации,
потом стираются; ключи повторов — 24 часа. Таблицы находятся сами — по колонке ``deleted_at``."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete

from habit_bot.kernel.db import Base, UowFactory
from habit_bot.kernel.idempotency import IdempotencyStore

log = logging.getLogger(__name__)
KEEP_DELETED = timedelta(days=30)


async def purge(uow: UowFactory, now: datetime, idempotency: IdempotencyStore | None = None) -> int:
    removed = 0
    async with uow() as unit:
        for table in Base.metadata.sorted_tables:
            if "deleted_at" in table.c:
                result = await unit.session.execute(
                    delete(table).where(table.c.deleted_at.is_not(None), table.c.deleted_at < now - KEEP_DELETED)
                )
                removed += int(getattr(result, "rowcount", 0) or 0)
        if idempotency is not None:
            removed += await idempotency.purge(unit.session, now)
    if removed:
        log.info("Окончательно удалено строк: %s", removed)
    return removed
