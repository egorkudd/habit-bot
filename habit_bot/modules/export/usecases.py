"""Экспорт своих данных в CSV (раздел 3.12): только свои записи за период, без имени и Telegram-ID; файлы
собираются в памяти и сразу уходят в чат — на диске ничего не остаётся. Без aiogram."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, timedelta, tzinfo
from decimal import Decimal
from typing import Any

from habit_bot.kernel.clock import Clock
from habit_bot.kernel.domain.parsing import logical_day
from habit_bot.kernel.identity import Actor
from habit_bot.modules.export.domain import tables as t
from habit_bot.modules.export.domain.csv_format import README, Cell, TableSpec, readme, to_csv
from habit_bot.modules.runs.domain.runs import speed

ALL_TIME_START = date(2020, 1, 1)
ZIP_NAME = "habit-bot-export.zip"


@dataclass
class Sources:
    profiles: Any
    days: Any
    food: Any = None
    warmup: Any = None
    habits: Any = None
    workouts: Any = None
    runs: Any = None


@dataclass(frozen=True, slots=True)
class ExportFile:
    filename: str
    data: bytes


class Export:
    def __init__(self, *, clock: Clock, tz: tzinfo, sources: Sources) -> None:
        self._clock = clock
        self._tz = tz
        self.s = sources

    def today(self) -> date:
        return logical_day(self._clock.now(), self._tz)

    def available(self) -> list[TableSpec]:
        """Таблицы включённых разделов; итоги, вес, цели и профиль есть всегда."""
        s = self.s
        skip = {t.FOOD.key: s.food, t.WARMUPS.key: s.warmup, t.WORKOUTS.key: s.workouts, t.RUNS.key: s.runs,
                t.HABITS.key: s.habits}
        return [spec for spec in t.TABLES if skip.get(spec.key, True) is not None]

    def _local(self, moment: Any) -> Any:
        return moment.astimezone(self._tz) if moment is not None else None

    async def build(self, actor: Actor, start: date, end: date, keys: Collection[str]) -> list[ExportFile]:
        """Выбранные таблицы и README.csv со словарём их колонок."""
        chosen = [spec for spec in self.available() if spec.key in keys]
        files = [ExportFile(spec.filename, to_csv(spec, await self._rows(actor, spec, start, end))) for spec in chosen]
        if files:
            files.append(ExportFile(README.filename, readme(chosen)))
        return files

    @staticmethod
    def archive(files: Sequence[ExportFile]) -> ExportFile:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            for f in files:
                zipped.writestr(f.filename, f.data)
        return ExportFile(ZIP_NAME, buffer.getvalue())

    async def _rows(self, actor: Actor, spec: TableSpec, start: date, end: date) -> list[Sequence[Cell]]:
        s = self.s
        if spec is t.FOOD:
            return [(e.day, self._local(e.logged_at), e.name, e.quantity, e.unit, e.nutrients.kcal,
                     e.nutrients.protein, e.nutrients.fat, e.nutrients.carbs, e.price, e.source)
                    for e in await s.food.entries_between(actor, start, end)]
        if spec is t.WARMUPS:
            return [(x.day, x.number, i.name, i.value, i.measure)
                    for x in await s.warmup.sessions_between(actor, start, end) for i in x.items]
        if spec is t.WORKOUTS:
            rows: list[Sequence[Cell]] = []
            for session in await s.workouts.sessions_between(actor, start, end):
                for block in session.blocks:
                    for number, x in enumerate(block.sets, 1):  # «4×8» — четыре строки
                        rows.append((session.day, session.kind, block.name, number, x.weight, x.band, x.reps,
                                     x.seconds, None, session.duration_min))
            return rows
        if spec is t.RUNS:
            runs = await s.runs.entries_between(actor, start, end)
            return [(day, self._local(at), run.distance_km, run.seconds, run.pace, speed(run.distance_km, run.seconds))
                    for day, at, run in runs]
        if spec is t.HABITS:
            return [(day, self._local(at), h.name, h.measure, value, h.unit, h.goal, h.period.value)
                    for day, at, h, value in await s.habits.entries_between(actor, start, end)]
        if spec is t.BODY:
            weights = await s.profiles.weights_between(actor, start, end)
            return [(day, weights[day]) for day in sorted(weights)]
        if spec is t.GOALS:
            return [(g.start_date, g.mode, g.kcal, g.protein, g.fat, g.carbs, g.target_weight, g.source)
                    for g in reversed(await s.profiles.goals(actor))]
        if spec is t.PROFILE:
            p = await s.profiles.profile(actor)
            if p is None:
                return []
            return [(p.sex, p.age, p.height_cm, p.weight_kg, p.activity, p.mode, p.target_weight, p.experience,
                     p.city.name if p.city else None)]
        return await self._daily(actor, start, end)

    async def _daily(self, actor: Actor, start: date, end: date) -> list[Sequence[Cell]]:
        """Итоги по дням: строки только за дни, где что-то записано или отмечен выходной."""
        s = self.s
        totals = await s.food.daily_totals(actor, start, end) if s.food else {}
        warmups: dict[date, int] = {}
        warmup_goal = None
        if s.warmup is not None:
            for x in await s.warmup.sessions_between(actor, start, end):
                warmups[x.day] = warmups.get(x.day, 0) + 1
            warmup_goal = await s.warmup.daily_goal(actor)
        workouts: dict[date, int] = {}
        if s.workouts is not None:
            for session in await s.workouts.sessions_between(actor, start, end):
                workouts[session.day] = workouts.get(session.day, 0) + 1
        run_km: dict[date, Decimal] = {}
        if s.runs is not None:
            for day, _, run in await s.runs.entries_between(actor, start, end):
                run_km[day] = run_km.get(day, Decimal(0)) + run.distance_km
        weights = await s.profiles.weights_between(actor, start, end)
        off = await s.days.days_off(actor, start, end)
        goals = await s.profiles.goals(actor)
        rows: list[Sequence[Cell]] = []
        for day in sorted(set(totals) | set(warmups) | set(workouts) | set(run_km) | set(weights) | off):
            goal = next((g for g in goals if g.start_date <= day), goals[-1] if goals else None)
            food = totals.get(day)
            fact = food.fact if food else None
            rows.append((
                day, "day_off" if day in off else "normal",
                fact.kcal if fact else None, fact.protein if fact else None, fact.fat if fact else None,
                fact.carbs if fact else None,
                goal.kcal if goal else None, goal.protein if goal else None, goal.fat if goal else None,
                goal.carbs if goal else None,
                goal.kcal - fact.kcal if goal and fact else None,
                food.cost if food else None,
                warmups.get(day, 0) if s.warmup else None, warmup_goal,
                workouts.get(day, 0) if s.workouts else None,
                run_km.get(day, Decimal(0)) if s.runs else None,
                weights.get(day),
            ))
        return rows

    def period(self, kind: str) -> tuple[date, date]:
        """«Неделя» — последние 7 дней, «Месяц» — 30, «3 месяца» — 90, «Всё время»."""
        today = self.today()
        days = {"w": 7, "m": 30, "q": 90}
        if kind in days:
            return today - timedelta(days=days[kind] - 1), today
        return ALL_TIME_START, today
