from __future__ import annotations

from datetime import date
from typing import Any

from habit_bot.kernel.identity import Actor
from habit_bot.kernel.modules import Module, ModuleContext, Stage
from habit_bot.modules.days.public import DayEntry
from habit_bot.modules.runs.domain.runs import run_line
from habit_bot.modules.runs.usecases import Runs


class RunsModule(Module):
    """Бег (раздел 3.5, часть 8): забеги, темп и скорость, сравнение, рекорды, строка карточки дня."""

    key = "runs"
    stage = Stage.MVP
    depends_on = ("users", "days")

    def register(self, ctx: ModuleContext) -> None:
        days = ctx.services["days"]
        runs = Runs(uow=ctx.uow, clock=ctx.clock, idempotency=ctx.idempotency)
        ctx.services["runs"] = runs
        days.add_mover("run", runs)

        async def listing(actor: Actor, day: date) -> list[DayEntry]:
            found = []
            for public_id, at, value in await runs.day_list(actor, day):
                line = run_line(value)
                found.append(DayEntry("run", public_id, f"{line.split(' · темп')[0]} · {at.astimezone(days.tz):%H:%M}",
                                      line))
            return found

        async def remove(actor: Actor, public_id: str) -> bool:
            return await runs.delete(actor, public_id) is not None

        days.add_entries("run", listing, remove)

        async def card_section(actor: Actor, day: date) -> list[str]:
            return [run_line(r) for r in await runs.day_runs(actor, day)]

        days.add_card_section(card_section)

        channel = ctx.channel("telegram")
        if channel is not None:
            from habit_bot.channels.telegram.channel import TelegramChannel
            from habit_bot.modules.runs.telegram.handlers import build_runs_router

            assert isinstance(channel, TelegramChannel)

            def week_progress() -> Any:
                return ctx.services.get("workouts.week")  # модуль workouts подключается позже

            channel.add_router(build_runs_router(runs, days, channel.screens, lambda: channel.day_card,
                                                 week_progress))
