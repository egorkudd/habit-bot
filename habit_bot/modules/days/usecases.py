"""Дни (раздел 3.7, 4.3): выходные, карточка дня, перенос записей. Без aiogram.

Дата записи приходит в сценарий явным параметром ``day`` — канал сам решает, «сегодня» это или «Другой день».
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import select

from habit_bot.kernel.clock import Clock
from habit_bot.kernel.db import UowFactory
from habit_bot.kernel.domain.parsing import ensure_not_future, logical_day
from habit_bot.kernel.identity import Actor
from habit_bot.modules.days.models import DAY_OFF, DayStatus
from habit_bot.modules.users.public import GoalView, Profiles

log = logging.getLogger(__name__)
DEFAULT_TZ = ZoneInfo("Europe/Moscow")

CardSection = Callable[[Actor, date], Awaitable[list[str]]]


@dataclass(frozen=True, slots=True)
class DayCardData:
    """Каркас карточки дня (раздел 3.1): дата, выходной, цель на эту дату и строки разделов."""

    day: date
    day_off: bool
    goal: GoalView | None
    lines: tuple[str, ...] = field(default_factory=tuple)


class EntryMover(Protocol):
    """Перенос записи раздела на другой день (еда, зарядка, привычки — части 5–8)."""

    async def day_of(self, actor: Actor, public_id: str) -> date | None: ...

    async def move(self, actor: Actor, public_id: str, day: date) -> None: ...


@dataclass(frozen=True, slots=True)
class MoveResult:
    old_day: date
    new_day: date


class Days:
    def __init__(self, *, uow: UowFactory, clock: Clock, profiles: Profiles, tz: tzinfo = DEFAULT_TZ) -> None:
        self._uow = uow
        self._clock = clock
        self._profiles = profiles
        self._tz = tz
        self._sections: list[CardSection] = []
        self._movers: dict[str, EntryMover] = {}

    def now(self) -> datetime:
        return self._clock.now()

    @property
    def tz(self) -> tzinfo:
        """Часовой пояс дат и времени на экранах (раздел 4.3: в MVP — Москва)."""
        return self._tz

    def today(self) -> date:
        return logical_day(self._clock.now(), self._tz)

    # --- регистрация разделов (части 5–8) ---
    def add_card_section(self, section: CardSection) -> None:
        self._sections.append(section)

    def add_mover(self, kind: str, mover: EntryMover) -> None:
        self._movers[kind] = mover

    # --- выходной ---
    async def toggle_day_off(self, actor: Actor, day: date) -> bool:
        """«🛌 Выходной» отмечает день; повторное нажатие снимает отметку. Возвращает, выходной ли день теперь."""
        ensure_not_future(day, self.today())
        async with self._uow() as uow:
            row = (await uow.session.execute(
                select(DayStatus).where(DayStatus.user_id == actor.user_id, DayStatus.day == day)
            )).scalar_one_or_none()
            if row is None:
                uow.session.add(DayStatus(user_id=actor.user_id, day=day, status=DAY_OFF))
                return True
            if row.deleted_at is None:
                row.deleted_at = self._clock.now()
                return False
            row.deleted_at = None
            row.status = DAY_OFF
            return True

    async def days_off(self, actor: Actor, start: date, end: date) -> set[date]:
        """Выходные пользователя в периоде — для серий и светофора (части 7 и 10)."""
        async with self._uow() as uow:
            rows = await uow.session.execute(
                select(DayStatus.day).where(
                    DayStatus.user_id == actor.user_id, DayStatus.deleted_at.is_(None), DayStatus.status == DAY_OFF,
                    DayStatus.day >= start, DayStatus.day <= end,
                )
            )
            return set(rows.scalars().all())

    async def is_day_off(self, actor: Actor, day: date) -> bool:
        return day in await self.days_off(actor, day, day)

    # --- карточка ---
    async def card(self, actor: Actor, day: date) -> DayCardData:
        lines: list[str] = []
        for section in self._sections:
            lines.extend(await section(actor, day))
        goal = await self._profiles.goal_on(actor, day)
        return DayCardData(day=day, day_off=await self.is_day_off(actor, day), goal=goal, lines=tuple(lines))

    # --- перенос ---
    async def move(self, actor: Actor, kind: str, public_id: str, day: date | None = None) -> MoveResult | None:
        """Переносит запись на ``day`` или, если не задано, на день раньше её дня («📅 На вчера»).

        Чужая или несуществующая запись — ``None``: раздел ищет её только среди записей пользователя.
        """
        mover = self._movers.get(kind)
        if mover is None:
            return None
        old_day = await mover.day_of(actor, public_id)
        if old_day is None:
            return None
        new_day = ensure_not_future(day or old_day - timedelta(days=1), self.today())
        await mover.move(actor, public_id, new_day)
        log.info("Запись перенесена", extra={"user": actor.user_id})
        return MoveResult(old_day, new_day)
