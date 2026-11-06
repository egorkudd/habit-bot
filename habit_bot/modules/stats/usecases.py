"""«📊 Итоги» (раздел 3.8): данные картинки дня по выбранной привычке и обзора-светофора за период.

Только чтение из модулей через их сценарии; ни одного запроса к ИИ (проверяется тестом). Без aiogram."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta, tzinfo
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from habit_bot.kernel.clock import Clock
from habit_bot.kernel.db import UowFactory
from habit_bot.kernel.domain.formatting import format_day, format_duration, format_number
from habit_bot.kernel.domain.parsing import logical_day
from habit_bot.kernel.identity import Actor
from habit_bot.modules.habits.domain.habits import format_value as habit_value
from habit_bot.modules.habits.domain.habits import is_scheduled
from habit_bot.modules.runs.domain.runs import comparison, group_of, km, records, speed
from habit_bot.modules.stats.domain.periods import Kind, Period, day_title, period, word
from habit_bot.modules.stats.models import StatsSettings
from habit_bot.modules.users.domain.kbju import GoalMode
from habit_bot.modules.warmup.domain.warmup import format_value as warmup_value
from habit_bot.modules.workouts.domain.training import format_sets, kg, tonnage, week_start
from habit_bot.platform.stats.data import Bar, DayStats, Overview, Table, TrafficRow
from habit_bot.platform.stats.domain import traffic as t
from habit_bot.platform.stats.domain.traffic import Color

FOOD, WARMUP, WORKOUT, RUN = "food", "warmup", "workout", "run"
HABIT = "h"  # + public_id своей привычки
HISTORY_DAYS = 365  # рекорды и «прошлый раз» — за год


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
class Section:
    key: str
    label: str
    has_data: bool


def _n(value: Decimal) -> str:
    """Число в таблице: до 1 знака (ккал 2 947, белки 26,4)."""
    return format_number(value.quantize(Decimal("0.1")))


class Stats:
    def __init__(self, *, uow: UowFactory, clock: Clock, tz: tzinfo, sources: Sources) -> None:
        self._uow = uow
        self._clock = clock
        self._tz = tz
        self.s = sources

    def today(self) -> date:
        return logical_day(self._clock.now(), self._tz)

    async def _registered(self, actor: Actor) -> date:
        """С какого дня оценивать: первая цель КБЖУ ставится в анкете — дни до неё серые."""
        goals = await self.s.profiles.goals(actor)
        return min((g.start_date for g in goals), default=self.today())

    # --- выбор привычки ---
    async def sections(self, actor: Actor, day: date) -> list[Section]:
        s = self.s
        found: list[Section] = []
        if s.food is not None:
            found.append(Section(FOOD, "🍽 Еда", bool(await s.food.entries(actor, day))))
        if s.warmup is not None:
            found.append(Section(WARMUP, "🤸 Зарядка", bool(await s.warmup.sessions(actor, day))))
        if s.workouts is not None:
            found.append(Section(WORKOUT, "🏋️ Тренировка", bool(await s.workouts.day_sessions(actor, day))))
        if s.runs is not None:
            found.append(Section(RUN, "🏃 Бег", bool(await s.runs.day_runs(actor, day))))
        if s.habits is not None:
            for item in await s.habits.day(actor, day):
                found.append(Section(HABIT + item.habit.public_id, item.habit.label, item.fact > 0))
        return found

    async def last_section(self, actor: Actor) -> str | None:
        async with self._uow() as uow:
            row = (await uow.session.execute(select(StatsSettings).where(
                StatsSettings.user_id == actor.user_id))).scalar_one_or_none()
            return row.section if row else None

    async def remember(self, actor: Actor, key: str) -> None:
        async with self._uow() as uow:
            row = (await uow.session.execute(select(StatsSettings).where(
                StatsSettings.user_id == actor.user_id))).scalar_one_or_none()
            if row is None:
                uow.session.add(StatsSettings(user_id=actor.user_id, section=key))
            else:
                row.section = key

    async def choose(self, actor: Actor, day: date) -> tuple[str, list[Section]]:
        """Какую привычку показать: последнюю выбранную, иначе первую с записями, иначе первую."""
        sections = await self.sections(actor, day)
        keys = [x.key for x in sections]
        last = await self.last_section(actor)
        if last in keys:
            return str(last), sections
        with_data = [x.key for x in sections if x.has_data]
        return (with_data or keys or [FOOD])[0], sections

    # --- картинка дня ---
    async def day(self, actor: Actor, key: str, day: date) -> DayStats | None:
        if key == FOOD and self.s.food is not None:
            return await self._food(actor, day)
        if key == WARMUP and self.s.warmup is not None:
            return await self._warmup(actor, day)
        if key == WORKOUT and self.s.workouts is not None:
            return await self._workout(actor, day)
        if key == RUN and self.s.runs is not None:
            return await self._run(actor, day)
        if key.startswith(HABIT) and self.s.habits is not None:
            return await self._habit(actor, key[len(HABIT):], day)
        return None

    async def _food(self, actor: Actor, day: date) -> DayStats:
        entries = await self.s.food.entries(actor, day)
        totals = await self.s.food.totals(actor, day)
        goal = await self.s.profiles.goal_on(actor, day)
        fact = totals.fact
        g = (goal.kcal, goal.protein, goal.fat, goal.carbs) if goal else (None,) * 4
        bars = (Bar("Ккал", fact.kcal, g[0], t.kcal(fact.kcal, g[0])),
                Bar("Белки", fact.protein, g[1], t.protein(fact.protein, g[1])),
                Bar("Жиры", fact.fat, g[2], t.macro(fact.fat, g[2])),
                Bar("Углев", fact.carbs, g[3], t.macro(fact.carbs, g[3])))
        rows = []
        for e in entries:
            name = e.name if e.quantity == 1 else f"{e.name} × {format_number(e.quantity)}"
            v = e.nutrients
            rows.append((name, _n(v.kcal), _n(v.protein), _n(v.fat), _n(v.carbs)))
        tables = (Table(("Блюдо", "Ккал", "Б", "Ж", "У"), tuple(rows), right=(1, 2, 3, 4)),) if rows else ()
        cost = f"Расход: {format_number(totals.cost)} ₽"
        if totals.without_price:
            n = totals.without_price
            cost += f" · {n} {word(n, 'блюдо', 'блюда', 'блюд')} без цены"
        return DayStats(f"Еда · {day_title(day)}", bars, tables, (cost,) if entries else (), empty=not entries)

    async def _warmup(self, actor: Actor, day: date) -> DayStats:
        sessions = await self.s.warmup.sessions(actor, day)
        before = [x for x in await self.s.warmup.sessions_between(actor, day - timedelta(days=60),
                                                                    day - timedelta(days=1))]
        previous: dict[str, int] = {}
        if before:
            last_day = before[-1].day
            for item in [i for x in before if x.day == last_day for i in x.items]:
                previous[item.name] = item.value
        names = list(dict.fromkeys(i.name for x in sessions for i in x.items))
        rows = []
        for name in names:
            values = {x.number: i for x in sessions for i in x.items if i.name == name}
            cells = [warmup_value(values[x.number].measure, values[x.number].value) if x.number in values else "—"
                     for x in sessions]
            last = values[max(values)]
            delta = ""
            if name in previous:
                diff = last.value - previous[name]
                shown = warmup_value(last.measure, abs(diff))
                delta = f"▲ +{shown}" if diff > 0 else f"▼ −{shown}" if diff < 0 else "="
            rows.append((name, *cells, delta))
        headers = ("Упражнение", *(f"{x.number}-я" for x in sessions), "к прошлой")
        goal = await self.s.warmup.daily_goal(actor)
        bars = (Bar("Зарядок", Decimal(len(sessions)), Decimal(goal), t.warmup(len(sessions), goal)),)
        tables = (Table(headers, tuple(rows), right=tuple(range(1, len(headers)))),) if rows else ()
        lines = tuple(await self.s.warmup.progress_lines(actor, day))
        return DayStats(f"Зарядка · {day_title(day)}", bars, tables, lines, empty=not sessions)

    async def _workout(self, actor: Actor, day: date) -> DayStats:
        sessions = await self.s.workouts.day_sessions(actor, day)
        history = await self.s.workouts.sessions_between(actor, day - timedelta(days=HISTORY_DAYS),
                                                          day - timedelta(days=1))
        best: dict[str, Decimal] = {}
        for old in history:
            for b in old.blocks:
                for x in b.sets:
                    if x.weight is not None:
                        best[b.name] = max(best.get(b.name, Decimal(0)), x.weight)
        tables, lines = [], []
        for session in sessions:
            rows = []
            for b in session.blocks:
                rows.append((b.name, format_sets(b.measure, b.sets, b.per_dumbbell),
                             kg(tonnage(b.sets, b.per_dumbbell)) if any(x.weight for x in b.sets) else "—"))
                top = max((x.weight for x in b.sets if x.weight is not None), default=None)
                if top is not None and b.name in best and top > best[b.name]:
                    lines.append(f"🏆 Рекорд: {b.name} {kg(top)} (было {kg(best[b.name])})")
            tables.append(Table(("Упражнение", "Подходы", "Тоннаж"), tuple(rows), right=(2,)))
            total = sum((tonnage(b.sets, b.per_dumbbell) for b in session.blocks), Decimal(0))
            minutes = f" · {session.duration_min} мин" if session.duration_min else ""
            lines.append(f"Тоннаж {kg(total)}{minutes}")
            same = [h for h in history if h.kind == session.kind]
            if same:
                was = sum((tonnage(b.sets, b.per_dumbbell) for b in same[-1].blocks), Decimal(0))
                diff = total - was
                sign = "▲ +" if diff > 0 else "▼ −" if diff < 0 else "= "
                lines.append(f"{sign}{kg(abs(diff))} к прошлой ({format_day(same[-1].day)})")
        return DayStats(f"Тренировка · {day_title(day)}", (), tuple(tables), tuple(lines), empty=not sessions)

    async def _run(self, actor: Actor, day: date) -> DayStats:
        runs = await self.s.runs.day_runs(actor, day)
        history = [v for _, v in await self.s.runs.runs_between(actor, day - timedelta(days=HISTORY_DAYS),
                                                                  day - timedelta(days=1))]
        rows, lines = [], []
        for run in runs:
            rows.append((km(run.distance_km), format_duration(run.seconds), format_duration(run.pace),
                         f"{format_number(speed(run.distance_km, run.seconds))} км/ч"))
            previous = next((h for h in reversed(history) if group_of(h.distance_km) is group_of(run.distance_km)),
                            None)
            lines.append(comparison(run, previous))
            lines += records(run, history)
            history.append(run)
        tables = (Table(("Дистанция", "Время", "Темп", "Скорость"), tuple(rows), right=(1, 2, 3)),) if rows else ()
        return DayStats(f"Бег · {day_title(day)}", (), tables, tuple(lines), empty=not runs)

    async def _habit(self, actor: Actor, public_id: str, day: date) -> DayStats | None:
        item = next((i for i in await self.s.habits.day(actor, day) if i.habit.public_id == public_id), None)
        if item is None:
            return None
        h = item.habit
        bars = (Bar(h.short, item.fact, h.goal, t.habit(item.fact, h.goal), h.unit),)
        marks = await self.s.habits.day_entries(actor, public_id, day)
        lines = []
        if marks:
            lines.append("Отметки: " + " · ".join(
                f"{at.astimezone(self._tz):%H:%M} +{habit_value(v, h.measure, h.unit)}" for at, v in marks))
        streak = await self.s.habits.streak_of(actor, public_id, day)
        if streak:
            lines.append(f"Серия: {streak} {word(streak, 'день', 'дня', 'дней')}")
        if not is_scheduled(h.weekdays, day):
            lines.append("Сегодня не по расписанию")
        return DayStats(f"{h.name} · {day_title(day)}", bars, (), tuple(lines), empty=not marks)

    # --- обзор-светофор ---
    def period(self, kind: Kind, shift: int) -> Period:
        return period(kind, self.today(), shift)

    async def overview(self, actor: Actor, kind: Kind, shift: int = 0) -> Overview:
        p = self.period(kind, shift)
        today = self.today()
        days = p.days
        registered = await self._registered(actor)
        off = await self.s.days.days_off(actor, p.start, p.end)
        rows: list[TrafficRow] = []

        def frame(day: date) -> Color | None:
            """Клетка без оценки: будущее — пустая, выходной и до регистрации — серая."""
            if day > today:
                return Color.EMPTY
            if day in off or day < registered:
                return Color.GRAY
            return None

        def row(label: str, cells: Sequence[Color]) -> TrafficRow:
            return TrafficRow(label, tuple(cells), t.green_share(cells), t.current_streak(cells))

        hidden = await self.s.habits.archived_builtins(actor) if self.s.habits is not None else set()
        if self.s.food is not None and FOOD not in hidden:
            totals = await self.s.food.daily_totals(actor, p.start, p.end)
            if totals:
                goals = {d: await self.s.profiles.goal_on(actor, d) for d in days if d in totals}
                kcal, prot = [], []
                for d in days:
                    fixed = frame(d)
                    goal = goals.get(d)
                    if fixed is None and d in totals and goal is not None:
                        kcal.append(t.kcal(totals[d].fact.kcal, goal.kcal))
                        prot.append(t.protein(totals[d].fact.protein, goal.protein))
                    else:
                        kcal.append(fixed or Color.GRAY)
                        prot.append(fixed or Color.GRAY)
                rows += [row("Калории", kcal), row("Белки", prot)]
        if self.s.warmup is not None and WARMUP not in hidden:
            sessions = await self.s.warmup.sessions_between(actor, p.start, p.end)
            if sessions:
                goal = await self.s.warmup.daily_goal(actor)
                count: dict[date, int] = {}
                for x in sessions:
                    count[x.day] = count.get(x.day, 0) + 1
                rows.append(row("Зарядка", [frame(d) or t.warmup(count.get(d, 0), goal) for d in days]))
        if self.s.workouts is not None and WORKOUT not in hidden:
            trained = await self._weekly_workouts(actor, p, today, registered)
            if trained is not None:
                rows.append(trained)
        if self.s.habits is not None:
            facts = await self.s.habits.facts_between(actor, p.start, p.end)
            for h in await self.s.habits.habits(actor):
                if h.public_id not in facts:
                    continue
                done = facts[h.public_id]
                cells = []
                for d in days:
                    fixed = frame(d)
                    if fixed is None and not is_scheduled(h.weekdays, d):
                        fixed = Color.GRAY
                    cells.append(fixed or t.habit(done.get(d, Decimal(0)), h.goal))
                rows.append(row(h.label, cells))
        weight = await self._weekly_weight(actor, p, today)
        if weight is not None:
            rows.append(row("Вес", weight))
        return Overview(p.title, days, tuple(rows))

    async def _weekly_workouts(self, actor: Actor, p: Period, today: date, registered: date) -> TrafficRow | None:
        """Тренировки и бег против цели «в неделю» (раздел 4.10). День с тренировкой виден всегда: закончившаяся
        неделя — цветом её итога, идущая — 🟢, если цель уже выполнена, иначе 🟡 «в процессе». Дни без тренировки —
        серые (отдых не провал). % зелёных и серия — по неделям."""
        first, last = week_start(p.start), week_start(p.end)
        trained: set[date] = {x.day for x in await self.s.workouts.sessions_between(actor, first, p.end)}
        if self.s.runs is not None:
            trained |= {day for day, _ in await self.s.runs.runs_between(actor, first, p.end)}
        if not [d for d in trained if d >= p.start]:
            return None
        goal = (await self.s.workouts.settings(actor)).weekly_goal
        weeks: dict[date, Color] = {}
        start = first
        while start <= last:
            end = start + timedelta(days=6)
            count = await self.s.workouts.count_between(actor, start, end)
            if self.s.runs is not None:
                count += await self.s.runs.count_between(actor, start, end)
            if start > today:
                weeks[start] = Color.EMPTY
            elif end >= today:  # неделя идёт
                weeks[start] = Color.GREEN if count >= goal else (Color.YELLOW if count else Color.EMPTY)
            else:
                weeks[start] = t.weekly(count, goal)
            start += timedelta(days=7)
        cells = []
        for d in p.days:
            if d > today:
                cells.append(Color.EMPTY)
            elif d in trained:  # тренировка видна, даже если записана задним числом до анкеты
                cells.append(weeks[week_start(d)])
            else:
                cells.append(Color.GRAY)
        finished = [c for s, c in sorted(weeks.items())
                    if (s + timedelta(days=6) < today and s + timedelta(days=6) >= registered) or c is Color.GREEN]
        return TrafficRow("Тренировки", tuple(cells), t.green_share(finished), t.current_streak(finished))

    async def _weekly_weight(self, actor: Actor, p: Period, today: date) -> list[Color] | None:
        """Средний вес недели к средней прошлой: в сторону цели — зелёный (раздел 4.10)."""
        first = week_start(p.start)
        weights = await self.s.profiles.weights_between(actor, first - timedelta(days=7), p.end)
        if not [d for d in weights if d >= p.start]:
            return None
        profile = await self.s.profiles.profile(actor)
        direction = 0
        if profile is not None:
            if profile.target_weight is not None and profile.target_weight != profile.weight_kg:
                direction = 1 if profile.target_weight > profile.weight_kg else -1
            elif profile.mode is GoalMode.LOSS:
                direction = -1
            elif profile.mode is GoalMode.GAIN:
                direction = 1

        def average(start: date) -> Decimal | None:
            found = [v for d, v in weights.items() if start <= d <= start + timedelta(days=6)]
            return sum(found, Decimal(0)) / len(found) if found else None

        cells = []
        for d in p.days:
            if d > today:
                cells.append(Color.EMPTY)
                continue
            now, before = average(week_start(d)), average(week_start(d) - timedelta(days=7))
            cells.append(t.weight(now - before if now is not None and before is not None else None, direction))
        return cells
