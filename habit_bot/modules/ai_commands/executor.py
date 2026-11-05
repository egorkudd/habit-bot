"""Выполнение проверенного плана и «↩️ Отменить всё» (раздел 3.10). Каждое действие идёт через сценарий своего
модуля — так же, как кнопки; для каждого запоминается, как его отменить."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from habit_bot.kernel.errors import AppError
from habit_bot.kernel.identity import Actor
from habit_bot.modules.ai_commands.planner import Services
from habit_bot.modules.food.domain.nutrition import Nutrients, Unit
from habit_bot.modules.food.domain.other_line import OtherLine
from habit_bot.modules.habits.domain.habits import Measure as HabitMeasure
from habit_bot.modules.users.domain.kbju import Targets
from habit_bot.modules.warmup.domain.warmup import Measure as WarmupMeasure
from habit_bot.modules.workouts.domain.training import SetValue

log = logging.getLogger(__name__)
UNITS = {"portion": Unit.PORTION, "100g": Unit.GRAMS, "piece": Unit.PIECE}


@dataclass
class Done:
    lines: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    undo: list[dict[str, Any]] = field(default_factory=list)
    approx: list[tuple[str, str]] = field(default_factory=list)  # (запись, название) — «Сохранить как рецепт»
    days: set[date] = field(default_factory=set)


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


class Executor:
    def __init__(self, services: Services) -> None:
        self.s = services

    async def run(self, actor: Actor, ops: Sequence[dict[str, Any]]) -> Done:
        done = Done()
        workout_groups: dict[str, list[tuple[str, list[SetValue]]]] = {}
        for op in ops:
            if op["op"] == "workout.set":
                sets = [SetValue(reps=s.get("reps"), seconds=s.get("seconds"),
                                 weight=_d(s["weight"]) if s.get("weight") else None) for s in op["sets"]]
                workout_groups.setdefault(op["day"], []).append((op["exercise_id"], sets))
                done.lines.append(op["line"])
                continue
            try:
                await self._one(actor, op, done)
                done.lines.append(op["line"])
            except AppError as err:
                done.failed.append(f"{op['line']} — {err.user_text()}")
        for day, groups in workout_groups.items():
            session = await self.s.workouts.log_sets(actor, date.fromisoformat(day), groups)
            done.undo.append({"undo": "workout.delete", "id": session.public_id})
            done.days.add(date.fromisoformat(day))
        return done

    async def _one(self, actor: Actor, op: dict[str, Any], done: Done) -> None:
        kind = op["op"]
        s = self.s
        if "day" in op:
            done.days.add(date.fromisoformat(op["day"]))
        if kind == "food.add":
            day = date.fromisoformat(op["day"])
            if op.get("approx"):
                line = OtherLine(op["name"], Nutrients(*(_d(v) for v in op["nutrients"])),
                                 _d(op["price"]) if op.get("price") else None)
                entry = await s.food.log_other(actor, line, day=day)
                done.approx.append((entry.public_id, entry.name))
            else:
                entry = await s.food.log_item(actor, op["item_id"], quantity=_d(op["quantity"]), day=day)
            done.undo.append({"undo": "food.delete", "id": entry.public_id})
        elif kind == "food.quantity":
            entry = await s.food.entry(actor, op["entry_id"])
            if entry is None:
                raise AppError("UI-STALE")
            await s.food.set_quantity(actor, op["entry_id"], _d(op["quantity"]))
            done.undo.append({"undo": "food.quantity", "id": op["entry_id"], "quantity": str(entry.quantity)})
            done.days.add(entry.day)
        elif kind == "food.delete":
            removed = await s.food.delete_entry(actor, op["entry_id"])
            if removed is None:
                raise AppError("UI-STALE")
            done.undo.append({"undo": "food.restore", "id": op["entry_id"]})
            done.days.add(removed.day)
        elif kind == "food.move":
            result = await s.days.move(actor, "food", op["entry_id"], date.fromisoformat(op["to_day"]))
            if result is None:
                raise AppError("UI-STALE")
            done.undo.append({"undo": "move", "kind": "food", "id": op["entry_id"], "day": result.old_day.isoformat()})
            done.days.update({result.old_day, result.new_day})
        elif kind == "warmup.add":
            session = await s.warmup.record(actor, op["values"], day=date.fromisoformat(op["day"]))
            done.undo.append({"undo": "warmup.delete", "id": session.public_id})
        elif kind == "warmup.edit":
            old = await s.warmup.set_value(actor, op["session_id"], op["name"], int(op["value"]))
            if old is None:
                raise AppError("UI-STALE")
            done.undo.append({"undo": "warmup.edit", "id": op["session_id"], "name": op["name"], "value": old})
        elif kind in {"habit.mark", "habit.value"}:
            ids = []
            for value in op["values"]:
                result = await s.habits.mark(actor, op["habit_id"], day=date.fromisoformat(op["day"]), value=_d(value),
                                             source="text")
                ids.append(result.entry_id)
            done.undo.append({"undo": "habit.entries", "ids": ids})
        elif kind == "run.add":
            run = await s.runs.record(actor, distance_km=_d(op["distance"]), seconds=int(op["seconds"]),
                                      day=date.fromisoformat(op["day"]))
            done.undo.append({"undo": "run.delete", "id": run.public_id})
        elif kind == "day.off":
            day = date.fromisoformat(op["day"])
            if await s.days.toggle_day_off(actor, day):
                done.undo.append({"undo": "day.toggle", "day": op["day"]})
        elif kind == "weight.record":
            before = await s.profiles.profile(actor)
            await s.profiles.update_profile(actor, weight_kg=_d(op["kg"]))
            done.undo.append({"undo": "weight", "kg": str(before.weight_kg) if before else None})
        elif kind == "recipe.create":
            nutrients = Nutrients(*(_d(v) for v in op["nutrients"]))
            price = _d(op["price"]) if op.get("price") else None
            if op.get("update_id"):
                old = await s.food.item(actor, op["update_id"])
                await s.food.update_item(actor, op["update_id"], nutrients=nutrients, price=price)
                done.undo.append({"undo": "recipe.restore", "id": op["update_id"],
                                  "nutrients": [str(v) for v in old.nutrients.values()],
                                  "price": str(old.price) if old.price is not None else None})
            else:
                unit = UNITS[op["unit"]]
                item = await s.food.create_item(actor, name=op["name"], kind="recipe" if unit is Unit.PORTION
                                                else "product", unit=unit, nutrients=nutrients, price=price,
                                                composition=op.get("composition", ""))
                done.undo.append({"undo": "recipe.delete", "id": item.public_id})
        elif kind == "habit.create":
            if op.get("template"):
                habit = await s.habits.from_template(actor, op["template"])
            else:
                habit = await s.habits.create(actor, name=op["name"], emoji=op["emoji"],
                                              measure=HabitMeasure(op["measure"]), unit=op.get("unit", ""),
                                              goal=_d(op["goal"]) if op.get("goal") else None, step=Decimal(1))
            done.undo.append({"undo": "habit.delete", "id": habit.public_id})
        elif kind == "goal.set":
            kcal, protein, fat, carbs = op["values"]
            await s.profiles.add_goal(actor, Targets(kcal, protein, fat, carbs),
                                      start_date=date.fromisoformat(op["start_date"]), source="text")
            done.undo.append({"undo": "goal.delete", "day": op["start_date"]})
        elif kind == "exercise_goal.set":
            goal = await s.warmup.set_goal(actor, op["template_id"], target=int(op["target"]),
                                           target_date=date.fromisoformat(op["date"]))
            done.undo.append({"undo": "exercise_goal.remove", "id": goal.public_id})
        elif kind == "warmup.set":
            for e in op["exercises"]:
                if e.get("existing_id"):
                    if e.get("step"):
                        current = next((t for t in await s.warmup.templates(actor) if t.public_id == e["existing_id"]),
                                       None)
                        await s.warmup.set_step(actor, e["existing_id"], int(e["step"]))
                        if current is not None:
                            done.undo.append({"undo": "warmup.step", "id": e["existing_id"], "step": current.step})
                    continue
                added = await s.warmup.add_exercise(actor, name=e["name"], measure=WarmupMeasure(e["measure"]))
                if e.get("step"):
                    await s.warmup.set_step(actor, added.public_id, int(e["step"]))
                done.undo.append({"undo": "warmup.remove", "id": added.public_id})
        else:  # pragma: no cover — план строится только из закрытого набора
            raise AppError("UI-STALE")

    async def undo(self, actor: Actor, records: Sequence[dict[str, Any]]) -> int:
        """Отменить в обратном порядке. Возвращает, сколько действий отменено."""
        s = self.s
        count = 0
        for r in reversed(records):
            kind = r["undo"]
            try:
                if kind == "food.delete":
                    await s.food.delete_entry(actor, r["id"])
                elif kind == "food.quantity":
                    await s.food.set_quantity(actor, r["id"], _d(r["quantity"]))
                elif kind == "food.restore":
                    await s.food.restore_entry(actor, r["id"])
                elif kind == "move":
                    await s.days.move(actor, r["kind"], r["id"], date.fromisoformat(r["day"]))
                elif kind == "warmup.delete":
                    await s.warmup.delete_session(actor, r["id"])
                elif kind == "warmup.edit":
                    await s.warmup.set_value(actor, r["id"], r["name"], int(r["value"]))
                elif kind == "habit.entries":
                    for entry_id in r["ids"]:
                        await s.habits.undo(actor, entry_id)
                elif kind == "workout.delete":
                    await s.workouts.delete_session(actor, r["id"])
                elif kind == "run.delete":
                    await s.runs.delete(actor, r["id"])
                elif kind == "day.toggle":
                    await s.days.toggle_day_off(actor, date.fromisoformat(r["day"]))
                elif kind == "weight":
                    if r.get("kg"):
                        await s.profiles.update_profile(actor, weight_kg=_d(r["kg"]))
                elif kind == "recipe.restore":
                    await s.food.update_item(actor, r["id"], nutrients=Nutrients(*(_d(v) for v in r["nutrients"])),
                                             price=_d(r["price"]) if r.get("price") else None)
                elif kind == "recipe.delete":
                    await s.food.delete_item(actor, r["id"])
                elif kind == "habit.delete":
                    await s.habits.delete(actor, r["id"])
                elif kind == "goal.delete":
                    await s.profiles.delete_goal(actor, date.fromisoformat(r["day"]), "text")
                elif kind == "exercise_goal.remove":
                    await s.warmup.remove_goal(actor, r["id"])
                elif kind == "warmup.step":
                    await s.warmup.set_step(actor, r["id"], int(r["step"]))
                elif kind == "warmup.remove":
                    await s.warmup.remove_exercise(actor, r["id"])
                count += 1
            except AppError:
                log.warning("Не удалось отменить действие %s", kind)
        return count
