from __future__ import annotations

from datetime import date
from typing import Any

from habit_bot.kernel.identity import Actor
from habit_bot.kernel.modules import Module, ModuleContext, Stage
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
