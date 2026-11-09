"""Проверка действий модели и план выполнения (раздел 3.10): объект существует и принадлежит пользователю, значения
в допустимых пределах, дата не в будущем. Что не прошло — отбрасывается с причиной. План — JSON-словари: он
хранится в ``AiCommand`` до «✅ Выполнить всё»."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from habit_bot.kernel.domain.formatting import format_day, format_duration, format_number
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.identity import Actor
from habit_bot.modules.ai_commands.domain import actions as a
from habit_bot.modules.food.domain import reference
from habit_bot.modules.food.domain.nutrition import Nutrients, Unit, check_quantity
from habit_bot.modules.habits.domain.habits import TEMPLATES, Measure, format_value
from habit_bot.modules.runs.domain.runs import km, pace, parse_run_time
from habit_bot.modules.warmup.domain.warmup import Measure as WarmupMeasure
from habit_bot.modules.warmup.domain.warmup import format_step, ordinal, parse_value
from habit_bot.modules.warmup.domain.warmup import format_value as warmup_format
from habit_bot.modules.workouts.domain.training import Filters, Kind, SetValue, format_sets
from habit_bot.modules.workouts.domain.training import Measure as SetMeasure

GROUPS = {
    "food": "Еда", "warmup": "Зарядка", "habit": "Привычки", "workout": "Тренировки", "run": "Бег", "day": "Дни",
    "weight": "Вес", "recipe": "Рецепты", "goal": "Цели", "exercise_goal": "Цели", "habit_new": "Привычки",
    "warmup_set": "Зарядка",
}


@dataclass
class Services:
    """Сценарии модулей, через которые выполняются действия. Отсутствующий модуль — его действия отбрасываются."""

    days: Any
    profiles: Any
    food: Any = None
    warmup: Any = None
    habits: Any = None
    workouts: Any = None
    runs: Any = None


@dataclass
class Plan:
    ops: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _fold(text: str) -> str:
    return " ".join(text.casefold().replace("ё", "е").split())


def find(name: str, options: Sequence[Any], key: Any = lambda o: o.name, *, prefix: bool = True) -> Any:
    """Своё по названию: точное совпадение без учёта регистра, иначе (``prefix``) единственное начинающееся с этого."""
    wanted = _fold(name)
    exact = [o for o in options if _fold(key(o)) == wanted]
    if exact or not prefix:
        return exact[0] if exact else None
    prefix = [o for o in options if _fold(key(o)).startswith(wanted) or wanted.startswith(_fold(key(o)))]
    return prefix[0] if len(prefix) == 1 else None


def _kcal(item: Any, quantity: Decimal) -> Decimal:
    factor = quantity / 100 if item.unit is Unit.GRAMS else quantity
    return Decimal(item.nutrients.kcal * factor)


def _qty(item: Any, quantity: Decimal) -> str:
    if item.unit is Unit.GRAMS:
        return f"{format_number(quantity)} г"
    return f"× {format_number(quantity)}" if quantity != 1 else ""


def _time(entry: Any, tz: Any) -> str:
    return entry.logged_at.astimezone(tz).strftime("%H:%M") if entry.logged_at else ""


class Planner:
    def __init__(self, services: Services, actor: Actor, today: date, tz: Any) -> None:
        self.s = services
        self.actor = actor
        self.today = today
        self.tz = tz
        self._cache: dict[str, Any] = {}

    async def _list(self, key: str, loader: Any) -> Any:
        if key not in self._cache:
            self._cache[key] = await loader()
        return self._cache[key]

    def _day(self, day: date, label: str) -> None:
        if day > self.today:
            raise _Skip(f"{label}: {format_day(day)} — это будущее")
        if day < self.today - timedelta(days=366):
            raise _Skip(f"{label}: {format_day(day)} — больше года назад")

    async def plan(self, actions: Sequence[Any]) -> Plan:
        plan = Plan()
        for action in actions:
            try:
                op = await self._one(action)
            except _Skip as skip:
                plan.skipped.append(str(skip))
                continue
            except AppError as err:
                plan.skipped.append(f"{_title(action)}: {err.user_text()}")
                continue
            plan.ops.append(op)
        return plan

    async def _one(self, action: Any) -> dict[str, Any]:
        handler = getattr(self, "_" + action.type.replace(".", "_"))
        op: dict[str, Any] = await handler(action)
        op["op"] = action.type
        return op

    # --- еда ---
    async def _foods(self) -> list[Any]:
        if self.s.food is None:
            raise _Skip("Еда: раздел выключен")
        return list(await self._list("foods", lambda: self.s.food.items(self.actor)))

    async def _food_add(self, x: a.FoodAdd) -> dict[str, Any]:
        self._day(x.day, x.item)
        # Порядок (правки 1.0.4): своё точно → справочник (название или синоним) → своё по началу → оценка модели.
        foods = await self._foods()
        item = find(x.item, foods, prefix=False)
        ref = reference.find(x.item) if item is None else None
        if ref is not None:
            return self._food_reference(x, ref)
        item = item or find(x.item, foods)
        if item is not None:
            kcal = _kcal(item, x.quantity)
            qty = _qty(item, x.quantity)
            line = f"➕ {format_day(x.day)} Еда: {item.name}{' ' + qty if qty else ''} — {format_number(kcal)} ккал"
            return {"group": "food", "line": line, "day": x.day.isoformat(), "item_id": item.public_id,
                    "quantity": str(x.quantity)}
        if x.kcal is None:
            raise _Skip(f"Еда: «{x.item}» нет среди ваших рецептов и продуктов и в справочнике")
        values = [str(v or 0) for v in (x.kcal, x.protein, x.fat, x.carbs)]
        p, f, c = (format_number(Decimal(v)) for v in values[1:])
        line = (f"➕ {format_day(x.day)} Еда: {x.item} ≈ {format_number(x.kcal)} ккал · Б {p} · Ж {f} · У {c} "
                "(оценка модели)")
        return {"group": "food", "line": line, "day": x.day.isoformat(), "name": x.item[:64], "nutrients": values,
                "price": str(x.price) if x.price is not None else None, "approx": True}

    @staticmethod
    def _food_reference(x: a.FoodAdd, ref: reference.RefFood) -> dict[str, Any]:
        """Блюдо из справочника: КБЖУ на количество, запись — как «Другое» с названием и количеством."""
        n = ref.scaled(check_quantity(ref.unit, x.quantity))
        qty = _qty(ref, x.quantity)
        name = f"{ref.title}{',' if ref.unit is Unit.GRAMS else ''} {qty}" if qty else ref.title
        p, f, c = (format_number(v) for v in (n.protein, n.fat, n.carbs))
        line = (f"➕ {format_day(x.day)} Еда: {name} — {format_number(n.kcal)} ккал · Б {p} · Ж {f} · У {c} "
                "(справочник)")
        return {"group": "food", "line": line, "day": x.day.isoformat(), "name": name[:64],
                "nutrients": [str(v) for v in n.values()], "price": None, "approx": True}

    async def _entry(self, day: date, name: str, time: str | None) -> Any:
        self._day(day, name)
        if self.s.food is None:
            raise _Skip("Еда: раздел выключен")
        entries = [e for e in await self.s.food.entries(self.actor, day) if _fold(e.name) == _fold(name)
                   or _fold(e.name).startswith(_fold(name))]
        if time:
            entries = [e for e in entries if _time(e, self.tz) == time.strip()] or entries
        if not entries:
            raise _Skip(f"Еда: «{name}» за {format_day(day)} не найдено")
        return entries[-1]

    async def _food_quantity(self, x: a.FoodQuantity) -> dict[str, Any]:
        entry = await self._entry(x.day, x.item, x.time)
        line = (f"✏️ {format_day(x.day)} Еда: {entry.name} ({_time(entry, self.tz)}) — "
                f"{format_number(entry.quantity)} → {format_number(x.quantity)}")
        return {"group": "food", "line": line, "entry_id": entry.public_id, "quantity": str(x.quantity)}

    async def _food_delete(self, x: a.FoodDelete) -> dict[str, Any]:
        entry = await self._entry(x.day, x.item, x.time)
        return {"group": "food", "line": f"🗑 {format_day(x.day)} Еда: {entry.name} ({_time(entry, self.tz)})",
                "entry_id": entry.public_id}

    async def _food_move(self, x: a.FoodMove) -> dict[str, Any]:
        entry = await self._entry(x.day, x.item, x.time)
        self._day(x.to_day, entry.name)
        if x.to_day == x.day:
            raise _Skip(f"Еда: «{entry.name}» и так за {format_day(x.day)}")
        return {"group": "food", "line": f"📅 {format_day(x.day)} → {format_day(x.to_day)} Еда: {entry.name}",
                "entry_id": entry.public_id, "to_day": x.to_day.isoformat()}

    # --- зарядка ---
    async def _templates(self) -> list[Any]:
        if self.s.warmup is None:
            raise _Skip("Зарядка: раздел выключен")
        return list(await self._list("warmup", lambda: self.s.warmup.templates(self.actor)))

    async def _warmup_add(self, x: a.WarmupAdd) -> dict[str, Any]:
        self._day(x.day, "Зарядка")
        templates = await self._templates()
        values: dict[str, int] = {}
        shown = []
        for name, raw in x.values.items():
            t = find(name, templates, key=lambda e: e.short) or find(name, templates)
            if t is None:
                raise _Skip(f"Зарядка: упражнения «{name}» нет в наборе")
            values[t.public_id] = parse_value(t.measure, raw, t.name)
            shown.append(f"{t.short} {_warmup_value(t.measure, values[t.public_id])}")
        return {"group": "warmup", "line": f"➕ {format_day(x.day)} Зарядка: " + " · ".join(shown),
                "day": x.day.isoformat(), "values": values}

    async def _warmup_edit(self, x: a.WarmupEdit) -> dict[str, Any]:
        self._day(x.day, "Зарядка")
        sessions = await self.s.warmup.sessions(self.actor, x.day) if self.s.warmup else []
        session = next((s for s in sessions if s.number == x.number), None)
        if session is None:
            raise _Skip(f"Зарядка: {ordinal(x.number)} за {format_day(x.day)} не найдена")
        item = find(x.exercise, list(session.items))
        if item is None:
            raise _Skip(f"Зарядка: {ordinal(x.number)} за {format_day(x.day)} — нет «{x.exercise}»")
        value = parse_value(item.measure, x.value, item.name)
        line = (f"✏️ {format_day(x.day)} Зарядка {ordinal(x.number)}: {item.name} "
                f"{_warmup_value(item.measure, item.value)} → {_warmup_value(item.measure, value)}")
        return {"group": "warmup", "line": line, "session_id": session.public_id, "name": item.name, "value": value}

    # --- привычки ---
    async def _habit(self, name: str) -> Any:
        if self.s.habits is None:
            raise _Skip("Привычки: раздел выключен")
        found = await self._list("habits", lambda: self.s.habits.habits(self.actor))
        habit = find(name, found) or find(name, found, key=lambda h: h.short)
        if habit is None:
            raise _Skip(f"Привычки: «{name}» не найдена")
        return habit

    async def _habit_mark(self, x: a.HabitMark) -> dict[str, Any]:
        self._day(x.day, x.habit)
        habit = await self._habit(x.habit)
        if habit.step is None:
            raise _Skip(f"Привычки: у «{habit.short}» нужно число — напишите, сколько")
        return {"group": "habit", "line": f"✅ {format_day(x.day)} {habit.label} +{x.times * habit.step:g}"
                if habit.measure is not Measure.CHECK else f"✅ {format_day(x.day)} {habit.label} ×{x.times}",
                "day": x.day.isoformat(), "habit_id": habit.public_id, "values": [str(habit.step)] * x.times}

    async def _habit_value(self, x: a.HabitValue) -> dict[str, Any]:
        self._day(x.day, x.habit)
        habit = await self._habit(x.habit)
        return {"group": "habit", "line": f"➕ {format_day(x.day)} {habit.label} "
                                          f"+{format_value(x.value, habit.measure, habit.unit)}",
                "day": x.day.isoformat(), "habit_id": habit.public_id, "values": [str(x.value)]}

    # --- тренировка и бег ---
    async def _workout_set(self, x: a.WorkoutSet) -> dict[str, Any]:
        self._day(x.day, x.exercise)
        if self.s.workouts is None:
            raise _Skip("Тренировки: раздел выключен")
        filters = Filters(kind=Kind.FREE, show_all=True)  # командой можно записать любое упражнение базы
        exercises = await self._list("exercises", lambda: self.s.workouts.exercises(self.actor, filters))
        exercise = find(x.exercise, exercises)
        if exercise is None:
            raise _Skip(f"Тренировки: упражнения «{x.exercise}» нет в базе")
        measure = exercise.spec.measure
        if measure is SetMeasure.TIME:
            if not x.seconds:
                raise _Skip(f"Тренировки: «{exercise.name}» — нужно время подходов")
            sets = [SetValue(seconds=s) for s in x.seconds]
        else:
            if not x.reps:
                raise _Skip(f"Тренировки: «{exercise.name}» — нужны повторы")
            if measure is SetMeasure.WEIGHT_REPS and x.weight is None:
                raise _Skip(f"Тренировки: «{exercise.name}» — нужен вес")
            weight = x.weight if measure is SetMeasure.WEIGHT_REPS else None
            sets = [SetValue(reps=r, weight=weight) for r in x.reps]
        line = (f"🏋️ {format_day(x.day)} {exercise.name}: "
                f"{format_sets(measure, sets, exercise.spec.per_dumbbell)}")
        return {"group": "workout", "line": line, "day": x.day.isoformat(), "exercise_id": exercise.public_id,
                "sets": [{"reps": s.reps, "seconds": s.seconds, "weight": str(s.weight) if s.weight else None}
                         for s in sets]}

    async def _run_add(self, x: a.RunAdd) -> dict[str, Any]:
        self._day(x.day, "Бег")
        if self.s.runs is None:
            raise _Skip("Бег: раздел выключен")
        seconds = parse_run_time(x.time)
        per_km = pace(x.distance_km, seconds)
        return {"group": "run", "line": f"🏃 {format_day(x.day)} {km(x.distance_km)} · {format_duration(seconds)} · "
                                        f"темп {format_duration(per_km)}",
                "day": x.day.isoformat(), "distance": str(x.distance_km), "seconds": seconds}

    async def _day_off(self, x: a.DayOff) -> dict[str, Any]:
        self._day(x.day, "Выходной")
        if await self.s.days.is_day_off(self.actor, x.day):
            raise _Skip(f"Выходной: {format_day(x.day)} уже отмечен")
        return {"group": "day", "line": f"🛌 {format_day(x.day)} Выходной", "day": x.day.isoformat()}

    async def _weight_record(self, x: a.WeightRecord) -> dict[str, Any]:
        self._day(x.day, "Вес")
        # прошлый день — только взвешивание этого дня, профиль (и пересчёт КБЖУ) — по весу за сегодня (1.0.3)
        return {"group": "weight", "line": f"⚖️ {format_day(x.day)} Вес {format_number(x.kg)} кг", "kg": str(x.kg),
                "day": x.day.isoformat()}

    # --- заполнение (раздел 3.12) ---
    async def _recipe_create(self, x: a.RecipeCreate) -> dict[str, Any]:
        if self.s.food is None:
            raise _Skip("Рецепты: раздел выключен")
        values = [x.kcal, x.protein, x.fat, x.carbs]
        n = Nutrients(*values)
        price = f" · {format_number(x.price)} ₽" if x.price is not None else ""
        shown = (f"{format_number(n.kcal)} ккал · Б {format_number(n.protein)} · Ж {format_number(n.fat)} · "
                 f"У {format_number(n.carbs)}{price}")
        mine = await self.s.food.items(self.actor, include_hidden=True)
        existing = next((i for i in mine if _fold(i.name) == _fold(x.name)), None)
        op = {"group": "recipe", "name": " ".join(x.name.split()), "unit": x.unit,
              "nutrients": [str(v) for v in values], "price": str(x.price) if x.price is not None else None,
              "composition": x.composition}
        if existing is not None:
            return {**op, "line": f"♻️ Рецепт «{existing.name}» уже есть — обновлю: {shown}",
                    "update_id": existing.public_id, "duplicate": True}
        unit = {"portion": "", "100g": " (на 100 г)", "piece": " (за 1 шт)"}[x.unit]
        return {**op, "line": f"🍽 Рецепт «{op['name']}»{unit}: {shown}"}

    async def _habit_create(self, x: a.HabitCreate) -> dict[str, Any]:
        if self.s.habits is None:
            raise _Skip("Привычки: раздел выключен")
        existing = await self._list("habits", lambda: self.s.habits.habits(self.actor))
        if find(x.name, existing) is not None:
            raise _Skip(f"Привычки: «{x.name}» уже есть")
        template = next((t for t in TEMPLATES if _fold(t.name) == _fold(x.name) or _fold(t.short) == _fold(x.name)),
                        None)
        if template is not None:
            goal = f", цель {format_value(template.goal, template.measure, template.unit)}" if template.goal else ""
            return {"group": "habit_new", "line": f"✅ Привычка «{template.emoji} {template.name}»{goal}",
                    "template": template.key}
        measure = Measure(x.measure)
        goal = f", цель {format_value(x.goal, measure, x.unit)}" if x.goal else ""
        return {"group": "habit_new", "line": f"✅ Привычка «{x.emoji or '⭐'} {x.name}»{goal}", "name": x.name,
                "emoji": x.emoji or "⭐", "measure": measure.value, "unit": x.unit,
                "goal": str(x.goal) if x.goal else None}

    async def _goal_set(self, x: a.GoalSet) -> dict[str, Any]:
        self._day(x.start_date, "Цель КБЖУ")
        line = (f"🎯 Цель КБЖУ с {format_day(x.start_date)}: {format_number(x.kcal)} ккал · Б {x.protein} · "
                f"Ж {x.fat} · У {x.carbs}")
        return {"group": "goal", "line": line, "start_date": x.start_date.isoformat(),
                "values": [x.kcal, x.protein, x.fat, x.carbs]}

    async def _exercise_goal_set(self, x: a.ExerciseGoalSet) -> dict[str, Any]:
        templates = await self._templates()
        t = find(x.exercise, templates) or find(x.exercise, templates, key=lambda e: e.short)
        if t is None:
            raise _Skip(f"Цели: упражнения «{x.exercise}» нет в наборе зарядки")
        if x.date <= self.today:
            raise _Skip(f"Цели: дата {format_day(x.date)} уже прошла")
        target = parse_value(t.measure, x.value, t.name)
        return {"group": "exercise_goal", "line": f"🎯 {t.short}: {_warmup_value(t.measure, target)} к "
                                                  f"{x.date:%d.%m.%Y}",
                "template_id": t.public_id, "target": target, "date": x.date.isoformat()}

    async def _warmup_set(self, x: a.WarmupSetDefine) -> dict[str, Any]:
        templates = await self._templates()
        items, shown = [], []
        for e in x.exercises:
            measure = WarmupMeasure.SECONDS if e.measure == "sec" else WarmupMeasure.REPS
            existing = find(e.name, templates) or find(e.name, templates, key=lambda t: t.short)
            step = e.step
            items.append({"name": e.name, "measure": measure.value, "step": step,
                          "existing_id": existing.public_id if existing else None})
            shown.append(f"{e.name}" + (f" ({format_step(measure, step)})" if step else ""))
        return {"group": "warmup_set", "line": "🤸 Набор зарядки: " + ", ".join(shown), "exercises": items}


def _warmup_value(measure: Any, value: int) -> str:
    return str(warmup_format(measure, value))


class _Skip(Exception):
    """Действие отброшено при проверке — причина видна пользователю в карточке."""


def _title(action: Any) -> str:
    kind = str(action.type)
    return GROUPS.get(kind.split(".")[0], kind)
