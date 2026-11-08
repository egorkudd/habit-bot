"""Раздел 3.10: проверка плана — что бот отказывается делать и почему (причина видна в «Не выполню»)."""

import dataclasses
import json
from datetime import date
from typing import Any

import pytest

from habit_bot.modules.ai_commands.domain.actions import parse_reply
from habit_bot.modules.ai_commands.planner import Planner
from tests.ai.test_golden import golden_app  # noqa: F401 — общий стенд

D, Y = "2026-11-03", "2026-11-02"
TODAY = date(2026, 11, 3)

CASES = [
    ({"type": "food.add", "day": "2025-10-01", "item": "Коктейль"}, "Коктейль: 01.10 — больше года назад"),
    ({"type": "food.add", "day": D, "item": "Борщ"}, "Еда: «Борщ» нет среди ваших рецептов и продуктов"),
    ({"type": "food.quantity", "day": D, "item": "Коктейль", "quantity": 2, "time": "10:00"},
     "✏️ 03.11 Еда: Коктейль (09:12) — 1 → 2"),
    ({"type": "food.move", "day": D, "item": "Коктейль", "to_day": D}, "Еда: «Коктейль» и так за 03.11"),
    ({"type": "warmup.add", "day": D, "values": {"Сальто": "5"}}, "Зарядка: упражнения «Сальто» нет в наборе"),
    ({"type": "warmup.edit", "day": D, "number": 5, "exercise": "Планка", "value": "6:00"},
     "Зарядка: 5-я за 03.11 не найдена"),
    ({"type": "warmup.edit", "day": D, "number": 1, "exercise": "Сальто", "value": "5"},
     "Зарядка: 1-я за 03.11 — нет «Сальто»"),
    ({"type": "habit.mark", "day": D, "habit": "Йога"}, "Привычки: «Йога» не найдена"),
    ({"type": "workout.set", "day": D, "exercise": "Сальто назад", "reps": [5]},
     "Тренировки: упражнения «Сальто назад» нет в базе"),
    ({"type": "workout.set", "day": D, "exercise": "Планка", "reps": [5]},
     "Тренировки: «Планка» — нужно время подходов"),
    ({"type": "workout.set", "day": D, "exercise": "Присед со штангой", "weight": 100},
     "Тренировки: «Присед со штангой» — нужны повторы"),
    ({"type": "workout.set", "day": D, "exercise": "Присед со штангой", "reps": [8]},
     "Тренировки: «Присед со штангой» — нужен вес"),
    ({"type": "run.add", "day": D, "distance_km": 5, "time": "быстро"}, "Бег: "),
    ({"type": "weight.record", "day": "2026-11-04", "kg": 77}, "Вес: "),  # будущая дата; прошлые дни — с 1.0.3
    ({"type": "habit.create", "name": "Вода"}, "Привычки: «Вода» уже есть"),
    ({"type": "exercise_goal.set", "exercise": "Сальто", "value": "5", "date": "2026-12-01"},
     "Цели: упражнения «Сальто» нет в наборе зарядки"),
    ({"type": "exercise_goal.set", "exercise": "Планка", "value": "11:00", "date": D}, "Цели: дата 03.11 уже прошла"),
]


@pytest.mark.parametrize(("action", "reason"), CASES)
async def test_refusals(golden_app: Any, action: dict[str, Any], reason: str) -> None:  # noqa: F811
    app, actor = golden_app
    commands = app.ctx.services["ai_commands"]
    parsed = parse_reply(json.dumps({"actions": [action]}, ensure_ascii=False))
    plan = await Planner(commands.services, actor, TODAY, commands._tz).plan(parsed.actions)
    shown = plan.skipped + [op["line"] for op in plan.ops]
    assert len(shown) == 1 and shown[0].startswith(reason), shown


async def test_day_off_twice(golden_app: Any) -> None:  # noqa: F811
    app, actor = golden_app
    commands = app.ctx.services["ai_commands"]
    await app.ctx.services["days"].toggle_day_off(actor, date(2026, 11, 2))
    parsed = parse_reply(json.dumps({"actions": [{"type": "day.off", "day": Y}]}))
    plan = await Planner(commands.services, actor, TODAY, commands._tz).plan(parsed.actions)
    assert plan.skipped == ["Выходной: 02.11 уже отмечен"]


async def test_sections_switched_off(golden_app: Any) -> None:  # noqa: F811
    """Модуль выключен в ENABLED_MODULES — его действия отбрасываются с причиной, остальные выполняются."""
    app, actor = golden_app
    commands = app.ctx.services["ai_commands"]
    services = dataclasses.replace(commands.services, food=None, warmup=None, habits=None, workouts=None, runs=None)
    actions = [
        {"type": "food.add", "day": D, "item": "Коктейль"},
        {"type": "food.delete", "day": D, "item": "Коктейль"},
        {"type": "warmup.add", "day": D, "values": {"Планка": "6:00"}},
        {"type": "habit.mark", "day": D, "habit": "Вода"},
        {"type": "workout.set", "day": D, "exercise": "Присед", "reps": [8], "weight": 100},
        {"type": "run.add", "day": D, "distance_km": 5, "time": "28:40"},
        {"type": "recipe.create", "name": "Сырники", "kcal": 350, "protein": 20, "fat": 15, "carbs": 30},
        {"type": "habit.create", "name": "Чтение"},
        {"type": "day.off", "day": Y},
    ]
    parsed = parse_reply(json.dumps({"actions": actions}))
    plan = await Planner(services, actor, TODAY, commands._tz).plan(parsed.actions)
    assert plan.skipped == ["Еда: раздел выключен", "Еда: раздел выключен", "Зарядка: раздел выключен",
                            "Привычки: раздел выключен", "Тренировки: раздел выключен", "Бег: раздел выключен",
                            "Рецепты: раздел выключен", "Привычки: раздел выключен"]
    assert [op["line"] for op in plan.ops] == ["🛌 02.11 Выходной"]
