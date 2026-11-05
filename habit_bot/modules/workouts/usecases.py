"""Тренировки (раздел 3.4.0): база упражнений, тренировка зал / площадка / свободная, подходы, «как в прошлый
раз», тоннаж, завершение и автозавершение через 3 часа, цель «тренировок в неделю». Без aiogram."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_bot.kernel.clock import Clock
from habit_bot.kernel.db import UowFactory
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.idempotency import IdempotencyStore
from habit_bot.kernel.identity import Actor
from habit_bot.modules.users.public import Profiles
from habit_bot.modules.workouts.catalog import EXERCISES
from habit_bot.modules.workouts.domain.training import (
    Band,
    Difficulty,
    Equipment,
    ExerciseSpec,
    Filters,
    Group,
    Kind,
    Measure,
    Movement,
    Muscle,
    Place,
    SetValue,
    Suggest,
    offered,
    tonnage,
    week_start,
)
from habit_bot.modules.workouts.models import Exercise, WorkoutSession, WorkoutSet, WorkoutSettings

log = logging.getLogger(__name__)
OPEN, DONE = "open", "done"
AUTO_FINISH_AFTER = timedelta(hours=3)  # раздел 3: идущая тренировка живёт 3 часа без действий
DEFAULT_WEEKLY_GOAL = 3
RECENT_LIMIT = 10


@dataclass(frozen=True, slots=True)
class ExerciseView:
    public_id: str
    name: str
    spec: ExerciseSpec
    own: bool


@dataclass(frozen=True, slots=True)
class Block:
    """Упражнение в тренировке с его подходами."""

    exercise_id: str | None
    name: str
    measure: Measure
    per_dumbbell: bool
    sets: tuple[SetValue, ...]

    @property
    def tonnage(self) -> Decimal:
        return tonnage(self.sets, self.per_dumbbell)


@dataclass(frozen=True, slots=True)
class SessionView:
    public_id: str
    day: date
    kind: Kind
    open: bool
    started_at: datetime
    duration_min: int | None
    band: bool | None
    missing: frozenset[Equipment]
    blocks: tuple[Block, ...]
    auto_finished: bool

    @property
    def tonnage(self) -> Decimal:
        return sum((b.tonnage for b in self.blocks), Decimal(0))

    @property
    def sets_count(self) -> int:
        return sum(len(b.sets) for b in self.blocks)


@dataclass(frozen=True, slots=True)
class SettingsView:
    weekly_goal: int
    bands: tuple[Band, ...]
    show_all: bool
    band_last: bool
    extra: dict[str, Any] = field(default_factory=dict)


def _uuid(public_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(hex=public_id)
    except (ValueError, TypeError):
        return None


def _f(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def spec_of(e: Exercise) -> ExerciseSpec:
    return ExerciseSpec(
        key=e.catalog_key or e.public_id.hex, name=e.name, place=Place(e.place), equipment=Equipment(e.equipment),
        group=Group(e.group), primary=Muscle(e.primary), secondary=tuple(Muscle(m) for m in e.secondary or []),
        movement=Movement(e.movement), compound=e.compound, difficulty=Difficulty(e.difficulty),
        measure=Measure(e.measure), floor=e.floor, suggest=Suggest(e.suggest), loaded=e.loaded,
        easier=e.easier_key, harder=e.harder_key,
        weight_step=Decimal(str(e.weight_step)) if e.weight_step is not None else None,
        reps_low=e.reps_low, reps_high=e.reps_high, per_dumbbell=e.per_dumbbell,
    )


def exercise_view(e: Exercise) -> ExerciseView:
    return ExerciseView(e.public_id.hex, e.name, spec_of(e), e.user_id is not None)


def set_value(s: WorkoutSet) -> SetValue:
    return SetValue(reps=s.reps, seconds=s.seconds,
                    weight=Decimal(str(s.weight)) if s.weight is not None else None,
                    band=Band(s.band) if s.band else None)


def _fill(row: Exercise, spec: ExerciseSpec) -> None:
    row.name, row.place, row.equipment, row.group = spec.name, spec.place.value, spec.equipment.value, spec.group.value
    row.primary, row.movement = spec.primary.value, spec.movement.value
    row.secondary = [m.value for m in spec.secondary]
    row.compound, row.difficulty, row.measure = spec.compound, spec.difficulty.value, spec.measure.value
    row.floor, row.suggest, row.loaded = spec.floor, spec.suggest.value, spec.loaded
    row.easier_key, row.harder_key, row.weight_step = spec.easier, spec.harder, _f(spec.weight_step)
    row.reps_low, row.reps_high, row.per_dumbbell, row.active = spec.reps_low, spec.reps_high, spec.per_dumbbell, True


class Workouts:
    def __init__(self, *, uow: UowFactory, clock: Clock, idempotency: IdempotencyStore, profiles: Profiles) -> None:
        self._uow = uow
        self._clock = clock
        self._idempotency = idempotency
        self._profiles = profiles

    # --- база упражнений ---
    async def seed_catalog(self) -> int:
        """Загружает базу (раздел 3.4.1); повторный запуск только обновляет поля."""
        changed = 0
        async with self._uow() as uow:
            existing = {e.catalog_key: e for e in (await uow.session.execute(
                select(Exercise).where(Exercise.catalog_key.is_not(None)))).scalars().all()}
            for spec in EXERCISES:
                row = existing.get(spec.key)
                if row is not None and spec_of(row) == spec and row.active:
                    continue
                row = row or Exercise(catalog_key=spec.key)
                _fill(row, spec)
                uow.session.add(row)
                changed += 1
        return changed

    async def filters(self, actor: Actor, kind: Kind, *, band: bool = True,
                      missing: Sequence[Equipment] = ()) -> Filters:
        profile = await self._profiles.profile(actor)
        sex = {"male": "m", "female": "f"}.get(profile.sex.value) if profile else None
        settings = await self.settings(actor)
        return Filters(kind=kind, band=band, missing=frozenset(missing), sex=sex, show_all=settings.show_all)

    async def session_filters(self, actor: Actor, session: SessionView) -> Filters:
        return await self.filters(actor, session.kind, band=session.band is not False, missing=tuple(session.missing))

    async def exercises(self, actor: Actor, filters: Filters, group: Group | None = None) -> list[ExerciseView]:
        """Упражнения базы и свои, которые подходят этой тренировке, по названию."""
        async with self._uow() as uow:
            rows = (await uow.session.execute(select(Exercise).where(
                Exercise.active.is_(True), or_(Exercise.user_id.is_(None), Exercise.user_id == actor.user_id))
                .order_by(Exercise.name))).scalars().all()
        found = [exercise_view(r) for r in rows]
        return [e for e in found if (e.own or offered(e.spec, filters)) and (group is None or e.spec.group is group)]

    async def groups(self, actor: Actor, filters: Filters) -> list[tuple[Group, int]]:
        counts: dict[Group, int] = {}
        for e in await self.exercises(actor, filters):
            counts[e.spec.group] = counts.get(e.spec.group, 0) + 1
        return [(g, counts[g]) for g in Group if g in counts]

    async def recent(self, actor: Actor, filters: Filters, limit: int = RECENT_LIMIT) -> list[ExerciseView]:
        """10 последних упражнений этого типа тренировки, новые сверху."""
        async with self._uow() as uow:
            rows = (await uow.session.execute(
                select(WorkoutSet.exercise_id, func.max(WorkoutSet.id).label("last"))
                .join(WorkoutSession, WorkoutSession.id == WorkoutSet.session_id)
                .where(WorkoutSet.user_id == actor.user_id, WorkoutSet.deleted_at.is_(None),
                       WorkoutSession.deleted_at.is_(None), WorkoutSession.kind == filters.kind.value,
                       WorkoutSet.exercise_id.is_not(None))
                .group_by(WorkoutSet.exercise_id).order_by(func.max(WorkoutSet.id).desc()).limit(limit * 2)
            )).all()
            ids = [r[0] for r in rows]
            found = {e.id: e for e in (await uow.session.execute(
                select(Exercise).where(Exercise.id.in_(ids)))).scalars().all()} if ids else {}
        views = [exercise_view(found[i]) for i in ids if i in found and found[i].active]
        return [e for e in views if e.own or offered(e.spec, filters)][:limit]

    async def _own_exercise(self, session: AsyncSession, actor: Actor, public_id: str) -> Exercise | None:
        public = _uuid(public_id)
        if public is None:
            return None
        return (await session.execute(select(Exercise).where(
            Exercise.public_id == public, or_(Exercise.user_id.is_(None), Exercise.user_id == actor.user_id))
        )).scalar_one_or_none()

    async def exercise(self, actor: Actor, public_id: str) -> ExerciseView | None:
        async with self._uow() as uow:
            row = await self._own_exercise(uow.session, actor, public_id)
            return exercise_view(row) if row else None

    async def create_exercise(self, actor: Actor, *, name: str, measure: Measure, kind: Kind) -> ExerciseView:
        """«Новое упражнение»: своё, видно только пользователю; место — по типу тренировки."""
        clean = " ".join(name.split())
        if not 1 <= len(clean) <= 64:
            raise AppError("INPUT-TEXT", field="Название", low=1, high=64, length=len(clean))
        async with self._uow() as uow:
            mine = (await uow.session.execute(select(Exercise.name).where(
                Exercise.user_id == actor.user_id, Exercise.active.is_(True)))).scalars().all()
            if any(n.casefold() == clean.casefold() for n in mine):
                raise AppError("INPUT-EXERCISE-DUPLICATE", name=clean)
            place = {Kind.GYM: Place.GYM, Kind.OUTDOOR: Place.OUTDOOR}.get(kind, Place.ANY)
            spec = ExerciseSpec(
                key="", name=clean, place=place, equipment=Equipment.NONE, group=Group.STANDING
                if kind is Kind.OUTDOOR else Group.LEGS, primary=Muscle.CORE, secondary=(),
                movement=Movement.ISOLATION, compound=False, difficulty=Difficulty.BEGINNER, measure=measure,
                weight_step=Decimal("2.5") if measure is Measure.WEIGHT_REPS else None)
            row = Exercise(user_id=actor.user_id)
            _fill(row, spec)
            uow.session.add(row)
            await uow.session.flush()
            return exercise_view(row)

    # --- настройки ---
    async def _settings_row(self, session: AsyncSession, actor: Actor) -> WorkoutSettings:
        row = (await session.execute(select(WorkoutSettings).where(
            WorkoutSettings.user_id == actor.user_id))).scalar_one_or_none()
        if row is None:
            row = WorkoutSettings(user_id=actor.user_id, weekly_goal=DEFAULT_WEEKLY_GOAL, bands=[], show_all=False,
                                  band_last=True)
            session.add(row)
        return row

    async def settings(self, actor: Actor) -> SettingsView:
        async with self._uow() as uow:
            row = (await uow.session.execute(select(WorkoutSettings).where(
                WorkoutSettings.user_id == actor.user_id))).scalar_one_or_none()
            if row is None:
                return SettingsView(DEFAULT_WEEKLY_GOAL, (), False, True)
            return SettingsView(row.weekly_goal, tuple(Band(b) for b in row.bands), row.show_all, row.band_last)

    async def update_settings(
        self, actor: Actor, *, weekly_goal: int | None = None, bands: Sequence[Band] | None = None,
        show_all: bool | None = None, band_last: bool | None = None,
    ) -> SettingsView:
        async with self._uow() as uow:
            row = await self._settings_row(uow.session, actor)
            if weekly_goal is not None:
                row.weekly_goal = weekly_goal
            if bands is not None:
                row.bands = [b.value for b in Band if b in set(bands)]
            if show_all is not None:
                row.show_all = show_all
            if band_last is not None:
                row.band_last = band_last
        return await self.settings(actor)

    # --- тренировка ---
    async def _view(self, session: AsyncSession, row: WorkoutSession) -> SessionView:
        sets = (await session.execute(select(WorkoutSet, Exercise.public_id).outerjoin(
            Exercise, Exercise.id == WorkoutSet.exercise_id).where(
            WorkoutSet.session_id == row.id, WorkoutSet.deleted_at.is_(None)).order_by(WorkoutSet.id))).all()
        blocks: list[Block] = []
        for s, exercise_public in sets:
            key = exercise_public.hex if exercise_public else None
            if blocks and blocks[-1].exercise_id == key and blocks[-1].name == s.name:
                last = blocks.pop()
                blocks.append(Block(key, s.name, last.measure, last.per_dumbbell, (*last.sets, set_value(s))))
            else:
                blocks.append(Block(key, s.name, Measure(s.measure), s.per_dumbbell, (set_value(s),)))
        return SessionView(row.public_id.hex, row.day, Kind(row.kind), row.status == OPEN, row.started_at,
                           row.duration_min, row.band, frozenset(Equipment(m) for m in row.missing or []),
                           tuple(blocks), row.auto_finished)

    async def _own_session(self, session: AsyncSession, actor: Actor, public_id: str) -> WorkoutSession | None:
        public = _uuid(public_id)
        if public is None:
            return None
        return (await session.execute(select(WorkoutSession).where(
            WorkoutSession.public_id == public, WorkoutSession.user_id == actor.user_id,
            WorkoutSession.deleted_at.is_(None)))).scalar_one_or_none()

    async def session(self, actor: Actor, public_id: str) -> SessionView | None:
        async with self._uow() as uow:
            row = await self._own_session(uow.session, actor, public_id)
            return await self._view(uow.session, row) if row else None

    async def open_session(self, actor: Actor) -> SessionView | None:
        """Идущая тренировка; просроченную (3 часа без действий) сначала завершает."""
        await self.auto_finish(self._clock.now(), actor.user_id)
        async with self._uow() as uow:
            row = (await uow.session.execute(select(WorkoutSession).where(
                WorkoutSession.user_id == actor.user_id, WorkoutSession.status == OPEN,
                WorkoutSession.deleted_at.is_(None)).order_by(WorkoutSession.id.desc()))).scalars().first()
            return await self._view(uow.session, row) if row else None

    async def start(self, actor: Actor, kind: Kind, *, day: date, band: bool | None = None,
                    missing: Sequence[Equipment] = ()) -> SessionView:
        current = await self.open_session(actor)
        if current is not None:
            return current
        now = self._clock.now()
        async with self._uow() as uow:
            row = WorkoutSession(user_id=actor.user_id, day=day, kind=kind.value, status=OPEN, started_at=now,
                                 last_action_at=now, band=band, missing=[m.value for m in missing], tonnage=0)
            uow.session.add(row)
            if band is not None:
                (await self._settings_row(uow.session, actor)).band_last = band
            await uow.session.flush()
            return await self._view(uow.session, row)

    async def touch(self, actor: Actor, public_id: str) -> None:
        """Любое действие в тренировке продлевает её ещё на 3 часа."""
        async with self._uow() as uow:
            row = await self._own_session(uow.session, actor, public_id)
            if row is not None and row.status == OPEN:
                row.last_action_at = self._clock.now()

    async def last_sets(self, actor: Actor, exercise_public_id: str, *,
                        before_session: str | None = None) -> tuple[date, tuple[SetValue, ...]] | None:
        """«Как в прошлый раз»: подходы упражнения из последней тренировки до текущей."""
        async with self._uow() as uow:
            exercise = await self._own_exercise(uow.session, actor, exercise_public_id)
            if exercise is None:
                return None
            query = (select(WorkoutSet, WorkoutSession).join(WorkoutSession, WorkoutSession.id == WorkoutSet.session_id)
                     .where(WorkoutSet.user_id == actor.user_id, WorkoutSet.exercise_id == exercise.id,
                            WorkoutSet.deleted_at.is_(None), WorkoutSession.deleted_at.is_(None)))
            current = _uuid(before_session or "")
            if current is not None:
                query = query.where(WorkoutSession.public_id != current)
            rows = (await uow.session.execute(query.order_by(WorkoutSet.id))).all()
        if not rows:
            return None
        last_session = rows[-1][1]
        return last_session.day, tuple(set_value(s) for s, ws in rows if ws.id == last_session.id)

    async def add_sets(self, actor: Actor, session_public_id: str, exercise_public_id: str,
                       sets: Sequence[SetValue], *, request_id: str | None = None) -> SessionView:
        """Подходы сохраняются сразу (раздел 3): даже если тренировку не завершить, они останутся."""

        async def action(session: AsyncSession) -> dict[str, Any]:
            row = await self._own_session(session, actor, session_public_id)
            exercise = await self._own_exercise(session, actor, exercise_public_id)
            if row is None or row.status != OPEN or exercise is None or not sets:
                raise AppError("UI-STALE")
            number = int((await session.execute(select(func.count(WorkoutSet.id)).where(
                WorkoutSet.session_id == row.id, WorkoutSet.exercise_id == exercise.id,
                WorkoutSet.deleted_at.is_(None)))).scalar_one())
            for i, value in enumerate(sets, start=number + 1):
                session.add(WorkoutSet(
                    user_id=actor.user_id, session_id=row.id, exercise_id=exercise.id, name=exercise.name,
                    measure=exercise.measure, per_dumbbell=exercise.per_dumbbell, number=i,
                    weight=_f(value.weight), reps=value.reps, seconds=value.seconds,
                    band=value.band.value if value.band else None))
            row.last_action_at = self._clock.now()
            await session.flush()
            row.tonnage = float((await self._view(session, row)).tonnage)
            return {"ok": True}

        async with self._uow() as uow:
            if request_id is None:
                await action(uow.session)
            else:
                await self._idempotency.run_once(uow.session, user_id=actor.user_id, request_id=request_id,
                                                 now=self._clock.now(), action=lambda: action(uow.session))
        found = await self.session(actor, session_public_id)
        assert found is not None
        return found

    async def undo_last(self, actor: Actor, session_public_id: str) -> SessionView | None:
        """Убрать подходы последнего записанного упражнения (ошибся при вводе)."""
        async with self._uow() as uow:
            row = await self._own_session(uow.session, actor, session_public_id)
            if row is None or row.status != OPEN:
                return None
            view = await self._view(uow.session, row)
            if not view.blocks:
                return view
            count = len(view.blocks[-1].sets)
            last = (await uow.session.execute(select(WorkoutSet).where(
                WorkoutSet.session_id == row.id, WorkoutSet.deleted_at.is_(None)).order_by(
                WorkoutSet.id.desc()).limit(count))).scalars().all()
            for s in last:
                s.deleted_at = self._clock.now()
            await uow.session.flush()
            view = await self._view(uow.session, row)
            row.tonnage = float(view.tonnage)
            return view

    def _close(self, row: WorkoutSession, view: SessionView, minutes: int | None, *, auto: bool) -> None:
        end = row.last_action_at if auto else self._clock.now()
        row.status = DONE
        row.finished_at = end
        elapsed = max(1, round((end - row.started_at).total_seconds() / 60))
        row.duration_min = minutes if minutes is not None else elapsed
        row.tonnage = float(view.tonnage)
        row.auto_finished = auto

    async def finish(self, actor: Actor, session_public_id: str, minutes: int | None) -> SessionView | None:
        """«Завершить» → длительность. Тренировка без подходов не сохраняется."""
        async with self._uow() as uow:
            row = await self._own_session(uow.session, actor, session_public_id)
            if row is None or row.status != OPEN:
                return None
            view = await self._view(uow.session, row)
            if not view.blocks:
                await uow.session.delete(row)
                return view
            self._close(row, view, minutes, auto=False)
            await uow.session.flush()
            return await self._view(uow.session, row)

    async def auto_finish(self, now: datetime, user_id: int | None = None) -> int:
        """Через 3 часа без действий тренировка завершается сама с тем, что успели записать (раздел 3)."""
        finished = 0
        async with self._uow() as uow:
            query = select(WorkoutSession).where(WorkoutSession.status == OPEN,
                                                 WorkoutSession.last_action_at <= now - AUTO_FINISH_AFTER)
            if user_id is not None:
                query = query.where(WorkoutSession.user_id == user_id)
            for row in (await uow.session.execute(query)).scalars().all():
                view = await self._view(uow.session, row)
                if view.blocks:
                    self._close(row, view, None, auto=True)
                else:
                    await uow.session.execute(delete(WorkoutSession).where(WorkoutSession.id == row.id))
                finished += 1
        if finished:
            log.info("Тренировки завершены автоматически: %s", finished)
        return finished

    async def log_sets(self, actor: Actor, day: date,
                       groups: Sequence[tuple[str, Sequence[SetValue]]]) -> SessionView:
        """Подходы командой текстом: отдельная «Свободная» тренировка за день, сразу завершённая."""
        now = self._clock.now()
        async with self._uow() as uow:
            row = WorkoutSession(user_id=actor.user_id, day=day, kind=Kind.FREE.value, status=OPEN, started_at=now,
                                 last_action_at=now, missing=[], tonnage=0)
            uow.session.add(row)
            await uow.session.flush()
            public_id = row.public_id.hex
        for exercise_id, sets in groups:
            await self.add_sets(actor, public_id, exercise_id, sets)
        async with self._uow() as uow:
            done = await self._own_session(uow.session, actor, public_id)
            assert done is not None
            view = await self._view(uow.session, done)
            self._close(done, view, None, auto=False)
            done.duration_min = None
            await uow.session.flush()
            return await self._view(uow.session, done)

    async def delete_session(self, actor: Actor, public_id: str) -> SessionView | None:
        async with self._uow() as uow:
            row = await self._own_session(uow.session, actor, public_id)
            if row is None:
                return None
            row.deleted_at = self._clock.now()
            return await self._view(uow.session, row)

    async def day_sessions(self, actor: Actor, day: date) -> list[SessionView]:
        async with self._uow() as uow:
            rows = (await uow.session.execute(select(WorkoutSession).where(
                WorkoutSession.user_id == actor.user_id, WorkoutSession.day == day, WorkoutSession.status == DONE,
                WorkoutSession.deleted_at.is_(None)).order_by(WorkoutSession.id))).scalars().all()
            return [await self._view(uow.session, r) for r in rows]

    async def sessions_between(self, actor: Actor, start: date, end: date) -> list[SessionView]:
        """Завершённые тренировки за период — для итогов (рекорды, сравнение) и экспорта."""
        async with self._uow() as uow:
            rows = (await uow.session.execute(select(WorkoutSession).where(
                WorkoutSession.user_id == actor.user_id, WorkoutSession.day >= start, WorkoutSession.day <= end,
                WorkoutSession.status == DONE, WorkoutSession.deleted_at.is_(None))
                .order_by(WorkoutSession.day, WorkoutSession.id))).scalars().all()
            return [await self._view(uow.session, r) for r in rows]

    async def count_between(self, actor: Actor, start: date, end: date) -> int:
        async with self._uow() as uow:
            return int((await uow.session.execute(select(func.count(WorkoutSession.id)).where(
                WorkoutSession.user_id == actor.user_id, WorkoutSession.status == DONE,
                WorkoutSession.deleted_at.is_(None), WorkoutSession.day >= start, WorkoutSession.day <= end)
            )).scalar_one())

    @staticmethod
    def week(day: date) -> tuple[date, date]:
        start = week_start(day)
        return start, start + timedelta(days=6)

    # --- перенос (раздел 3.7) ---
    async def day_of(self, actor: Actor, public_id: str) -> date | None:
        found = await self.session(actor, public_id)
        return found.day if found else None

    async def move(self, actor: Actor, public_id: str, day: date) -> None:
        async with self._uow() as uow:
            row = await self._own_session(uow.session, actor, public_id)
            if row is not None:
                row.day = day
