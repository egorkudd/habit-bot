"""Свои привычки (раздел 3.6, 4.6): шаблоны и свои, отметки, выполнение за день, серии, архив. Без aiogram."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_bot.kernel.clock import Clock
from habit_bot.kernel.db import UowFactory
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.idempotency import IdempotencyStore
from habit_bot.kernel.identity import Actor
from habit_bot.modules.days.public import Days
from habit_bot.modules.habits.domain.habits import (
    DEFAULT_STEP,
    STARTER,
    STREAK_LOOKBACK,
    TEMPLATE_BY_KEY,
    Measure,
    daily_totals,
    is_done,
    is_scheduled,
    streak,
)
from habit_bot.modules.habits.models import Habit, HabitEntry
from habit_bot.modules.users.public import Profiles

log = logging.getLogger(__name__)
ACTIVE, ARCHIVED = "active", "archived"
NAME_MAX, SHORT_MAX = 64, 20
HABITS_LIMIT = 30


def dec(value: float | int | str | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


@dataclass(frozen=True, slots=True)
class HabitView:
    public_id: str
    name: str
    short: str
    emoji: str
    measure: Measure
    unit: str
    goal: Decimal | None
    step: Decimal | None
    quick_values: tuple[Decimal, ...]
    weekdays: tuple[int, ...] | None
    position: int
    archived: bool
    template_key: str | None

    @property
    def label(self) -> str:
        """Подпись кнопки: «👁 Глаза»."""
        return f"{self.emoji} {self.short}"

    @property
    def once(self) -> bool:
        """Однократная отметка в день («Витамины»): повторное нажатие предлагает снять отметку."""
        return self.measure is Measure.CHECK and self.goal == 1


@dataclass(frozen=True, slots=True)
class DayHabit:
    habit: HabitView
    fact: Decimal
    done: bool
    scheduled: bool


@dataclass(frozen=True, slots=True)
class MarkResult:
    habit: HabitView
    entry_id: str
    value: Decimal
    day: date
    fact: Decimal
    done: bool
    just_done: bool  # этой записью цель выполнена
    streak: int


def _uuid(public_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(hex=public_id)
    except (ValueError, TypeError):
        return None


def habit_view(h: Habit) -> HabitView:
    quick = tuple(Decimal(str(v)) for v in (h.quick_values or []))
    weekdays = tuple(h.weekdays) if h.weekdays is not None else None
    return HabitView(h.public_id.hex, h.name, h.short, h.emoji, Measure(h.measure), h.unit, dec(h.goal), dec(h.step),
                     quick, weekdays, h.position, h.status == ARCHIVED, h.template_key)


class Habits:
    def __init__(self, *, uow: UowFactory, clock: Clock, idempotency: IdempotencyStore, profiles: Profiles,
                 days: Days) -> None:
        self._uow = uow
        self._clock = clock
        self._idempotency = idempotency
        self._profiles = profiles
        self._days = days

    # --- список ---
    @staticmethod
    async def _rows(session: AsyncSession, actor: Actor, *, archived: bool = False) -> list[Habit]:
        query = select(Habit).where(Habit.user_id == actor.user_id)
        query = query.where(Habit.status == (ARCHIVED if archived else ACTIVE))
        return list((await session.execute(query.order_by(Habit.position, Habit.id))).scalars().all())

    async def habits(self, actor: Actor, *, archived: bool = False) -> list[HabitView]:
        async with self._uow() as uow:
            return [habit_view(h) for h in await self._rows(uow.session, actor, archived=archived)]

    async def _own(self, session: AsyncSession, actor: Actor, public_id: str) -> Habit | None:
        public = _uuid(public_id)
        if public is None:
            return None
        return (await session.execute(
            select(Habit).where(Habit.public_id == public, Habit.user_id == actor.user_id)
        )).scalar_one_or_none()

    async def habit(self, actor: Actor, public_id: str) -> HabitView | None:
        async with self._uow() as uow:
            found = await self._own(uow.session, actor, public_id)
            return habit_view(found) if found else None

    async def by_label(self, actor: Actor, label: str) -> HabitView | None:
        clean = " ".join(label.split())
        return next((h for h in await self.habits(actor) if h.label == clean), None)

    # --- создание и правка ---
    async def _check_names(self, session: AsyncSession, actor: Actor, name: str, short: str,
                           skip_id: int | None = None) -> None:
        for other in await self._rows(session, actor):
            if other.id == skip_id:
                continue
            if other.name.casefold() == name.casefold() or other.short.casefold() == short.casefold():
                raise AppError("INPUT-HABIT-DUPLICATE", name=name)

    async def create(
        self, actor: Actor, *, name: str, emoji: str, measure: Measure, short: str | None = None, unit: str = "",
        goal: Decimal | None = None, step: Decimal | None = None, quick: Sequence[Decimal] = (),
        weekdays: Sequence[int] | None = None, template_key: str | None = None,
    ) -> HabitView:
        clean = " ".join(name.split())
        if not 1 <= len(clean) <= NAME_MAX:
            raise AppError("INPUT-TEXT", field="Название", low=1, high=NAME_MAX, length=len(clean))
        label = " ".join((short or clean).split())[:SHORT_MAX]
        async with self._uow() as uow:
            rows = await self._rows(uow.session, actor)
            if len(rows) >= HABITS_LIMIT:
                raise AppError("INPUT-RANGE", field="Привычек", low=1, high=HABITS_LIMIT, unit="", value=len(rows) + 1,
                               guess="")
            await self._check_names(uow.session, actor, clean, label)
            habit = Habit(
                user_id=actor.user_id, kind="custom", template_key=template_key, name=clean, short=label,
                emoji=emoji or "✅", measure=measure.value, unit=unit.strip()[:16], goal=_f(goal), step=_f(step),
                quick_values=[str(v) for v in quick][:4], weekdays=sorted(set(weekdays)) if weekdays else None,
                position=max((h.position for h in rows), default=0) + 1, status=ACTIVE,
            )
            uow.session.add(habit)
            await uow.session.flush()
            return habit_view(habit)

    async def from_template(self, actor: Actor, key: str) -> HabitView:
        t = TEMPLATE_BY_KEY[key]
        return await self.create(actor, name=t.name, short=t.short, emoji=t.emoji, measure=t.measure, unit=t.unit,
                                 goal=t.goal, step=t.step, template_key=t.key)

    async def apply_starter(self, actor: Actor) -> list[HabitView]:
        """«Примеры привычек» из анкеты — один раз, при первом открытии привычек."""
        if not await self._profiles.consume_starter(actor, "habits"):
            return []
        existing = {h.template_key for h in await self.habits(actor)}
        return [await self.from_template(actor, key) for key in STARTER if key not in existing]

    async def update(self, actor: Actor, public_id: str, **fields: Any) -> HabitView:
        """Правка привычки: название, цель, шаг, быстрые значения, расписание. Прошлые записи не меняются."""
        async with self._uow() as uow:
            habit = await self._own(uow.session, actor, public_id)
            if habit is None:
                raise AppError("UI-STALE")
            if "name" in fields:
                name = " ".join(str(fields["name"]).split())
                if not 1 <= len(name) <= NAME_MAX:
                    raise AppError("INPUT-TEXT", field="Название", low=1, high=NAME_MAX, length=len(name))
                short = name[:SHORT_MAX]
                await self._check_names(uow.session, actor, name, short, skip_id=habit.id)
                habit.name, habit.short = name, short
            if "emoji" in fields:
                habit.emoji = str(fields["emoji"])[:8]
            if "goal" in fields:
                habit.goal = _f(fields["goal"])
            if "step" in fields:
                habit.step = _f(fields["step"])
            if "quick" in fields:
                habit.quick_values = [str(v) for v in fields["quick"]][:4]
            if "weekdays" in fields:
                days = fields["weekdays"]
                habit.weekdays = None if days is None or len(set(days)) == 7 else sorted(set(days))
            await uow.session.flush()
            return habit_view(habit)

    async def move_up(self, actor: Actor, public_id: str) -> None:
        async with self._uow() as uow:
            rows = await self._rows(uow.session, actor)
            index = next((i for i, h in enumerate(rows) if h.public_id.hex == public_id), None)
            if index:
                above = rows[index - 1]
                above.position, rows[index].position = rows[index].position, above.position

    async def set_archived(self, actor: Actor, public_id: str, archived: bool) -> HabitView:
        """Архив: привычка пропадает из списков и с главного экрана, история остаётся."""
        async with self._uow() as uow:
            habit = await self._own(uow.session, actor, public_id)
            if habit is None:
                raise AppError("UI-STALE")
            habit.status = ARCHIVED if archived else ACTIVE
            if not archived:
                habit.position = max((h.position for h in await self._rows(uow.session, actor)), default=0) + 1
            return habit_view(habit)

    async def delete(self, actor: Actor, public_id: str) -> HabitView | None:
        """Удалить привычку вместе с историей."""
        async with self._uow() as uow:
            habit = await self._own(uow.session, actor, public_id)
            if habit is None:
                return None
            view = habit_view(habit)
            await uow.session.execute(delete(HabitEntry).where(HabitEntry.habit_id == habit.id))
            await uow.session.delete(habit)
            return view

    # --- записи ---
    async def _fact(self, session: AsyncSession, habit: Habit, day: date) -> Decimal:
        total = (await session.execute(
            select(func.coalesce(func.sum(HabitEntry.value), 0)).where(
                HabitEntry.habit_id == habit.id, HabitEntry.day == day, HabitEntry.deleted_at.is_(None))
        )).scalar_one()
        return dec(total) or Decimal(0)

    async def _done_days(self, session: AsyncSession, habit: Habit, until: date) -> set[date]:
        rows = (await session.execute(
            select(HabitEntry.day, HabitEntry.value).where(
                HabitEntry.habit_id == habit.id, HabitEntry.deleted_at.is_(None),
                HabitEntry.day <= until, HabitEntry.day > until - timedelta(days=STREAK_LOOKBACK))
        )).all()
        goal = dec(habit.goal)
        return {d for d, total in daily_totals((d, Decimal(str(v))) for d, v in rows).items() if is_done(total, goal)}

    async def _streak(self, session: AsyncSession, actor: Actor, habit: Habit, day: date) -> int:
        done = await self._done_days(session, habit, day)
        off = await self._days.days_off(actor, day - timedelta(days=STREAK_LOOKBACK), day)
        weekdays = habit.weekdays
        return streak(day, done.__contains__, lambda d: is_scheduled(weekdays, d), off.__contains__)

    async def streak_of(self, actor: Actor, public_id: str, day: date) -> int:
        async with self._uow() as uow:
            habit = await self._own(uow.session, actor, public_id)
            return await self._streak(uow.session, actor, habit, day) if habit else 0

    async def _result(self, session: AsyncSession, actor: Actor, habit: Habit, entry: HabitEntry,
                      before: Decimal) -> MarkResult:
        fact = await self._fact(session, habit, entry.day)
        goal = dec(habit.goal)
        done = is_done(fact, goal)
        return MarkResult(habit_view(habit), entry.public_id.hex, dec(entry.value) or Decimal(0), entry.day, fact,
                          done, done and not is_done(before, goal),
                          await self._streak(session, actor, habit, entry.day) if done else 0)

    async def mark(
        self, actor: Actor, public_id: str, *, day: date, value: Decimal | None = None, source: str = "button",
        request_id: str | None = None,
    ) -> MarkResult:
        """Записать шаг (или своё значение). Повтор того же апдейта Telegram не задваивает запись."""

        async def action(session: AsyncSession) -> dict[str, Any]:
            habit = await self._own(session, actor, public_id)
            if habit is None or habit.status != ACTIVE:
                raise AppError("UI-STALE")
            amount = value if value is not None else dec(habit.step)
            if amount is None:
                amount = DEFAULT_STEP[Measure(habit.measure)]
            before = await self._fact(session, habit, day)
            entry = HabitEntry(user_id=actor.user_id, habit_id=habit.id, day=day, logged_at=self._clock.now(),
                               value=float(amount), source=source)
            session.add(entry)
            await session.flush()
            return {"entry": entry.public_id.hex, "before": str(before)}

        async with self._uow() as uow:
            if request_id is None:
                result = await action(uow.session)
            else:
                result = await self._idempotency.run_once(
                    uow.session, user_id=actor.user_id, request_id=request_id, now=self._clock.now(),
                    action=lambda: action(uow.session))
        found = await self.entry_result(actor, result["entry"], before=Decimal(result["before"]))
        assert found is not None
        return found

    async def _own_entry(self, session: AsyncSession, actor: Actor, public_id: str) -> HabitEntry | None:
        public = _uuid(public_id)
        if public is None:
            return None
        return (await session.execute(
            select(HabitEntry).where(HabitEntry.public_id == public, HabitEntry.user_id == actor.user_id,
                                     HabitEntry.deleted_at.is_(None))
        )).scalar_one_or_none()

    async def entry_result(self, actor: Actor, entry_id: str, *, before: Decimal | None = None) -> MarkResult | None:
        async with self._uow() as uow:
            entry = await self._own_entry(uow.session, actor, entry_id)
            if entry is None:
                return None
            habit = await uow.session.get(Habit, entry.habit_id)
            assert habit is not None
            fact = await self._fact(uow.session, habit, entry.day)
            prior = before if before is not None else fact - Decimal(str(entry.value))
            return await self._result(uow.session, actor, habit, entry, prior)

    async def undo(self, actor: Actor, entry_id: str) -> DayHabit | None:
        """«Отменить» под ответом: запись удаляется, возвращается новое выполнение за тот день."""
        async with self._uow() as uow:
            entry = await self._own_entry(uow.session, actor, entry_id)
            if entry is None:
                return None
            entry.deleted_at = self._clock.now()
            await uow.session.flush()
            habit = await uow.session.get(Habit, entry.habit_id)
            assert habit is not None
            return await self._day_habit(uow.session, habit, entry.day)

    async def clear_day(self, actor: Actor, public_id: str, day: date) -> int:
        """«Снять отметку»: удалить записи привычки за день."""
        async with self._uow() as uow:
            habit = await self._own(uow.session, actor, public_id)
            if habit is None:
                return 0
            rows = (await uow.session.execute(select(HabitEntry).where(
                HabitEntry.habit_id == habit.id, HabitEntry.day == day, HabitEntry.deleted_at.is_(None)))).scalars()
            count = 0
            for row in rows:
                row.deleted_at = self._clock.now()
                count += 1
            return count

    async def _day_habit(self, session: AsyncSession, habit: Habit, day: date) -> DayHabit:
        fact = await self._fact(session, habit, day)
        view = habit_view(habit)
        return DayHabit(view, fact, is_done(fact, view.goal), is_scheduled(view.weekdays, day))

    async def day(self, actor: Actor, day: date) -> list[DayHabit]:
        """Привычки на день с выполнением, в порядке пользователя."""
        async with self._uow() as uow:
            return [await self._day_habit(uow.session, h, day) for h in await self._rows(uow.session, actor)]

    async def facts_between(self, actor: Actor, start: date, end: date) -> dict[str, dict[date, Decimal]]:
        """Выполнение каждой привычки по дням периода одним запросом — для светофора."""
        async with self._uow() as uow:
            rows = (await uow.session.execute(
                select(Habit.public_id, HabitEntry.day, HabitEntry.value).join(Habit, Habit.id == HabitEntry.habit_id)
                .where(HabitEntry.user_id == actor.user_id, HabitEntry.deleted_at.is_(None),
                       HabitEntry.day >= start, HabitEntry.day <= end)
            )).all()
        result: dict[str, dict[date, Decimal]] = {}
        for public_id, day, value in rows:
            days = result.setdefault(public_id.hex, {})
            days[day] = days.get(day, Decimal(0)) + Decimal(str(value))
        return result

    async def day_entries(self, actor: Actor, public_id: str, day: date) -> list[tuple[datetime, Decimal]]:
        """Отметки привычки за день со временем — для картинки «Итоги»."""
        async with self._uow() as uow:
            habit = await self._own(uow.session, actor, public_id)
            if habit is None:
                return []
            rows = (await uow.session.execute(select(HabitEntry).where(
                HabitEntry.habit_id == habit.id, HabitEntry.day == day, HabitEntry.deleted_at.is_(None))
                .order_by(HabitEntry.logged_at))).scalars().all()
            return [(r.logged_at, Decimal(str(r.value))) for r in rows]

    async def mark_many(self, actor: Actor, public_ids: Sequence[str], *, day: date,
                        request_id: str | None = None) -> list[MarkResult]:
        """«Отметить несколько» → «Записать (3)»: по шагу каждой отмеченной привычки."""
        results = []
        for index, public_id in enumerate(dict.fromkeys(public_ids)):
            key = f"{request_id}:{index}" if request_id else None
            results.append(await self.mark(actor, public_id, day=day, source="many", request_id=key))
        return results

    # --- перенос (раздел 3.7) ---
    async def day_of(self, actor: Actor, public_id: str) -> date | None:
        async with self._uow() as uow:
            entry = await self._own_entry(uow.session, actor, public_id)
            return entry.day if entry else None

    async def move(self, actor: Actor, public_id: str, day: date) -> None:
        async with self._uow() as uow:
            entry = await self._own_entry(uow.session, actor, public_id)
            if entry is not None:
                entry.day = day


def _f(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


__all__ = ["DayHabit", "HabitView", "Habits", "MarkResult"]
