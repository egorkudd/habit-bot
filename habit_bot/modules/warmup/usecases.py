"""Зарядка (раздел 3.3, 4.5): набор и шаги, зарядки, «как в прошлый раз», номер в дне, личные цели. Без aiogram."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_bot.kernel.clock import Clock
from habit_bot.kernel.db import UowFactory
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.idempotency import IdempotencyStore
from habit_bot.kernel.identity import Actor
from habit_bot.modules.users.public import Profiles
from habit_bot.modules.warmup.domain.warmup import (
    DEFAULT_SET,
    DEFAULT_STEP,
    PACE_DAYS,
    Measure,
    format_value,
    goal_progress,
    next_number,
    progress_line,
)
from habit_bot.modules.warmup.models import WarmupGoal, WarmupItem, WarmupSession, WarmupSettings, WarmupTemplate

log = logging.getLogger(__name__)
DEFAULT_DAILY_GOAL = 2
SHORT_MAX = 24


@dataclass(frozen=True, slots=True)
class ExerciseView:
    public_id: str
    name: str
    short: str
    measure: Measure
    step: int
    active: bool


@dataclass(frozen=True, slots=True)
class SessionItem:
    name: str
    measure: Measure
    value: int
    template_id: str | None


@dataclass(frozen=True, slots=True)
class SessionView:
    public_id: str
    day: date
    number: int
    items: tuple[SessionItem, ...]

    def summary(self) -> str:
        return " · ".join(f"{i.name} {format_value(i.measure, i.value)}" for i in self.items)


@dataclass(frozen=True, slots=True)
class GoalView:
    public_id: str
    exercise: ExerciseView
    target: int
    target_date: date


def _uuid(public_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(hex=public_id)
    except (ValueError, TypeError):
        return None


def exercise_view(t: WarmupTemplate) -> ExerciseView:
    return ExerciseView(t.public_id.hex, t.name, t.short, Measure(t.measure), t.step, t.active)


class Warmup:
    def __init__(self, *, uow: UowFactory, clock: Clock, idempotency: IdempotencyStore, profiles: Profiles) -> None:
        self._uow = uow
        self._clock = clock
        self._idempotency = idempotency
        self._profiles = profiles

    # --- набор ---
    async def templates(self, actor: Actor, *, include_inactive: bool = False) -> list[ExerciseView]:
        async with self._uow() as uow:
            return [exercise_view(t) for t in await self._templates(uow.session, actor, include_inactive)]

    @staticmethod
    async def _templates(session: AsyncSession, actor: Actor, include_inactive: bool = False) -> list[WarmupTemplate]:
        query = select(WarmupTemplate).where(WarmupTemplate.user_id == actor.user_id)
        if not include_inactive:
            query = query.where(WarmupTemplate.active.is_(True))
        return list((await session.execute(query.order_by(WarmupTemplate.position, WarmupTemplate.id)))
                    .scalars().all())

    async def ensure_set(self, actor: Actor) -> bool:
        """«Зарядка по умолчанию» из анкеты — набор при первом открытии. Возвращает, есть ли упражнения."""
        if await self.templates(actor):
            return True
        if await self._profiles.consume_starter(actor, "warmup"):
            await self.use_default_set(actor)
            return True
        return False

    async def use_default_set(self, actor: Actor) -> list[ExerciseView]:
        """Набор по умолчанию (раздел 3.3): отжимания, ягодичный мостик, планка, спина."""
        async with self._uow() as uow:
            existing = {t.name.casefold() for t in await self._templates(uow.session, actor, True)}
            position = len(existing)
            for exercise in DEFAULT_SET:
                if exercise.name.casefold() in existing:
                    continue
                position += 1
                uow.session.add(WarmupTemplate(
                    user_id=actor.user_id, name=exercise.name, short=exercise.short, measure=exercise.measure.value,
                    step=DEFAULT_STEP[exercise.measure], position=position, active=True,
                ))
        return await self.templates(actor)

    async def add_exercise(self, actor: Actor, *, name: str, measure: Measure) -> ExerciseView:
        clean = " ".join(name.split())
        if not 1 <= len(clean) <= 64:
            raise AppError("INPUT-TEXT", field="Название", low=1, high=64, length=len(clean))
        async with self._uow() as uow:
            templates = await self._templates(uow.session, actor, True)
            same = next((t for t in templates if t.name.casefold() == clean.casefold()), None)
            if same is not None and same.active:
                raise AppError("INPUT-DUPLICATE", name=clean)
            position = max((t.position for t in templates), default=0) + 1
            if same is not None:  # было убрано из набора — возвращается
                same.active, same.position = True, position
                return exercise_view(same)
            template = WarmupTemplate(
                user_id=actor.user_id, name=clean, short=clean[:SHORT_MAX], measure=measure.value,
                step=DEFAULT_STEP[measure], position=position, active=True,
            )
            uow.session.add(template)
            await uow.session.flush()
            return exercise_view(template)

    async def _template(self, session: AsyncSession, actor: Actor, public_id: str) -> WarmupTemplate:
        public = _uuid(public_id)
        found = (await session.execute(
            select(WarmupTemplate).where(WarmupTemplate.public_id == public, WarmupTemplate.user_id == actor.user_id)
        )).scalar_one_or_none() if public else None
        if found is None:
            raise AppError("UI-STALE")
        return found

    async def remove_exercise(self, actor: Actor, public_id: str) -> ExerciseView:
        """Убрать из набора: прошлые зарядки сохраняются, вернуть можно, добавив то же название."""
        async with self._uow() as uow:
            template = await self._template(uow.session, actor, public_id)
            template.active = False
            return exercise_view(template)

    async def move_up(self, actor: Actor, public_id: str) -> None:
        async with self._uow() as uow:
            templates = await self._templates(uow.session, actor)
            index = next((i for i, t in enumerate(templates) if t.public_id.hex == public_id), None)
            if index is None:
                raise AppError("UI-STALE")
            if index > 0:
                templates[index - 1], templates[index] = templates[index], templates[index - 1]
            for position, template in enumerate(templates, start=1):
                template.position = position

    async def set_step(self, actor: Actor, public_id: str, step: int) -> ExerciseView:
        async with self._uow() as uow:
            template = await self._template(uow.session, actor, public_id)
            template.step = step
            return exercise_view(template)

    # --- зарядки ---
    async def _last_session(self, session: AsyncSession, actor: Actor, day: date) -> WarmupSession | None:
        return (await session.execute(
            select(WarmupSession).where(
                WarmupSession.user_id == actor.user_id, WarmupSession.deleted_at.is_(None), WarmupSession.day <= day,
            ).order_by(WarmupSession.day.desc(), WarmupSession.number.desc(), WarmupSession.id.desc()).limit(1)
        )).scalar_one_or_none()

    async def last_values(self, actor: Actor, day: date) -> dict[str, int] | None:
        """«Как в прошлый раз»: последняя зарядка до даты записи (в «Другом дне» — до выбранной даты)."""
        async with self._uow() as uow:
            last = await self._last_session(uow.session, actor, day)
            if last is None:
                return None
            view = await self._view(uow.session, last)
            return {i.template_id: i.value for i in view.items if i.template_id}

    async def next_number(self, actor: Actor, day: date) -> int:
        async with self._uow() as uow:
            return await self._next_number(uow.session, actor, day)

    @staticmethod
    async def _next_number(session: AsyncSession, actor: Actor, day: date) -> int:
        numbers = (await session.execute(
            select(WarmupSession.number).where(
                WarmupSession.user_id == actor.user_id, WarmupSession.day == day, WarmupSession.deleted_at.is_(None),
            )
        )).scalars().all()
        return next_number(numbers)

    async def record(
        self, actor: Actor, values: dict[str, int], *, day: date, request_id: str | None = None,
    ) -> SessionView:
        """Записать зарядку: значения по упражнениям набора; номер в дне ставится автоматически."""

        async def action(session: AsyncSession) -> dict[str, Any]:
            templates = {t.public_id.hex: t for t in await self._templates(session, actor)}
            chosen = [(templates[k], v) for k, v in values.items() if k in templates]
            if not chosen:
                raise AppError("UI-STALE")
            chosen.sort(key=lambda pair: pair[0].position)
            record = WarmupSession(user_id=actor.user_id, day=day, number=await self._next_number(session, actor, day),
                                   logged_at=self._clock.now())
            session.add(record)
            await session.flush()
            for template, value in chosen:
                session.add(WarmupItem(user_id=actor.user_id, session_id=record.id, template_id=template.id,
                                       name=template.short, measure=template.measure, value=max(0, int(value))))
            await session.flush()
            return {"session": record.public_id.hex}

        async with self._uow() as uow:
            if request_id is None:
                result = await action(uow.session)
            else:
                result = await self._idempotency.run_once(
                    uow.session, user_id=actor.user_id, request_id=request_id, now=self._clock.now(),
                    action=lambda: action(uow.session),
                )
        view = await self.session(actor, result["session"])
        assert view is not None
        return view

    async def _view(self, session: AsyncSession, record: WarmupSession) -> SessionView:
        rows = (await session.execute(
            select(WarmupItem, WarmupTemplate.public_id)
            .outerjoin(WarmupTemplate, WarmupTemplate.id == WarmupItem.template_id)
            .where(WarmupItem.session_id == record.id).order_by(WarmupItem.id)
        )).all()
        items = tuple(SessionItem(i.name, Measure(i.measure), i.value, pid.hex if pid else None) for i, pid in rows)
        return SessionView(record.public_id.hex, record.day, record.number, items)

    async def _own_session(self, session: AsyncSession, actor: Actor, public_id: str) -> WarmupSession | None:
        public = _uuid(public_id)
        if public is None:
            return None
        return (await session.execute(
            select(WarmupSession).where(WarmupSession.public_id == public, WarmupSession.user_id == actor.user_id,
                                        WarmupSession.deleted_at.is_(None))
        )).scalar_one_or_none()

    async def session(self, actor: Actor, public_id: str) -> SessionView | None:
        async with self._uow() as uow:
            found = await self._own_session(uow.session, actor, public_id)
            return await self._view(uow.session, found) if found else None

    async def sessions(self, actor: Actor, day: date) -> list[SessionView]:
        async with self._uow() as uow:
            rows = (await uow.session.execute(
                select(WarmupSession).where(WarmupSession.user_id == actor.user_id, WarmupSession.day == day,
                                            WarmupSession.deleted_at.is_(None)).order_by(WarmupSession.number)
            )).scalars().all()
            return [await self._view(uow.session, r) for r in rows]

    async def sessions_between(self, actor: Actor, start: date, end: date) -> list[SessionView]:
        """Зарядки за период по дням и номерам — для итогов и экспорта."""
        async with self._uow() as uow:
            rows = (await uow.session.execute(
                select(WarmupSession).where(WarmupSession.user_id == actor.user_id, WarmupSession.day >= start,
                                            WarmupSession.day <= end, WarmupSession.deleted_at.is_(None))
                .order_by(WarmupSession.day, WarmupSession.number)
            )).scalars().all()
            return [await self._view(uow.session, r) for r in rows]

    async def set_value(self, actor: Actor, session_public_id: str, name: str, value: int) -> int | None:
        """Исправить значение упражнения в записанной зарядке («планка во 2-й зарядке 6:15, а не 6:00»).
        Возвращает прежнее значение; ``None`` — такого упражнения в зарядке нет."""
        async with self._uow() as uow:
            found = await self._own_session(uow.session, actor, session_public_id)
            if found is None:
                return None
            items = (await uow.session.execute(select(WarmupItem).where(WarmupItem.session_id == found.id)))
            item = next((i for i in items.scalars().all() if i.name.casefold() == name.casefold()), None)
            if item is None:
                return None
            old, item.value = item.value, max(0, int(value))
            return old

    async def delete_session(self, actor: Actor, public_id: str) -> SessionView | None:
        async with self._uow() as uow:
            found = await self._own_session(uow.session, actor, public_id)
            if found is None:
                return None
            found.deleted_at = self._clock.now()
            return await self._view(uow.session, found)

    # --- перенос (раздел 3.7) ---
    async def day_of(self, actor: Actor, public_id: str) -> date | None:
        found = await self.session(actor, public_id)
        return found.day if found else None

    async def move(self, actor: Actor, public_id: str, day: date) -> None:
        """Перенос на другой день: номер — следующий в том дне."""
        async with self._uow() as uow:
            found = await self._own_session(uow.session, actor, public_id)
            if found is not None:
                found.number = await self._next_number(uow.session, actor, day)
                found.day = day

    # --- цель «зарядок в день» ---
    async def daily_goal(self, actor: Actor) -> int:
        async with self._uow() as uow:
            value = (await uow.session.execute(
                select(WarmupSettings.daily_goal).where(WarmupSettings.user_id == actor.user_id)
            )).scalar_one_or_none()
            return DEFAULT_DAILY_GOAL if value is None else int(value)

    async def set_daily_goal(self, actor: Actor, goal: int) -> None:
        async with self._uow() as uow:
            row = (await uow.session.execute(
                select(WarmupSettings).where(WarmupSettings.user_id == actor.user_id)
            )).scalar_one_or_none()
            if row is None:
                uow.session.add(WarmupSettings(user_id=actor.user_id, daily_goal=goal))
            else:
                row.daily_goal = goal

    # --- личные цели (раздел 3.3, 4.5) ---
    async def _best(self, session: AsyncSession, actor: Actor, template_id: int, until: date) -> int:
        value = (await session.execute(
            select(func.max(WarmupItem.value)).join(WarmupSession, WarmupSession.id == WarmupItem.session_id).where(
                WarmupItem.user_id == actor.user_id, WarmupItem.template_id == template_id,
                WarmupSession.deleted_at.is_(None), WarmupSession.day <= until,
            )
        )).scalar_one_or_none()
        return int(value or 0)

    async def set_goal(self, actor: Actor, template_public_id: str, *, target: int, target_date: date) -> GoalView:
        today = self._profiles.today()
        if target_date <= today:
            raise AppError("INPUT-DATE", value=f"{target_date:%d.%m.%Y}")
        async with self._uow() as uow:
            template = await self._template(uow.session, actor, template_public_id)
            for old in (await uow.session.execute(
                select(WarmupGoal).where(WarmupGoal.user_id == actor.user_id, WarmupGoal.template_id == template.id,
                                         WarmupGoal.active.is_(True))
            )).scalars().all():
                old.active = False
            goal = WarmupGoal(
                user_id=actor.user_id, template_id=template.id, target=target, target_date=target_date,
                start_value=await self._best(uow.session, actor, template.id, today), set_on=today, active=True,
            )
            uow.session.add(goal)
            await uow.session.flush()
            return GoalView(goal.public_id.hex, exercise_view(template), target, target_date)

    async def goals(self, actor: Actor) -> list[GoalView]:
        async with self._uow() as uow:
            rows = (await uow.session.execute(
                select(WarmupGoal, WarmupTemplate).join(WarmupTemplate, WarmupTemplate.id == WarmupGoal.template_id)
                .where(WarmupGoal.user_id == actor.user_id, WarmupGoal.active.is_(True))
                .order_by(WarmupTemplate.position)
            )).all()
            return [GoalView(g.public_id.hex, exercise_view(t), g.target, g.target_date) for g, t in rows]

    async def remove_goal(self, actor: Actor, public_id: str) -> None:
        public = _uuid(public_id)
        async with self._uow() as uow:
            goal = (await uow.session.execute(
                select(WarmupGoal).where(WarmupGoal.public_id == public, WarmupGoal.user_id == actor.user_id)
            )).scalar_one_or_none() if public else None
            if goal is None:
                raise AppError("UI-STALE")
            goal.active = False

    async def progress_lines(self, actor: Actor, today: date, only: set[str] | None = None) -> list[str]:
        """Строки прогресса личных целей; ``only`` — упражнения только что записанной зарядки."""
        lines = []
        async with self._uow() as uow:
            rows = (await uow.session.execute(
                select(WarmupGoal, WarmupTemplate).join(WarmupTemplate, WarmupTemplate.id == WarmupGoal.template_id)
                .where(WarmupGoal.user_id == actor.user_id, WarmupGoal.active.is_(True))
                .order_by(WarmupTemplate.position)
            )).all()
            for goal, template in rows:
                if only is not None and template.public_id.hex not in only:
                    continue
                progress = goal_progress(
                    target=goal.target, target_date=goal.target_date, start_value=goal.start_value,
                    set_on=goal.set_on, today=today,
                    best=await self._best(uow.session, actor, template.id, today),
                    best_before_window=await self._best(uow.session, actor, template.id,
                                                        today - timedelta(days=PACE_DAYS)),
                )
                lines.append(progress_line(template.short, Measure(template.measure), progress, goal.target_date))
        return lines
