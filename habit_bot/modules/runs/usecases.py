"""Бег (раздел 3.5, 4.9): запись забега, сравнение с прошлым в той же группе, рекорды, перенос. Без aiogram."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_bot.kernel.clock import Clock
from habit_bot.kernel.db import UowFactory
from habit_bot.kernel.idempotency import IdempotencyStore
from habit_bot.kernel.identity import Actor
from habit_bot.modules.runs.domain.runs import RunValue, comparison, group_of, pace, records
from habit_bot.modules.runs.models import RunEntry


@dataclass(frozen=True, slots=True)
class RunView:
    public_id: str
    day: date
    value: RunValue
    comparison: str = ""
    records: tuple[str, ...] = ()


def _uuid(public_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(hex=public_id)
    except (ValueError, TypeError):
        return None


def _value(row: RunEntry) -> RunValue:
    return RunValue(Decimal(str(row.distance_km)), row.duration_sec)


class Runs:
    def __init__(self, *, uow: UowFactory, clock: Clock, idempotency: IdempotencyStore) -> None:
        self._uow = uow
        self._clock = clock
        self._idempotency = idempotency

    @staticmethod
    async def _rows(session: AsyncSession, actor: Actor, *, before_id: int | None = None) -> list[RunEntry]:
        query = select(RunEntry).where(RunEntry.user_id == actor.user_id, RunEntry.deleted_at.is_(None))
        if before_id is not None:
            query = query.where(RunEntry.id < before_id)
        return list((await session.execute(query.order_by(RunEntry.id))).scalars().all())

    async def last(self, actor: Actor) -> RunValue | None:
        """Для кнопки «Как в прошлый раз (5,0 км)»."""
        async with self._uow() as uow:
            rows = await self._rows(uow.session, actor)
            return _value(rows[-1]) if rows else None

    async def record(self, actor: Actor, *, distance_km: Decimal, seconds: int, day: date,
                     request_id: str | None = None) -> RunView:
        async def action(session: AsyncSession) -> dict[str, Any]:
            row = RunEntry(user_id=actor.user_id, day=day, logged_at=self._clock.now(),
                           distance_km=float(distance_km), duration_sec=seconds, pace_sec=pace(distance_km, seconds))
            session.add(row)
            await session.flush()
            return {"run": row.public_id.hex}

        async with self._uow() as uow:
            if request_id is None:
                result = await action(uow.session)
            else:
                result = await self._idempotency.run_once(
                    uow.session, user_id=actor.user_id, request_id=request_id, now=self._clock.now(),
                    action=lambda: action(uow.session))
        found = await self.run(actor, result["run"])
        assert found is not None
        return found

    async def _own(self, session: AsyncSession, actor: Actor, public_id: str) -> RunEntry | None:
        public = _uuid(public_id)
        if public is None:
            return None
        return (await session.execute(select(RunEntry).where(
            RunEntry.public_id == public, RunEntry.user_id == actor.user_id, RunEntry.deleted_at.is_(None))
        )).scalar_one_or_none()

    async def run(self, actor: Actor, public_id: str) -> RunView | None:
        """Забег со сравнением с прошлым в той же группе дистанций и рекордами на момент записи."""
        async with self._uow() as uow:
            row = await self._own(uow.session, actor, public_id)
            if row is None:
                return None
            current = _value(row)
            history = [_value(r) for r in await self._rows(uow.session, actor, before_id=row.id)]
            group = group_of(current.distance_km)
            previous = next((r for r in reversed(history) if group_of(r.distance_km) is group), None)
            return RunView(row.public_id.hex, row.day, current, comparison(current, previous),
                           tuple(records(current, history)))

    async def delete(self, actor: Actor, public_id: str) -> RunView | None:
        found = await self.run(actor, public_id)
        if found is None:
            return None
        async with self._uow() as uow:
            row = await self._own(uow.session, actor, public_id)
            assert row is not None
            row.deleted_at = self._clock.now()
        return found

    async def day_runs(self, actor: Actor, day: date) -> list[RunValue]:
        async with self._uow() as uow:
            rows = (await uow.session.execute(select(RunEntry).where(
                RunEntry.user_id == actor.user_id, RunEntry.day == day, RunEntry.deleted_at.is_(None))
                .order_by(RunEntry.id))).scalars().all()
            return [_value(r) for r in rows]

    async def runs_between(self, actor: Actor, start: date, end: date) -> list[tuple[date, RunValue]]:
        """Забеги за период по порядку — для итогов (сравнение, рекорды) и экспорта."""
        async with self._uow() as uow:
            rows = (await uow.session.execute(select(RunEntry).where(
                RunEntry.user_id == actor.user_id, RunEntry.day >= start, RunEntry.day <= end,
                RunEntry.deleted_at.is_(None)).order_by(RunEntry.day, RunEntry.id))).scalars().all()
            return [(r.day, _value(r)) for r in rows]

    async def count_between(self, actor: Actor, start: date, end: date) -> int:
        """Забеги за период — для цели «тренировок в неделю» (бег считается тренировкой)."""
        async with self._uow() as uow:
            return int((await uow.session.execute(select(func.count(RunEntry.id)).where(
                RunEntry.user_id == actor.user_id, RunEntry.deleted_at.is_(None), RunEntry.day >= start,
                RunEntry.day <= end))).scalar_one())

    # --- перенос (раздел 3.7) ---
    async def day_of(self, actor: Actor, public_id: str) -> date | None:
        found = await self.run(actor, public_id)
        return found.day if found else None

    async def move(self, actor: Actor, public_id: str, day: date) -> None:
        async with self._uow() as uow:
            row = await self._own(uow.session, actor, public_id)
            if row is not None:
                row.day = day
